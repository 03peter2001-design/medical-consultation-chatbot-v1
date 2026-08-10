"""Strict schema validation for offline Gemini-generated AMIE route drafts.

These artifacts are deliberately incompatible with the active questionnaire,
Safety, and disease-profile loaders.  They are review inputs, not runtime data.
"""

from __future__ import annotations

import re
from typing import Any

SCHEMA_VERSION = 1
PIPELINE_VERSION = "amie-route-drafts-v8"
EVIDENCE_STATUSES = {"sufficient", "limited", "insufficient"}
DISPOSITIONS = {"questionnaire", "handoff", "urgent"}
CLINICAL_DOMAINS = {None, "chest", "headache", "abdomen"}
FACT_KINDS = {"symptom", "finding", "history", "risk", "context"}
SCALAR_DOMAINS = {
    "onset": {"sudden", "gradual"},
    "course": {"episodic", "continuous", "recurrent"},
    "duration": {"brief", "prolonged"},
    "severity": {"mild", "moderate", "severe"},
    "new_or_changed": {"true", "false"},
}
SAFETY_WHEN_KEYS = {
    "primary_in",
    "severity_in",
    "onset_in",
    "course_in",
    "duration_in",
    "new_or_changed_in",
    "all_findings",
    "any_findings",
}
_CODE = re.compile(r"^[a-z][a-z0-9_]{2,95}$")


