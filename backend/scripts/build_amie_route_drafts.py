"""Build non-executable AMIE route proposals with Gemini and local RAG.

The pipeline intentionally has two model stages.  Gemini first proposes canonical
disease names, then every name becomes an independent RAG query before Gemini may
propose semantic facts, disease clues, or Safety candidates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

from amie.rule_config import clinical_fact_descriptions
from domain.questionnaires import (
    CANDIDATE_DISEASE_ROUTES,
    CANDIDATE_ROUTE_CATALOG,
    QUESTIONNAIRE_DATA_DIR,
    ROUTE_CATALOG_PATH,
)
from infrastructure.llm import LLMClient
from scripts.amie_route_draft_prompts import discovery_messages, proposal_messages
from scripts.amie_route_draft_schema import (
    PIPELINE_VERSION,
    SCHEMA_VERSION,
    validate_bundle,
    validate_discovery,
    validate_proposal,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
BASE_SAFETY_PATH = BACKEND_DIR / "amie" / "rules" / "safety_rules.json"
DEFAULT_OUTPUT_ROOT = BACKEND_DIR / "questionnaire_drafts" / "clinical_artifacts" / "v1"
DISCOVERY_MAX_TOKENS = 5000
PROPOSAL_MAX_TOKENS = 24000
_RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} 必須是 JSON object")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _parse_json(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        start = value.find("{")
        end = value.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("模型未回傳 JSON object") from None
        try:
            parsed = json.loads(value[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"模型 JSON 無法解析：{exc.msg}") from None
    if not isinstance(parsed, dict):
        raise ValueError("模型輸出必須是 JSON object")
    return parsed


def _questionnaire(route: str) -> tuple[dict[str, Any], Path, str]:
    path = QUESTIONNAIRE_DATA_DIR / f"{route}.json"
    raw = path.read_bytes()
    document = json.loads(raw)
    if not isinstance(document, dict) or document.get("id") != route:
        raise ValueError(f"問卷資料不正確：{path}")
    return document, path, _sha256_bytes(raw)


def _input_hashes(questionnaire_sha256: str) -> dict[str, str]:
    return {
        "questionnaire_sha256": questionnaire_sha256,
        "route_catalog_sha256": _sha256_bytes(ROUTE_CATALOG_PATH.read_bytes()),
        "base_safety_sha256": _sha256_bytes(BASE_SAFETY_PATH.read_bytes()),
    }


def _ascii_keywords(catalog_entry: dict[str, Any]) -> list[str]:
    values = []
    for keyword in catalog_entry["keywords"]:
        if keyword.isascii() and keyword not in values:
            values.append(keyword)
    return values


def _initial_queries(route: str, catalog_entry: dict[str, Any]) -> list[tuple[str, str]]:
    subject = " ".join([route.replace("_", " "), *_ascii_keywords(catalog_entry)])
    return [
        (
            "route_discovery",
            f"{subject} differential diagnosis diseases clinical presentation symptoms history",
        ),
        (
            "route_safety",
            f"{subject} red flags emergency warning signs urgent referral rule out",
        ),
    ]


def _normalize_result(raw: dict[str, Any], *, scope: str, query: str) -> tuple[str, dict[str, Any]]:
    text = str(raw.get("text") or "").strip()
    if not text:
        raise ValueError("RAG result 缺少 text")
    text_hash = _sha256_text(text)
    chunk_id = str(raw.get("chunk_id") or text_hash[:20]).strip()
    identity = chunk_id or text_hash
    routes = raw.get("routes")
    if not isinstance(routes, list):
        route = str(raw.get("route") or "").strip()
        routes = [route] if route else []
    routes = list(dict.fromkeys(str(item).strip() for item in routes if str(item).strip()))
    source_id = f"rag-{_sha256_text(identity + text_hash)[:16]}"
    title = str(raw.get("title") or raw.get("source") or chunk_id).strip()
    source = str(raw.get("source") or "local_rag").strip()
    return identity, {
        "id": source_id,
        "chunk_id": chunk_id,
        "title": title[:500],
        "source": source[:200],
        "url": str(raw.get("url") or "")[:1000],
        "routes": routes[:10],
        "retrieval_scopes": [scope],
        "retrieval_queries": [query],
        "distance": float(raw.get("distance", 1.0)),
        "excerpt": text[:1800],
        "text_sha256": text_hash,
    }


def _add_results(
    accumulated: dict[str, dict[str, Any]],
    results: list[dict[str, Any]],
    *,
    scope: str,
    query: str,
    limit: int,
) -> None:
    added = 0
    for raw in results:
        if added >= limit:
            break
        try:
            identity, normalized = _normalize_result(raw, scope=scope, query=query)
        except (TypeError, ValueError):
            continue
        existing = accumulated.get(identity)
        if existing is None:
            accumulated[identity] = normalized
        else:
            if scope not in existing["retrieval_scopes"]:
                existing["retrieval_scopes"].append(scope)
            if query not in existing["retrieval_queries"]:
                existing["retrieval_queries"].append(query)
            existing["routes"] = list(dict.fromkeys([*existing["routes"], *normalized["routes"]]))
            existing["distance"] = min(existing["distance"], normalized["distance"])
        added += 1


def _retrieve_initial(
    route: str,
    catalog_entry: dict[str, Any],
    retrieve_fn: Callable[..., list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[str]]:
    accumulated: dict[str, dict[str, Any]] = {}
    queries = _initial_queries(route, catalog_entry)
    for scope, query in queries:
        results = retrieve_fn(query, primary_route=None, purpose="diagnosis", final_k=12)
        _add_results(accumulated, results, scope=scope, query=query, limit=8)
    sources = list(accumulated.values())[:16]
    if not sources:
        raise RuntimeError(f"{route} 的初始 RAG 沒有可用證據")
    return sources, [query for _, query in queries]


def _call_validated(
    llm: LLMClient,
    message_builder: Callable[[str | None], list[dict[str, str]]],
    validator: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    max_tokens: int,
    max_attempts: int,
) -> tuple[dict[str, Any], str]:
    correction: str | None = None
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        messages = message_builder(correction)
        prompt_text = "\n\n".join(item["content"] for item in messages)
        try:
            response = llm.generate_text(messages, temperature=0, max_tokens=max_tokens)
            parsed = _parse_json(response)
            return validator(parsed), _sha256_text(prompt_text)
        except Exception as exc:  # retry transport, JSON, and strict schema failures
            last_error = exc
            correction = f"{type(exc).__name__}: {str(exc)[:1200]}"
            if attempt < max_attempts:
                time.sleep(min(4, 2 ** (attempt - 1)))
    assert last_error is not None
    raise RuntimeError(
        f"Gemini 在 {max_attempts} 次內未產生有效 artifact："
        f"{type(last_error).__name__}: {str(last_error)[:1200]}"
    ) from last_error


def _discovery_document(
    *,
    route: str,
    catalog_entry: dict[str, Any],
    questionnaire: dict[str, Any],
    inputs: dict[str, str],
    sources: list[dict[str, Any]],
    queries: list[str],
    rag_status: dict[str, Any],
    llm: LLMClient,
    max_attempts: int,
) -> dict[str, Any]:
    source_ids = {source["id"] for source in sources}

    def messages(correction: str | None) -> list[dict[str, str]]:
        return discovery_messages(
            route=route,
            catalog_entry=catalog_entry,
            questionnaire=questionnaire,
            sources=sources,
            correction=correction,
        )

    def validate_candidate(value: dict[str, Any]) -> dict[str, Any]:
        _normalize_discovery_citations(value, source_ids=source_ids)
        return validate_discovery(
            value,
            route=route,
            catalog_entry=catalog_entry,
            source_ids=source_ids,
        )

    discovery, prompt_hash = _call_validated(
        llm,
        messages,
        validate_candidate,
        max_tokens=DISCOVERY_MAX_TOKENS,
        max_attempts=max_attempts,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "amie_disease_name_discovery",
        "route": route,
        "lifecycle": {"status": "model_generated_provisional", "executable": False},
        "inputs": {
            **inputs,
            "rag_index_version": str(rag_status["index_version"]),
            "rag_collections": list(rag_status["collections"]),
            "rag_queries": queries,
            "rag_corpus_hash": _corpus_hash(sources),
        },
        "generation": _generation(llm, prompt_hash, DISCOVERY_MAX_TOKENS),
        "sources": sources,
        "discovery": discovery,
    }


def _normalize_discovery_citations(value: dict[str, Any], *, source_ids: set[str]) -> None:
    if not isinstance(value, dict) or not source_ids:
        return
    evidence_pack = sorted(source_ids)
    repaired: list[str] = []
    for collection_name in ("diseases", "review_notes"):
        collection = value.get(collection_name)
        if not isinstance(collection, list):
            continue
        for index, item in enumerate(collection):
            if not isinstance(item, dict) or "source_ids" not in item:
                continue
            citations = item["source_ids"]
            if (
                not isinstance(citations, list)
                or not citations
                or any(not isinstance(source_id, str) for source_id in citations)
                or not set(citations).issubset(source_ids)
                or len(citations) != len(set(citations))
            ):
                item["source_ids"] = evidence_pack
                repaired.append(f"{collection_name}[{index}]")
    notes = value.get("review_notes")
    if repaired and isinstance(notes, list):
        notes.append(
            {
                "severity": "warning",
                "note": (
                    "Local compiler replaced missing, duplicate, or out-of-scope discovery "
                    "citations with the complete route RAG evidence pack for: "
                    + ", ".join(repaired[:12])
                    + ". These citations remain unverified."
                ),
                "source_ids": evidence_pack,
            }
        )


def _generation(llm: LLMClient, prompt_hash: str, max_tokens: int) -> dict[str, Any]:
    return {
        "pipeline_version": PIPELINE_VERSION,
        "provider": llm.provider,
        "model": llm.model,
        "temperature": 0,
        "max_output_tokens": max_tokens,
        "prompt_sha256": prompt_hash,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _corpus_hash(sources: list[dict[str, Any]]) -> str:
    frozen = [
        {
            "id": source["id"],
            "text_sha256": source["text_sha256"],
            "retrieval_scopes": sorted(source["retrieval_scopes"]),
            "retrieval_queries": sorted(source["retrieval_queries"]),
        }
        for source in sorted(sources, key=lambda item: item["id"])
    ]
    return _sha256_text(json.dumps(frozen, sort_keys=True, separators=(",", ":")))


def _load_discovery(
    path: Path,
    *,
    route: str,
    catalog_entry: dict[str, Any],
    inputs: dict[str, str],
    model: str,
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    document = _read_json(path)
    if document.get("artifact_kind") != "amie_disease_name_discovery":
        raise RuntimeError(f"既有 discovery 類型不正確：{path}")
    if document.get("route") != route or document.get("lifecycle") != {
        "status": "model_generated_provisional",
        "executable": False,
    }:
        raise RuntimeError(f"既有 discovery 不可安全續跑：{path}")
    for key, expected in inputs.items():
        if document.get("inputs", {}).get(key) != expected:
            raise RuntimeError(f"既有 discovery 輸入已改變，請使用新 run-id：{path}")
    generation = document.get("generation", {})
    if generation.get("pipeline_version") != PIPELINE_VERSION or generation.get("model") != model:
        raise RuntimeError(f"既有 discovery 模型／pipeline 已改變，請使用新 run-id：{path}")
    sources = document.get("sources", [])
    validate_discovery(
        document.get("discovery"),
        route=route,
        catalog_entry=catalog_entry,
        source_ids={source["id"] for source in sources},
    )
    return document


def _disease_candidates(discovery: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": disease["id"],
            "name": disease["name"],
            "retrieval_query": (
                f"{disease['name']} diagnostic features signs symptoms differential "
                "diagnosis red flags emergency rule out"
            ),
            "discovery_source_ids": disease["source_ids"],
            "disease_rag_source_ids": [],
        }
        for disease in discovery["discovery"]["diseases"]
    ]


def _retrieve_disease_sources(
    initial_sources: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    retrieve_fn: Callable[..., list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    accumulated = {
        source["chunk_id"] or source["text_sha256"]: dict(source) for source in initial_sources
    }
    for candidate in candidates:
        query = candidate["retrieval_query"]
        results = retrieve_fn(query, primary_route=None, purpose="diagnosis", final_k=8)
        _add_results(
            accumulated,
            results,
            scope=candidate["id"],
            query=query,
            limit=4,
        )
    sources = list(accumulated.values())
    if len(sources) > 40:
        raise RuntimeError("合併後 RAG sources 超過 schema 上限")
    for candidate in candidates:
        if not any(candidate["id"] in source["retrieval_scopes"] for source in sources):
            raise RuntimeError(f"疾病名稱 query 沒有可用 RAG 證據：{candidate['name']}")
        candidate["disease_rag_source_ids"] = [
            source["id"] for source in sources if candidate["id"] in source["retrieval_scopes"]
        ]
    return sources


def _proposal_bundle(
    *,
    route: str,
    catalog_entry: dict[str, Any],
    questionnaire: dict[str, Any],
    inputs: dict[str, str],
    discovery: dict[str, Any],
    candidates: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    rag_status: dict[str, Any],
    llm: LLMClient,
    max_attempts: int,
) -> dict[str, Any]:
    source_ids = {source["id"] for source in sources}
    source_scopes = {source["id"]: set(source["retrieval_scopes"]) for source in sources}
    active_facts = clinical_fact_descriptions()
    focused_outputs: list[dict[str, Any]] = []
    prompt_hashes: list[str] = []
    generation_failures: list[tuple[dict[str, Any], Exception]] = []
    generation_targets: list[dict[str, Any] | None] = (
        candidates
        if candidates
        else [None]
        if catalog_entry["disposition"] != "questionnaire"
        else []
    )
    for candidate in generation_targets:
        if candidate is None:
            focused_sources = sources
            focused_candidates: list[dict[str, Any]] = []
        else:
            allowed_ids = {
                *candidate["discovery_source_ids"],
                *candidate["disease_rag_source_ids"],
            }
            focused_sources = [source for source in sources if source["id"] in allowed_ids]
            focused_candidates = [candidate]
        focused_source_ids = {source["id"] for source in focused_sources}
        focused_scopes = {
            source["id"]: set(source["retrieval_scopes"]) for source in focused_sources
        }

        def messages(correction: str | None) -> list[dict[str, str]]:
            return proposal_messages(
                route=route,
                catalog_entry=catalog_entry,
                questionnaire=questionnaire,
                disease_candidates=focused_candidates,
                active_fact_descriptions=active_facts,
                sources=focused_sources,
                correction=correction,
            )

        def validate_focused(value: dict[str, Any]) -> dict[str, Any]:
            _normalize_focused_output(
                value,
                candidate=candidate,
                focused_sources=focused_sources,
                disposition=catalog_entry["disposition"],
            )
            result = validate_proposal(
                value,
                route=route,
                questionnaire=questionnaire,
                catalog_entry=catalog_entry,
                existing_fact_codes=set(active_facts),
                source_ids=focused_source_ids,
                source_scopes=focused_scopes,
                disease_candidates=focused_candidates,
            )
            if (
                candidate is None
                and catalog_entry["disposition"] == "questionnaire"
                and (result["fact_proposals"] or result["semantic_options"] or result["profiles"])
            ):
                raise ValueError("沒有疾病名稱 discovery 時不可產生疾病語意標籤")
            return result

        try:
            focused, focused_prompt_hash = _call_validated(
                llm,
                messages,
                validate_focused,
                max_tokens=PROPOSAL_MAX_TOKENS,
                max_attempts=max_attempts,
            )
            focused_outputs.append(focused)
            prompt_hashes.append(focused_prompt_hash)
        except Exception as exc:
            if candidate is None:
                focused_outputs.append(
                    _failed_route_level_output(
                        route=route,
                        catalog_entry=catalog_entry,
                        source_ids=sorted(focused_source_ids),
                        exc=exc,
                    )
                )
                prompt_hashes.append(
                    _sha256_text("\n\n".join(item["content"] for item in messages(None)))
                )
                print(
                    f"  ROUTE_LEVEL_FALLBACK {route}: {type(exc).__name__}: {str(exc)[:500]}",
                    flush=True,
                )
                continue
            generation_failures.append((candidate, exc))
            print(
                f"  DISEASE_FAILED {route}/{candidate['id']}: "
                f"{type(exc).__name__}: {str(exc)[:500]}",
                flush=True,
            )

    proposal = _merge_focused_proposals(
        route=route,
        catalog_entry=catalog_entry,
        candidates=candidates,
        sources=sources,
        focused_outputs=focused_outputs,
        failures=generation_failures,
    )
    validate_proposal(
        proposal,
        route=route,
        questionnaire=questionnaire,
        catalog_entry=catalog_entry,
        existing_fact_codes=set(active_facts),
        source_ids=source_ids,
        source_scopes=source_scopes,
        disease_candidates=candidates,
    )
    prompt_hash = _sha256_text("\n".join(prompt_hashes) or "no-successful-model-output")
    queries = list(
        dict.fromkeys(query for source in sources for query in source["retrieval_queries"])
    )
    bundle = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "amie_route_draft",
        "route": route,
        "label": questionnaire["label"],
        "lifecycle": {"status": "model_generated_provisional", "executable": False},
        "inputs": {
            **inputs,
            "rag_index_version": str(rag_status["index_version"]),
            "rag_collections": list(rag_status["collections"]),
            "rag_query": json.dumps(queries, ensure_ascii=False, separators=(",", ":")),
            "rag_corpus_hash": _corpus_hash(sources),
        },
        "generation": _generation(llm, prompt_hash, PROPOSAL_MAX_TOKENS),
        "sources": sources,
        "disease_candidates": candidates,
        "proposal": proposal,
    }
    validate_bundle(bundle)
    return bundle


def _failed_route_level_output(
    *,
    route: str,
    catalog_entry: dict[str, Any],
    source_ids: list[str],
    exc: Exception,
) -> dict[str, Any]:
    """Return an explicit non-clinical stub when urgent/handoff generation fails."""
    return {
        "route": route,
        "evidence_status": "insufficient",
        "route_review": {
            "recommended_disposition": catalog_entry["disposition"],
            "recommended_clinical_domain": catalog_entry["clinical_domain"],
            "rationale": (
                "The existing fail-closed disposition is retained because Gemini did not "
                "produce a schema-valid route-level clinical artifact."
            ),
            "source_ids": source_ids,
        },
        "fact_proposals": [],
        "semantic_options": [],
        "profile_status": "not_applicable",
        "profiles": [],
        "safety_proposals": [],
        "unsupported_requirements": [
            {
                "requirement": "Generate validated route-level fact and Safety proposals",
                "reason": f"Gemini generation failed strict validation: {str(exc)[:900]}",
            }
        ],
        "review_notes": [
            {
                "severity": "critical",
                "note": (
                    "No model-generated Safety proposal was accepted for this urgent/handoff "
                    "route. The current fail-closed disposition must remain unchanged, and a "
                    "qualified reviewer must regenerate and assess this artifact."
                ),
                "source_ids": source_ids,
            }
        ],
    }


def _normalize_focused_output(
    value: dict[str, Any],
    *,
    candidate: dict[str, Any] | None,
    focused_sources: list[dict[str, Any]],
    disposition: str,
) -> None:
    """Apply narrow, auditable compiler repairs before strict validation.

    Only citation lists and unreachable proposed facts are normalized. Clinical
    values, mappings, disease names, weights, and Safety conditions are never
    invented or rewritten here.
    """
    if not isinstance(value, dict):
        return
    if candidate is not None:
        _namespace_candidate_codes(value, candidate=candidate)
    allowed_ids = (
        list(candidate["disease_rag_source_ids"])
        if candidate is not None
        else [source["id"] for source in focused_sources]
    )
    allowed = set(allowed_ids)
    repaired_paths: list[str] = []

    def repair_citations(item: Any, path: str) -> None:
        if not isinstance(item, dict) or "source_ids" not in item:
            return
        citations = item["source_ids"]
        if (
            not isinstance(citations, list)
            or not citations
            or any(not isinstance(source_id, str) for source_id in citations)
            or not set(citations).issubset(allowed)
            or len(citations) != len(set(citations))
        ):
            item["source_ids"] = allowed_ids
            repaired_paths.append(path)

    repair_citations(value.get("route_review"), "route_review")
    for collection_name in ("fact_proposals", "semantic_options", "safety_proposals"):
        collection = value.get(collection_name)
        if isinstance(collection, list):
            for index, item in enumerate(collection):
                repair_citations(item, f"{collection_name}[{index}]")
    profiles = value.get("profiles")
    if isinstance(profiles, list):
        for index, profile in enumerate(profiles):
            repair_citations(profile, f"profiles[{index}]")
            if isinstance(profile, dict) and isinstance(profile.get("clues"), list):
                for clue_index, clue in enumerate(profile["clues"]):
                    repair_citations(clue, f"profiles[{index}].clues[{clue_index}]")
    notes = value.get("review_notes")
    if isinstance(notes, list):
        for index, note in enumerate(notes):
            repair_citations(note, f"review_notes[{index}]")

    facts = value.get("fact_proposals")
    semantics = value.get("semantic_options")
    if isinstance(facts, list) and isinstance(semantics, list):
        reachable = {
            code
            for semantic in semantics
            if isinstance(semantic, dict) and isinstance(semantic.get("mapping"), dict)
            for key in ("findings", "negated_findings")
            for code in semantic["mapping"].get(key, [])
            if isinstance(code, str)
        }
        removed_items = [
            fact
            for fact in facts
            if isinstance(fact, dict)
            and isinstance(fact.get("code"), str)
            and fact["code"] not in reachable
        ]
        removed_codes = {fact["code"] for fact in removed_items}
        if removed_codes:
            value["fact_proposals"] = [
                fact
                for fact in facts
                if not isinstance(fact, dict) or fact.get("code") not in removed_codes
            ]
            safety = value.get("safety_proposals")
            removed_safety_codes: set[str] = set()
            if isinstance(safety, list):
                kept_safety = []
                for rule in safety:
                    when = rule.get("when", {}) if isinstance(rule, dict) else {}
                    referenced = {
                        code
                        for key in ("all_findings", "any_findings")
                        for code in when.get(key, [])
                    }
                    if referenced & removed_codes:
                        if isinstance(rule, dict) and isinstance(rule.get("code"), str):
                            removed_safety_codes.add(rule["code"])
                    else:
                        kept_safety.append(rule)
                value["safety_proposals"] = kept_safety
            if isinstance(profiles, list):
                kept_profiles = []
                for profile in profiles:
                    if not isinstance(profile, dict) or not isinstance(profile.get("clues"), list):
                        kept_profiles.append(profile)
                        continue
                    profile["clues"] = [
                        clue
                        for clue in profile["clues"]
                        if not isinstance(clue, dict) or clue.get("fact") not in removed_codes
                    ]
                    linked = set(profile.get("safety_rule_codes", []))
                    if (
                        not profile["clues"]
                        or linked & removed_safety_codes
                        or (
                            profile.get("must_not_miss")
                            and not any(
                                clue.get("status") == "absent"
                                for clue in profile["clues"]
                                if isinstance(clue, dict)
                            )
                        )
                    ):
                        continue
                    kept_profiles.append(profile)
                value["profiles"] = kept_profiles
                if disposition == "questionnaire" and not kept_profiles:
                    value["profile_status"] = "insufficient_evidence"
            if isinstance(value.get("unsupported_requirements"), list):
                value["unsupported_requirements"].append(
                    {
                        "requirement": "Use free-text-only proposed facts in disease scoring",
                        "reason": (
                            "The current draft compiler only permits facts reachable from exact "
                            "choice options; text/date/duration extraction needs a separate engine contract."
                        ),
                    }
                )
            if isinstance(notes, list):
                removed_source_ids = list(
                    dict.fromkeys(
                        source_id
                        for fact in removed_items
                        for source_id in fact.get("source_ids", [])
                    )
                )
                notes.append(
                    {
                        "severity": "warning",
                        "note": (
                            "Local compiler removed proposed facts and dependent clues that no exact "
                            "choice option can produce; the content remains available only as an "
                            "unsupported review requirement."
                        ),
                        "source_ids": removed_source_ids or allowed_ids,
                    }
                )

    if repaired_paths and isinstance(notes, list):
        notes.append(
            {
                "severity": "warning",
                "note": (
                    "Local compiler replaced missing, duplicate, or out-of-scope citations with "
                    "the complete single-disease RAG evidence pack for: "
                    + ", ".join(repaired_paths[:12])
                    + ". Every repaired citation remains unverified and requires source-level review."
                ),
                "source_ids": allowed_ids,
            }
        )


def _namespace_candidate_codes(value: dict[str, Any], *, candidate: dict[str, Any]) -> None:
    """Mechanically namespace generated codes and update internal references."""
    route = candidate["id"].split("__", 1)[0]
    fact_prefix = f"{candidate['id']}__"
    safety_prefix = f"experimental_{candidate['id']}__"
    if len(fact_prefix) > 78:
        fact_prefix = f"{route}__d_{_sha256_text(candidate['id'])[:12]}__"
    if len(safety_prefix) > 78:
        safety_prefix = f"experimental_{route}__d_{_sha256_text(candidate['id'])[:12]}__"

    def code_with_prefix(prefix: str, old: str) -> str:
        suffix = re.sub(r"[^a-z0-9]+", "_", old.casefold()).strip("_") or "generated"
        experimental_route_prefix = f"experimental_{route}__"
        if suffix.startswith(experimental_route_prefix):
            suffix = suffix[len(experimental_route_prefix) :]
        elif suffix.startswith(f"{route}__"):
            suffix = suffix[len(route) + 2 :]
        room = 96 - len(prefix)
        if len(suffix) > room:
            digest = _sha256_text(old)[:10]
            suffix = f"{suffix[: max(1, room - 12)].rstrip('_')}__{digest}"
        return f"{prefix}{suffix}"

    fact_codes: dict[str, str] = {}
    facts = value.get("fact_proposals")
    if isinstance(facts, list):
        for fact in facts:
            if not isinstance(fact, dict) or not isinstance(fact.get("code"), str):
                continue
            old = fact["code"]
            if old.startswith(fact_prefix):
                continue
            fact["code"] = code_with_prefix(fact_prefix, old)
            fact_codes[old] = fact["code"]

    safety_codes: dict[str, str] = {}
    safety = value.get("safety_proposals")
    if isinstance(safety, list):
        for rule in safety:
            if not isinstance(rule, dict) or not isinstance(rule.get("code"), str):
                continue
            old = rule["code"]
            if old.startswith(safety_prefix):
                continue
            rule["code"] = code_with_prefix(safety_prefix, old)
            safety_codes[old] = rule["code"]

    semantics = value.get("semantic_options")
    if isinstance(semantics, list):
        for semantic in semantics:
            mapping = semantic.get("mapping", {}) if isinstance(semantic, dict) else {}
            for key in ("findings", "negated_findings"):
                if isinstance(mapping.get(key), list):
                    mapping[key] = [fact_codes.get(code, code) for code in mapping[key]]
    profiles = value.get("profiles")
    if isinstance(profiles, list):
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            if isinstance(profile.get("safety_rule_codes"), list):
                profile["safety_rule_codes"] = [
                    safety_codes.get(code, code) for code in profile["safety_rule_codes"]
                ]
            if isinstance(profile.get("clues"), list):
                for clue in profile["clues"]:
                    if isinstance(clue, dict) and isinstance(clue.get("fact"), str):
                        clue["fact"] = fact_codes.get(clue["fact"], clue["fact"])
    if isinstance(safety, list):
        for rule in safety:
            when = rule.get("when", {}) if isinstance(rule, dict) else {}
            for key in ("all_findings", "any_findings"):
                if isinstance(when.get(key), list):
                    when[key] = [fact_codes.get(code, code) for code in when[key]]
    if (fact_codes or safety_codes) and isinstance(value.get("review_notes"), list):
        value["review_notes"].append(
            {
                "severity": "info",
                "note": (
                    "Local compiler mechanically namespaced generated codes and updated all "
                    "internal references; no clinical values or conditions were changed."
                ),
                "source_ids": candidate["disease_rag_source_ids"],
            }
        )


def _merge_focused_proposals(
    *,
    route: str,
    catalog_entry: dict[str, Any],
    candidates: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    focused_outputs: list[dict[str, Any]],
    failures: list[tuple[dict[str, Any], Exception]],
) -> dict[str, Any]:
    facts: list[dict[str, Any]] = []
    profiles: list[dict[str, Any]] = []
    safety: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    semantics_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for output in focused_outputs:
        facts.extend(output["fact_proposals"])
        profiles.extend(output["profiles"])
        safety.extend(output["safety_proposals"])
        unsupported.extend(output["unsupported_requirements"])
        notes.extend(output["review_notes"])
        for semantic in output["semantic_options"]:
            key = (semantic["field"], semantic["option"])
            existing = semantics_by_key.get(key)
            if existing is None:
                semantics_by_key[key] = semantic
                continue
            for mapping_key in ("findings", "negated_findings"):
                values = [
                    *existing["mapping"].get(mapping_key, []),
                    *semantic["mapping"].get(mapping_key, []),
                ]
                if values:
                    existing["mapping"][mapping_key] = list(dict.fromkeys(values))
            for scalar_key in ("onset", "course", "duration", "severity", "new_or_changed"):
                incoming = semantic["mapping"].get(scalar_key)
                current = existing["mapping"].get(scalar_key)
                if incoming is not None and current is None:
                    existing["mapping"][scalar_key] = incoming
                elif incoming is not None and current != incoming:
                    existing["mapping"].pop(scalar_key, None)
                    notes.append(
                        {
                            "severity": "warning",
                            "note": (
                                f"Merged disease drafts disagreed on {key[0]}/{key[1]} "
                                f"scalar {scalar_key}; reducer omitted that scalar."
                            ),
                            "source_ids": list(
                                dict.fromkeys([*existing["source_ids"], *semantic["source_ids"]])
                            ),
                        }
                    )
            existing["disease_ids"] = list(
                dict.fromkeys([*existing["disease_ids"], *semantic["disease_ids"]])
            )
            existing["source_ids"] = list(
                dict.fromkeys([*existing["source_ids"], *semantic["source_ids"]])
            )

    for candidate, exc in failures:
        unsupported.append(
            {
                "requirement": f"Generate disease semantics for {candidate['name']}",
                "reason": (
                    f"Strict Gemini output validation failed: {type(exc).__name__}: "
                    f"{str(exc)[:700]}"
                ),
            }
        )
        notes.append(
            {
                "severity": "critical",
                "note": (
                    f"No validated semantic/profile proposal was produced for "
                    f"{candidate['name']}; clinical review and regeneration are required."
                ),
                "source_ids": candidate["disease_rag_source_ids"],
            }
        )

    dispositions = [catalog_entry["disposition"]]
    dispositions.extend(
        output["route_review"]["recommended_disposition"] for output in focused_outputs
    )
    disposition_rank = {"questionnaire": 1, "handoff": 2, "urgent": 3}
    recommended_disposition = max(dispositions, key=disposition_rank.__getitem__)
    review_source_ids = list(
        dict.fromkeys(
            source_id
            for output in focused_outputs
            for source_id in output["route_review"]["source_ids"]
        )
    )
    if not review_source_ids:
        review_source_ids = [sources[0]["id"]]
    clinical_lists = [facts, list(semantics_by_key.values()), profiles, safety]
    evidence_status = (
        "insufficient"
        if not any(clinical_lists)
        else "sufficient"
        if not failures
        and focused_outputs
        and all(output["evidence_status"] == "sufficient" for output in focused_outputs)
        else "limited"
    )
    profile_status = (
        "not_applicable"
        if catalog_entry["disposition"] != "questionnaire"
        else "proposed"
        if profiles
        else "insufficient_evidence"
    )
    return {
        "route": route,
        "evidence_status": evidence_status,
        "route_review": {
            "recommended_disposition": recommended_disposition,
            "recommended_clinical_domain": catalog_entry["clinical_domain"],
            "rationale": (
                "Local reducer selected the safest disposition from independently "
                "validated Gemini disease drafts; qualified clinical review is required."
            ),
            "source_ids": review_source_ids,
        },
        "fact_proposals": facts,
        "semantic_options": list(semantics_by_key.values()),
        "profile_status": profile_status,
        "profiles": profiles,
        "safety_proposals": safety,
        "unsupported_requirements": unsupported,
        "review_notes": notes,
    }


def _validate_complete_bundle(
    bundle: dict[str, Any],
    *,
    route: str,
    questionnaire: dict[str, Any],
    catalog_entry: dict[str, Any],
) -> dict[str, Any]:
    validate_bundle(bundle)
    sources = bundle["sources"]
    validate_proposal(
        bundle["proposal"],
        route=route,
        questionnaire=questionnaire,
        catalog_entry=catalog_entry,
        existing_fact_codes=set(clinical_fact_descriptions()),
        source_ids={source["id"] for source in sources},
        source_scopes={source["id"]: set(source["retrieval_scopes"]) for source in sources},
        disease_candidates=bundle["disease_candidates"],
    )
    return bundle


def build_route(
    *,
    route: str,
    run_dir: Path,
    rag_status: dict[str, Any],
    llm: LLMClient,
    retrieve_fn: Callable[..., list[dict[str, Any]]],
    max_attempts: int,
) -> str:
    catalog_entry = CANDIDATE_ROUTE_CATALOG[route]
    questionnaire, _, questionnaire_sha = _questionnaire(route)
    inputs = _input_hashes(questionnaire_sha)
    output_path = run_dir / "routes" / f"{route}.json"
    if output_path.exists():
        existing = _validate_complete_bundle(
            _read_json(output_path),
            route=route,
            questionnaire=questionnaire,
            catalog_entry=catalog_entry,
        )
        if existing["inputs"]["questionnaire_sha256"] != questionnaire_sha:
            raise RuntimeError(f"既有 route artifact 輸入已變更，請使用新 run-id：{route}")
        return "skip"

    discovery_path = run_dir / "discoveries" / f"{route}.json"
    discovery = _load_discovery(
        discovery_path,
        route=route,
        catalog_entry=catalog_entry,
        inputs=inputs,
        model=llm.model,
    )
    if discovery is None:
        initial_sources, initial_queries = _retrieve_initial(route, catalog_entry, retrieve_fn)
        discovery = _discovery_document(
            route=route,
            catalog_entry=catalog_entry,
            questionnaire=questionnaire,
            inputs=inputs,
            sources=initial_sources,
            queries=initial_queries,
            rag_status=rag_status,
            llm=llm,
            max_attempts=max_attempts,
        )
        _write_json(discovery_path, discovery)

    candidates = _disease_candidates(discovery)
    sources = _retrieve_disease_sources(discovery["sources"], candidates, retrieve_fn)
    bundle = _proposal_bundle(
        route=route,
        catalog_entry=catalog_entry,
        questionnaire=questionnaire,
        inputs=inputs,
        discovery=discovery,
        candidates=candidates,
        sources=sources,
        rag_status=rag_status,
        llm=llm,
        max_attempts=max_attempts,
    )
    _write_json(output_path, bundle)
    return "wrote"


def _manifest(run_id: str, run_dir: Path, rag_status: dict[str, Any], model: str) -> dict[str, Any]:
    route_rows = []
    failures = []
    global_codes: dict[str, str] = {}
    totals = {
        "disease_candidates": 0,
        "facts": 0,
        "semantic_options": 0,
        "profiles": 0,
        "missing_candidate_profiles": 0,
        "safety_rules": 0,
        "critical_review_notes": 0,
        "citation_repair_notes": 0,
        "unreachable_fact_prune_notes": 0,
    }
    routes_without_safety: list[str] = []
    insufficient_evidence_routes: list[str] = []
    routes_with_critical_notes: list[str] = []
    for route in CANDIDATE_DISEASE_ROUTES:
        path = run_dir / "routes" / f"{route}.json"
        if not path.exists():
            failures.append(route)
            continue
        questionnaire, _, _ = _questionnaire(route)
        document = _validate_complete_bundle(
            _read_json(path),
            route=route,
            questionnaire=questionnaire,
            catalog_entry=CANDIDATE_ROUTE_CATALOG[route],
        )
        proposal = document["proposal"]
        for collection, key in (
            (proposal["fact_proposals"], "code"),
            (proposal["profiles"], "id"),
            (proposal["safety_proposals"], "code"),
        ):
            for item in collection:
                code = item[key]
                previous = global_codes.setdefault(code, route)
                if previous != route:
                    raise ValueError(f"跨 route code collision：{code}")
        counts = {
            "disease_candidates": len(document["disease_candidates"]),
            "facts": len(proposal["fact_proposals"]),
            "semantic_options": len(proposal["semantic_options"]),
            "profiles": len(proposal["profiles"]),
            "missing_candidate_profiles": (
                len(document["disease_candidates"]) - len(proposal["profiles"])
            ),
            "safety_rules": len(proposal["safety_proposals"]),
            "critical_review_notes": sum(
                note["severity"] == "critical" for note in proposal["review_notes"]
            ),
            "citation_repair_notes": sum(
                "complete single-disease RAG evidence pack" in note["note"]
                for note in proposal["review_notes"]
            ),
            "unreachable_fact_prune_notes": sum(
                "removed proposed facts" in note["note"] for note in proposal["review_notes"]
            ),
        }
        for key, count in counts.items():
            totals[key] += count
        if not proposal["safety_proposals"]:
            routes_without_safety.append(route)
        if proposal["evidence_status"] == "insufficient":
            insufficient_evidence_routes.append(route)
        if counts["critical_review_notes"]:
            routes_with_critical_notes.append(route)
        route_rows.append(
            {
                "route": route,
                "file": f"routes/{route}.json",
                "sha256": _sha256_bytes(path.read_bytes()),
                "evidence_status": proposal["evidence_status"],
                "profile_status": proposal["profile_status"],
                "disease_name_count": len(document["disease_candidates"]),
                **counts,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "amie_route_draft_manifest",
        "run_id": run_id,
        "lifecycle": {"status": "model_generated_provisional", "executable": False},
        "runtime_eligible": False,
        "clinical_review_ready": False,
        "citation_review_status": "unverified",
        "generation": {
            "pipeline_version": PIPELINE_VERSION,
            "provider": "gemini",
            "model": model,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        "rag": {
            "index_version": str(rag_status["index_version"]),
            "collections": list(rag_status["collections"]),
            "disease_name_directed_retrieval": True,
        },
        "complete": not failures,
        "expected_route_count": len(CANDIDATE_DISEASE_ROUTES),
        "generated_route_count": len(route_rows),
        "failed_or_missing_routes": failures,
        "totals": totals,
        "blocking_summary": {
            "routes_without_safety": routes_without_safety,
            "insufficient_evidence_routes": insufficient_evidence_routes,
            "critical_review_note_count": totals["critical_review_notes"],
            "routes_with_critical_review_notes": routes_with_critical_notes,
            "missing_candidate_profile_count": totals["missing_candidate_profiles"],
        },
        "routes": route_rows,
    }


def _record_failure(run_dir: Path, route: str, exc: Exception) -> None:
    _write_json(
        run_dir / "failures" / f"{route}.json",
        {
            "route": route,
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc)[:1600],
            "failed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="用疾病名稱導向 RAG 與 Gemini 產生 49 route 的不可執行 AMIE 草稿"
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--no-manifest", action="store_true")
    parser.add_argument("--reduce-only", action="store_true")
    args = parser.parse_args()
    if not _RUN_ID.fullmatch(args.run_id):
        raise SystemExit("--run-id 只能使用小寫字母、數字、點、底線與連字號")
    if not 1 <= args.max_attempts <= 5:
        raise SystemExit("--max-attempts 必須介於 1 與 5")

    requested = list(CANDIDATE_DISEASE_ROUTES)
    if args.only:
        unknown = sorted(set(args.only) - set(requested))
        if unknown:
            raise SystemExit(f"--only 指定未知 candidate route：{unknown}")
        requested = [route for route in requested if route in set(args.only)]
    if args.limit is not None:
        if args.limit < 1:
            raise SystemExit("--limit 必須大於 0")
        requested = requested[: args.limit]

    load_dotenv(BACKEND_DIR / ".env")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from knowledge.retrieval import get_rag_status, retrieve

    rag_status = get_rag_status()
    if not rag_status.get("enabled") or not rag_status.get("collections"):
        raise SystemExit("本機 RAG v2 collections 未完整可用")
    run_dir = (args.output_root / args.run_id).resolve()
    if not args.reduce_only:
        if os.getenv("LLM_PROVIDER", "").strip().lower() != "gemini":
            raise SystemExit("此 pipeline 必須明確設定 LLM_PROVIDER=gemini")
        llm = LLMClient()
        if llm.provider != "gemini":
            raise SystemExit("此 pipeline 只允許 Gemini provider")
        for position, route in enumerate(requested, start=1):
            print(f"[{position}/{len(requested)}] BUILD {route}", flush=True)
            try:
                outcome = build_route(
                    route=route,
                    run_dir=run_dir,
                    rag_status=rag_status,
                    llm=llm,
                    retrieve_fn=retrieve,
                    max_attempts=args.max_attempts,
                )
                print(f"[{position}/{len(requested)}] {outcome.upper()} {route}", flush=True)
            except Exception as exc:
                _record_failure(run_dir, route, exc)
                print(
                    f"[{position}/{len(requested)}] FAILED {route}: "
                    f"{type(exc).__name__}: {str(exc)[:300]}",
                    flush=True,
                )

    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    manifest = _manifest(args.run_id, run_dir, rag_status, model)
    if not args.no_manifest:
        _write_json(run_dir / "manifest.json", manifest)
    print(
        f"RUN {args.run_id}: {manifest['generated_route_count']}/"
        f"{manifest['expected_route_count']} routes; complete={manifest['complete']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