def _object(value: Any, path: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{path} 欄位不符合 schema")
    return value


def _text(value: Any, path: str, *, limit: int = 1200) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{path} 必須是 1–{limit} 字的非空字串")
    return value.strip()


def _code(value: Any, path: str) -> str:
    code = _text(value, path, limit=96)
    if not _CODE.fullmatch(code):
        raise ValueError(f"{path} 必須是 snake_case code")
    return code


def _strings(
    value: Any,
    path: str,
    *,
    allow_empty: bool = False,
    limit: int = 60,
) -> list[str]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or len(value) > limit
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        qualifier = "可為空的" if allow_empty else "非空"
        raise ValueError(f"{path} 必須是最多 {limit} 項的{qualifier}字串陣列")
    normalized = [item.strip() for item in value]
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{path} 不可包含重複值")
    return normalized


def _source_ids(value: Any, path: str, source_ids: set[str]) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{path} 必須是 source ID 陣列，不可使用字串或物件")
    if not value:
        raise ValueError(f"{path} 至少必須引用一個 RAG source ID，不可為空")
    if len(value) > 40:
        raise ValueError(f"{path} 最多只能引用 40 個 RAG source ID")
    values = _strings(value, path, limit=40)
    unknown = set(values) - source_ids
    if unknown:
        raise ValueError(f"{path} 引用未知 RAG source：{sorted(unknown)}")
    return values


def _validate_mapping(
    mapping: Any,
    path: str,
    fact_codes: set[str],
) -> dict[str, Any]:
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError(f"{path} 必須是非空語意 mapping")
    allowed = {*SCALAR_DOMAINS, "findings", "negated_findings"}
    unknown = set(mapping) - allowed
    if unknown:
        raise ValueError(f"{path} 含不支援欄位：{sorted(unknown)}")
    for key, domain in SCALAR_DOMAINS.items():
        if key in mapping and mapping[key] not in domain:
            raise ValueError(f"{path}.{key} 值不正確")
    for key in ("findings", "negated_findings"):
        if key not in mapping:
            continue
        values = _strings(mapping[key], f"{path}.{key}", allow_empty=True)
        unknown_codes = set(values) - fact_codes
        if unknown_codes:
            raise ValueError(f"{path}.{key} 引用未知 fact：{sorted(unknown_codes)}")
    if not any(
        key in mapping and (mapping[key] if isinstance(mapping[key], str) else bool(mapping[key]))
        for key in allowed
    ):
        raise ValueError(f"{path} 沒有任何可執行語意")
    return mapping


def validate_discovery(
    discovery: Any,
    *,
    route: str,
    catalog_entry: dict[str, Any],
    source_ids: set[str],
) -> dict[str, Any]:
    """Validate Gemini's first-stage disease-name proposal."""
    discovery = _object(
        discovery,
        "discovery",
        {"route", "evidence_status", "diseases", "review_notes"},
    )
    if discovery["route"] != route:
        raise ValueError("discovery.route 與目標 route 不符")
    if discovery["evidence_status"] not in EVIDENCE_STATUSES:
        raise ValueError("discovery.evidence_status 不正確")
    diseases = discovery["diseases"]
    if not isinstance(diseases, list) or len(diseases) > 10:
        raise ValueError("discovery.diseases 必須是最多 10 項陣列")
    if catalog_entry["disposition"] != "questionnaire" and diseases:
        raise ValueError("urgent/handoff route 不可建立候選疾病表")
    if discovery["evidence_status"] == "insufficient" and diseases:
        raise ValueError("證據不足時不可提出候選疾病")
    ids: set[str] = set()
    names: set[str] = set()
    for index, raw in enumerate(diseases):
        path = f"discovery.diseases[{index}]"
        item = _object(raw, path, {"id", "name", "rationale", "source_ids"})
        disease_id = _code(item["id"], f"{path}.id")
        if not disease_id.startswith(f"{route}__") or disease_id in ids:
            raise ValueError(f"{path}.id namespace 或唯一性不正確")
        ids.add(disease_id)
        name = _text(item["name"], f"{path}.name", limit=200)
        if name.casefold() in names:
            raise ValueError(f"{path}.name 重複")
        names.add(name.casefold())
        _text(item["rationale"], f"{path}.rationale")
        _source_ids(item["source_ids"], f"{path}.source_ids", source_ids)
    notes = discovery["review_notes"]
    if not isinstance(notes, list) or len(notes) > 20:
        raise ValueError("discovery.review_notes 必須是最多 20 項陣列")
    for index, raw in enumerate(notes):
        path = f"discovery.review_notes[{index}]"
        item = _object(raw, path, {"severity", "note", "source_ids"})
        if item["severity"] not in {"critical", "warning", "info"}:
            raise ValueError(f"{path}.severity 不正確")
        _text(item["note"], f"{path}.note")
        _source_ids(item["source_ids"], f"{path}.source_ids", source_ids)
    return discovery


def validate_proposal(
    proposal: Any,
    *,
    route: str,
    questionnaire: dict[str, Any],
    catalog_entry: dict[str, Any],
    existing_fact_codes: set[str],
    source_ids: set[str],
    source_scopes: dict[str, set[str]],
    disease_candidates: list[dict[str, str]],
) -> dict[str, Any]:
    """Validate one raw Gemini response against deterministic route inputs."""
    proposal = _object(
        proposal,
        "proposal",
        {
            "route",
            "evidence_status",
            "route_review",
            "fact_proposals",
            "semantic_options",
            "profile_status",
            "profiles",
            "safety_proposals",
            "unsupported_requirements",
            "review_notes",
        },
    )
    if proposal["route"] != route:
        raise ValueError("proposal.route 與目標 route 不符")
    if proposal["evidence_status"] not in EVIDENCE_STATUSES:
        raise ValueError("proposal.evidence_status 不正確")

    route_review = _object(
        proposal["route_review"],
        "proposal.route_review",
        {
            "recommended_disposition",
            "recommended_clinical_domain",
            "rationale",
            "source_ids",
        },
    )
    if route_review["recommended_disposition"] not in DISPOSITIONS:
        raise ValueError("route_review.recommended_disposition 不正確")
    if route_review["recommended_clinical_domain"] not in CLINICAL_DOMAINS:
        raise ValueError("route_review.recommended_clinical_domain 不正確")
    _text(route_review["rationale"], "route_review.rationale")
    _source_ids(route_review["source_ids"], "route_review.source_ids", source_ids)

    candidate_by_id = {item["id"]: item for item in disease_candidates}
    if len(candidate_by_id) != len(disease_candidates):
        raise ValueError("disease_candidates.id 不可重複")

    fact_proposals = proposal["fact_proposals"]
    if not isinstance(fact_proposals, list) or len(fact_proposals) > 48:
        raise ValueError("fact_proposals 必須是最多 48 項的陣列")
    proposed_codes: set[str] = set()
    proposed_fact_diseases: dict[str, set[str]] = {}
    for index, raw in enumerate(fact_proposals):
        path = f"fact_proposals[{index}]"
        item = _object(
            raw,
            path,
            {
                "code",
                "description",
                "kind",
                "safety_candidate",
                "disease_ids",
                "source_ids",
            },
        )
        code = _code(item["code"], f"{path}.code")
        if code in existing_fact_codes:
            raise ValueError(f"{path}.code 已是 active fact；請直接引用，不要重新定義")
        if not code.startswith(f"{route}__"):
            raise ValueError(f"{path}.code 必須使用 {route}__ namespace")
        if code in proposed_codes:
            raise ValueError(f"重複 fact proposal：{code}")
        proposed_codes.add(code)
        _text(item["description"], f"{path}.description", limit=300)
        if item["kind"] not in FACT_KINDS:
            raise ValueError(f"{path}.kind 不正確")
        if not isinstance(item["safety_candidate"], bool):
            raise ValueError(f"{path}.safety_candidate 必須是布林值")
        disease_ids = _strings(
            item["disease_ids"], f"{path}.disease_ids", allow_empty=True, limit=14
        )
        if set(disease_ids) - set(candidate_by_id):
            raise ValueError(f"{path}.disease_ids 引用未知疾病")
        proposed_fact_diseases[code] = set(disease_ids)
        fact_source_ids = _source_ids(item["source_ids"], f"{path}.source_ids", source_ids)
        for disease_id in disease_ids:
            if not any(disease_id in source_scopes[source_id] for source_id in fact_source_ids):
                raise ValueError(f"{path} 缺少由疾病名稱檢索的 {disease_id} RAG 證據")
    all_fact_codes = existing_fact_codes | proposed_codes

    questions = questionnaire.get("questions", [])
    choice_options = {
        (item["field"], option)
        for item in questions
        if item.get("kind") == "choice"
        for option in item.get("options", [])
    }
    semantics = proposal["semantic_options"]
    if not isinstance(semantics, list) or len(semantics) > len(choice_options):
        raise ValueError("semantic_options 數量超過問卷 choice options")
    semantic_keys: set[tuple[str, str]] = set()
    reachable_facts: set[str] = set()
    for index, raw in enumerate(semantics):
        path = f"semantic_options[{index}]"
        item = _object(
            raw,
            path,
            {"field", "option", "mapping", "disease_ids", "source_ids"},
        )
        key = (
            _text(item["field"], f"{path}.field", limit=100),
            _text(item["option"], f"{path}.option", limit=300),
        )
        if key not in choice_options:
            raise ValueError(f"{path} 不是問卷中的 exact choice option：{key}")
        if key in semantic_keys:
            raise ValueError(f"重複 semantic option：{key}")
        semantic_keys.add(key)
        mapping = _validate_mapping(item["mapping"], f"{path}.mapping", all_fact_codes)
        reachable_facts.update(mapping.get("findings", []))
        reachable_facts.update(mapping.get("negated_findings", []))
        disease_ids = _strings(
            item["disease_ids"], f"{path}.disease_ids", allow_empty=True, limit=14
        )
        if set(disease_ids) - set(candidate_by_id):
            raise ValueError(f"{path}.disease_ids 引用未知疾病")
        mapped_disease_ids = set().union(
            *(
                proposed_fact_diseases.get(code, set())
                for code in (
                    *mapping.get("findings", []),
                    *mapping.get("negated_findings", []),
                )
            )
        )
        if not mapped_disease_ids.issubset(set(disease_ids)):
            raise ValueError(f"{path}.disease_ids 遺漏 mapped fact 的疾病追溯")
        semantic_source_ids = _source_ids(item["source_ids"], f"{path}.source_ids", source_ids)
        for disease_id in disease_ids:
            if not any(disease_id in source_scopes[source_id] for source_id in semantic_source_ids):
                raise ValueError(f"{path} 缺少由疾病名稱檢索的 {disease_id} RAG 證據")

    safety = proposal["safety_proposals"]
    if not isinstance(safety, list) or len(safety) > 20:
        raise ValueError("safety_proposals 必須是最多 20 項的陣列")
    safety_codes: set[str] = set()
    urgent_codes: set[str] = set()
    for index, raw in enumerate(safety):
        path = f"safety_proposals[{index}]"
        item = _object(
            raw,
            path,
            {
                "code",
                "label",
                "level",
                "kind",
                "terms",
                "when",
                "possible_conditions",
                "source_ids",
            },
        )
        code = _code(item["code"], f"{path}.code")
        if not code.startswith(f"experimental_{route}__") or code in safety_codes:
            raise ValueError(f"{path}.code namespace 或唯一性不正確")
        safety_codes.add(code)
        _text(item["label"], f"{path}.label", limit=200)
        if item["level"] not in {"urgent", "routine"}:
            raise ValueError(f"{path}.level 不正確")
        if item["level"] == "urgent":
            urgent_codes.add(code)
        if item["kind"] not in {"raw", "structured"}:
            raise ValueError(f"{path}.kind 不正確")
        terms = _strings(item["terms"], f"{path}.terms", allow_empty=True, limit=30)
        when = item["when"]
        if not isinstance(when, dict) or set(when) - SAFETY_WHEN_KEYS:
            raise ValueError(f"{path}.when 含不支援條件")
        if item["kind"] == "raw" and (not terms or when):
            raise ValueError(f"{path} raw rule 必須有 terms 且 when 為空")
        if item["kind"] == "structured" and (terms or not when):
            raise ValueError(f"{path} structured rule 必須有 when 且 terms 為空")
        for key, values in when.items():
            values = _strings(values, f"{path}.when.{key}", limit=30)
            if key == "primary_in" and set(values) != {route}:
                raise ValueError(f"{path}.when.primary_in 只能是目前 route")
            if key in {"all_findings", "any_findings"}:
                unknown = set(values) - all_fact_codes
                if unknown:
                    raise ValueError(f"{path}.when.{key} 引用未知 fact：{sorted(unknown)}")
            scalar_key = key.removesuffix("_in")
            if scalar_key in SCALAR_DOMAINS and set(values) - SCALAR_DOMAINS[scalar_key]:
                raise ValueError(f"{path}.when.{key} 含無效值")
        _strings(
            item["possible_conditions"],
            f"{path}.possible_conditions",
            allow_empty=item["level"] != "urgent",
            limit=20,
        )
        _source_ids(item["source_ids"], f"{path}.source_ids", source_ids)

    profile_status = proposal["profile_status"]
    profiles = proposal["profiles"]
    if profile_status not in {"proposed", "not_applicable", "insufficient_evidence"}:
        raise ValueError("profile_status 不正確")
    if not isinstance(profiles, list) or len(profiles) > 14:
        raise ValueError("profiles 必須是最多 14 項的陣列")
    current_disposition = catalog_entry["disposition"]
    if current_disposition != "questionnaire":
        if profile_status != "not_applicable" or profiles:
            raise ValueError("urgent/handoff route 不可建立長問卷疾病表")
    elif profile_status == "proposed" and not profiles:
        raise ValueError("profile_status=proposed 時 profiles 不可為空")
    elif profile_status != "proposed" and profiles:
        raise ValueError("非 proposed profile_status 不可包含 profiles")

    profile_ids: set[str] = set()
    for index, raw in enumerate(profiles):
        path = f"profiles[{index}]"
        item = _object(
            raw,
            path,
            {
                "id",
                "name",
                "must_not_miss",
                "retrieval_query",
                "safety_rule_codes",
                "clues",
                "source_ids",
            },
        )
        profile_id = _code(item["id"], f"{path}.id")
        if not profile_id.startswith(f"{route}__") or profile_id in profile_ids:
            raise ValueError(f"{path}.id namespace 或唯一性不正確")
        profile_ids.add(profile_id)
        _text(item["name"], f"{path}.name", limit=200)
        candidate = candidate_by_id.get(profile_id)
        if candidate is None:
            raise ValueError(f"{path}.id 不在疾病名稱 discovery 結果")
        if item["name"] != candidate["name"]:
            raise ValueError(f"{path}.name 必須與 discovery 疾病名稱完全一致")
        if item["retrieval_query"] != candidate["retrieval_query"]:
            raise ValueError(f"{path}.retrieval_query 必須使用疾病名稱導向的固定 query")
        if not isinstance(item["must_not_miss"], bool):
            raise ValueError(f"{path}.must_not_miss 必須是布林值")
        linked_safety = _strings(
            item["safety_rule_codes"],
            f"{path}.safety_rule_codes",
            allow_empty=not item["must_not_miss"],
            limit=20,
        )
        if set(linked_safety) - safety_codes:
            raise ValueError(f"{path}.safety_rule_codes 引用未知規則")
        if item["must_not_miss"] and not set(linked_safety).issubset(urgent_codes):
            raise ValueError(f"{path} must-not-miss 只能連到 urgent Safety")
        if not item["must_not_miss"] and linked_safety:
            raise ValueError(f"{path} 非 must-not-miss 不可連 Safety")
        clues = item["clues"]
        if not isinstance(clues, list) or not clues or len(clues) > 40:
            raise ValueError(f"{path}.clues 必須是 1–40 項陣列")
        clue_keys: set[tuple[str, str, str]] = set()
        for clue_index, raw_clue in enumerate(clues):
            clue_path = f"{path}.clues[{clue_index}]"
            clue = _object(
                raw_clue,
                clue_path,
                {"fact", "status", "direction", "weight", "source_ids"},
            )
            fact = _code(clue["fact"], f"{clue_path}.fact")
            if fact not in all_fact_codes:
                raise ValueError(f"{clue_path}.fact 引用未知 fact")
            if fact not in reachable_facts and fact in proposed_codes:
                raise ValueError(f"{clue_path}.fact 沒有任何 choice option 可產生")
            if fact in proposed_fact_diseases and profile_id not in proposed_fact_diseases[fact]:
                raise ValueError(f"{clue_path}.fact 未宣告屬於此疾病")
            if clue["status"] not in {"present", "absent"}:
                raise ValueError(f"{clue_path}.status 不正確")
            if clue["direction"] not in {"support", "oppose"}:
                raise ValueError(f"{clue_path}.direction 不正確")
            if clue["weight"] not in {1, 2, 3}:
                raise ValueError(f"{clue_path}.weight 必須是 1、2 或 3")
            clue_key = (fact, clue["status"], clue["direction"])
            if clue_key in clue_keys:
                raise ValueError(f"{clue_path} 是重複 clue")
            clue_keys.add(clue_key)
            clue_source_ids = _source_ids(clue["source_ids"], f"{clue_path}.source_ids", source_ids)
            if not any(profile_id in source_scopes[source_id] for source_id in clue_source_ids):
                raise ValueError(f"{clue_path} 缺少此疾病名稱 query 的 RAG 證據")
        if item["must_not_miss"] and not any(clue["status"] == "absent" for clue in clues):
            raise ValueError(f"{path} must-not-miss 缺少 absent rule-out clue")
        profile_source_ids = _source_ids(item["source_ids"], f"{path}.source_ids", source_ids)
        if not any(profile_id in source_scopes[source_id] for source_id in profile_source_ids):
            raise ValueError(f"{path} 缺少此疾病名稱 query 的 RAG 證據")

    if not profile_ids.issubset(set(candidate_by_id)):
        raise ValueError("profiles 含未經 discovery 的疾病名稱")

    unsupported = proposal["unsupported_requirements"]
    if not isinstance(unsupported, list) or len(unsupported) > 30:
        raise ValueError("unsupported_requirements 必須是最多 30 項陣列")
    for index, raw in enumerate(unsupported):
        item = _object(raw, f"unsupported_requirements[{index}]", {"requirement", "reason"})
        _text(item["requirement"], f"unsupported_requirements[{index}].requirement")
        _text(item["reason"], f"unsupported_requirements[{index}].reason")

    notes = proposal["review_notes"]
    if not isinstance(notes, list) or len(notes) > 30:
        raise ValueError("review_notes 必須是最多 30 項陣列")
    for index, raw in enumerate(notes):
        path = f"review_notes[{index}]"
        item = _object(raw, path, {"severity", "note", "source_ids"})
        if item["severity"] not in {"critical", "warning", "info"}:
            raise ValueError(f"{path}.severity 不正確")
        _text(item["note"], f"{path}.note")
        _source_ids(item["source_ids"], f"{path}.source_ids", source_ids)

    if proposal["evidence_status"] == "insufficient" and (
        fact_proposals or semantics or safety or profiles
    ):
        raise ValueError("evidence_status=insufficient 時不可產生臨床提案")
    return proposal


def validate_bundle(bundle: Any) -> dict[str, Any]:
    """Validate the non-executable wrapper without consulting active loaders."""
    bundle = _object(
        bundle,
        "bundle",
        {
            "schema_version",
            "artifact_kind",
            "route",
            "label",
            "lifecycle",
            "inputs",
            "generation",
            "sources",
            "disease_candidates",
            "proposal",
        },
    )
    if bundle["schema_version"] != SCHEMA_VERSION:
        raise ValueError("bundle.schema_version 不正確")
    if bundle["artifact_kind"] != "amie_route_draft":
        raise ValueError("bundle.artifact_kind 不正確")
    route = _code(bundle["route"], "bundle.route")
    _text(bundle["label"], "bundle.label", limit=200)
    lifecycle = _object(bundle["lifecycle"], "bundle.lifecycle", {"status", "executable"})
    if lifecycle != {"status": "model_generated_provisional", "executable": False}:
        raise ValueError("bundle.lifecycle 必須保持不可執行 provisional")
    inputs = _object(
        bundle["inputs"],
        "bundle.inputs",
        {
            "questionnaire_sha256",
            "route_catalog_sha256",
            "base_safety_sha256",
            "rag_index_version",
            "rag_collections",
            "rag_query",
            "rag_corpus_hash",
        },
    )
    for key in (
        "questionnaire_sha256",
        "route_catalog_sha256",
        "base_safety_sha256",
        "rag_corpus_hash",
    ):
        value = _text(inputs[key], f"bundle.inputs.{key}", limit=64)
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError(f"bundle.inputs.{key} 必須是 SHA-256")
    _text(inputs["rag_index_version"], "bundle.inputs.rag_index_version", limit=50)
    _strings(inputs["rag_collections"], "bundle.inputs.rag_collections", limit=20)
    _text(inputs["rag_query"], "bundle.inputs.rag_query", limit=2000)
    generation = _object(
        bundle["generation"],
        "bundle.generation",
        {
            "pipeline_version",
            "provider",
            "model",
            "temperature",
            "max_output_tokens",
            "prompt_sha256",
            "generated_at",
        },
    )
    if generation["pipeline_version"] != PIPELINE_VERSION or generation["provider"] != "gemini":
        raise ValueError("bundle generation pipeline/provider 不正確")
    _text(generation["model"], "bundle.generation.model", limit=100)
    if generation["temperature"] != 0 or not isinstance(generation["max_output_tokens"], int):
        raise ValueError("bundle generation temperature/token 不正確")
    if not re.fullmatch(r"[0-9a-f]{64}", str(generation["prompt_sha256"])):
        raise ValueError("bundle.generation.prompt_sha256 必須是 SHA-256")
    _text(generation["generated_at"], "bundle.generation.generated_at", limit=80)
    sources = bundle["sources"]
    if not isinstance(sources, list) or not sources or len(sources) > 40:
        raise ValueError("bundle.sources 必須是 1–40 項陣列")
    source_ids: set[str] = set()
    for index, raw in enumerate(sources):
        path = f"bundle.sources[{index}]"
        item = _object(
            raw,
            path,
            {
                "id",
                "chunk_id",
                "title",
                "source",
                "url",
                "routes",
                "retrieval_scopes",
                "retrieval_queries",
                "distance",
                "excerpt",
                "text_sha256",
            },
        )
        source_id = _text(item["id"], f"{path}.id", limit=80)
        if source_id in source_ids:
            raise ValueError(f"重複 source id：{source_id}")
        source_ids.add(source_id)
        _text(item["chunk_id"], f"{path}.chunk_id", limit=300)
        _text(item["title"], f"{path}.title", limit=500)
        _text(item["source"], f"{path}.source", limit=200)
        if not isinstance(item["url"], str) or len(item["url"]) > 1000:
            raise ValueError(f"{path}.url 不正確")
        _strings(item["routes"], f"{path}.routes", allow_empty=True, limit=10)
        _strings(item["retrieval_scopes"], f"{path}.retrieval_scopes", limit=20)
        _strings(item["retrieval_queries"], f"{path}.retrieval_queries", limit=20)
        if not isinstance(item["distance"], (int, float)):
            raise ValueError(f"{path}.distance 必須是數字")
        _text(item["excerpt"], f"{path}.excerpt", limit=1800)
        if not re.fullmatch(r"[0-9a-f]{64}", str(item["text_sha256"])):
            raise ValueError(f"{path}.text_sha256 必須是 SHA-256")
    sources_by_id = {item["id"]: item for item in sources}
    candidates = bundle["disease_candidates"]
    if not isinstance(candidates, list) or len(candidates) > 14:
        raise ValueError("bundle.disease_candidates 必須是最多 14 項陣列")
    candidate_ids: set[str] = set()
    for index, raw in enumerate(candidates):
        path = f"bundle.disease_candidates[{index}]"
        item = _object(
            raw,
            path,
            {
                "id",
                "name",
                "retrieval_query",
                "discovery_source_ids",
                "disease_rag_source_ids",
            },
        )
        candidate_id = _code(item["id"], f"{path}.id")
        if not candidate_id.startswith(f"{route}__") or candidate_id in candidate_ids:
            raise ValueError(f"{path}.id namespace 或唯一性不正確")
        candidate_ids.add(candidate_id)
        _text(item["name"], f"{path}.name", limit=200)
        query = _text(item["retrieval_query"], f"{path}.retrieval_query", limit=500)
        if item["name"].casefold() not in query.casefold():
            raise ValueError(f"{path}.retrieval_query 必須包含疾病名稱")
        _source_ids(
            item["discovery_source_ids"],
            f"{path}.discovery_source_ids",
            source_ids,
        )
        disease_source_ids = _source_ids(
            item["disease_rag_source_ids"],
            f"{path}.disease_rag_source_ids",
            source_ids,
        )
        if not any(
            candidate_id in sources_by_id[source_id]["retrieval_scopes"]
            for source_id in disease_source_ids
        ):
            raise ValueError(f"{path} 缺少疾病名稱 query 的 RAG source")
    if bundle["proposal"].get("route") != route:
        raise ValueError("bundle proposal route 不一致")
    return bundle
