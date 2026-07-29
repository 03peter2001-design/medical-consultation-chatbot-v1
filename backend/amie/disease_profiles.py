"""Versioned disease-profile validation and deterministic vote scoring."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

from .clinical_facts import FACT_CODES, merge_facts
from .rule_config import (
    clinical_fact_rules,
    disease_profile_rules,
    load_safety_rules,
)

PROFILE_DATA_DIR = Path(__file__).resolve().parent / "disease_data"
PROFILE_PATH = PROFILE_DATA_DIR / "chest.json"
SCHEMA_VERSION = 1
METHOD = "unit_vote_v1"


def _nonempty(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} 必須是非空字串")
    return value.strip()


def validate_profile_document(document: Any) -> dict[str, Any]:
    """Reject unsafe or non-reproducible disease-table artifacts."""
    if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("疾病表 schema_version 必須是 1")
    if set(document) != {
        "schema_version",
        "profile_version",
        "route",
        "generation",
        "sources",
        "profiles",
    }:
        raise ValueError("疾病表頂層欄位不符合 schema")
    profile_version = _nonempty(
        document.get("profile_version"),
        "profile_version",
    )
    route = _nonempty(document.get("route"), "route")
    if not re.fullmatch(rf"{re.escape(route)}-[a-z0-9.-]+", profile_version):
        raise ValueError("profile_version 格式不正確")
    try:
        route_profile_rules = disease_profile_rules(route)
    except ValueError as exc:
        raise ValueError("疾病表 route 沒有對應 JSON 規則") from exc
    generation = document.get("generation")
    if not isinstance(generation, dict):
        raise ValueError("generation 必須是物件")
    if set(generation) != {"method", "model", "corpus_hash", "generated_at"}:
        raise ValueError("generation 欄位不符合 schema")
    for key in ("method", "model", "corpus_hash", "generated_at"):
        _nonempty(generation.get(key), f"generation.{key}")
    if not re.fullmatch(r"[0-9a-f]{64}", generation["corpus_hash"]):
        raise ValueError("generation.corpus_hash 必須是 SHA-256")

    sources = document.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("sources 必須是非空陣列")
    source_ids: set[str] = set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError(f"sources[{index}] 必須是物件")
        if set(source) != {"id", "title", "source", "url"}:
            raise ValueError(f"sources[{index}] 欄位不符合 schema")
        source_id = _nonempty(source.get("id"), f"sources[{index}].id")
        if source_id in source_ids:
            raise ValueError(f"重複來源 id：{source_id}")
        source_ids.add(source_id)
        _nonempty(source.get("title"), f"sources[{index}].title")
        _nonempty(source.get("source"), f"sources[{index}].source")

    profiles = document.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("profiles 必須是非空陣列")
    profile_ids: set[str] = set()
    profile_names: set[str] = set()
    for index, profile in enumerate(profiles):
        path = f"profiles[{index}]"
        if not isinstance(profile, dict):
            raise ValueError(f"{path} 必須是物件")
        if set(profile) != {
            "id",
            "name",
            "coding",
            "must_not_miss",
            "review_status",
            "reviewer",
            "reviewed_at",
            "clues",
        }:
            raise ValueError(f"{path} 欄位不符合 schema")
        profile_id = _nonempty(profile.get("id"), f"{path}.id")
        if profile_id in profile_ids:
            raise ValueError(f"重複疾病 id：{profile_id}")
        profile_ids.add(profile_id)
        profile_name = _nonempty(profile.get("name"), f"{path}.name")
        if profile_name in profile_names:
            raise ValueError(f"重複疾病名稱：{profile_name}")
        profile_names.add(profile_name)
        if not isinstance(profile.get("must_not_miss"), bool):
            raise ValueError(f"{path}.must_not_miss 必須是布林值")
        if profile.get("review_status") not in {"provisional", "reviewed"}:
            raise ValueError(f"{path}.review_status 不正確")
        if profile["review_status"] == "reviewed":
            _nonempty(profile.get("reviewer"), f"{path}.reviewer")
            _nonempty(profile.get("reviewed_at"), f"{path}.reviewed_at")
        coding = profile.get("coding")
        if coding is not None:
            if (
                not isinstance(coding, dict)
                or set(coding) != {"system", "code", "display", "verified"}
                or coding.get("system") != "http://snomed.info/sct"
                or not str(coding.get("code", "")).isdigit()
                or not coding.get("verified")
                or not str(coding.get("display", "")).strip()
            ):
                raise ValueError(f"{path}.coding 未驗證")

        clues = profile.get("clues")
        if not isinstance(clues, list) or not clues:
            raise ValueError(f"{path}.clues 必須是非空陣列")
        clue_keys: set[tuple[str, str, str]] = set()
        for clue_index, clue in enumerate(clues):
            clue_path = f"{path}.clues[{clue_index}]"
            if (
                not isinstance(clue, dict)
                or set(clue) != {"fact", "status", "direction", "weight", "source_ids"}
                or clue.get("fact") not in FACT_CODES
            ):
                raise ValueError(f"{clue_path}.fact 不在白名單")
            if clue.get("status") not in {"present", "absent"}:
                raise ValueError(f"{clue_path}.status 不正確")
            if clue.get("direction") not in {"support", "oppose"}:
                raise ValueError(f"{clue_path}.direction 不正確")
            clue_key = (
                clue["fact"],
                clue["status"],
                clue["direction"],
            )
            if clue_key in clue_keys:
                raise ValueError(f"{clue_path} 是重複線索")
            clue_keys.add(clue_key)
            weight = clue.get("weight")
            if not isinstance(weight, int) or isinstance(weight, bool) or weight < 1:
                raise ValueError(f"{clue_path}.weight 必須是正整數")
            references = clue.get("source_ids")
            if (
                not isinstance(references, list)
                or not references
                or any(reference not in source_ids for reference in references)
            ):
                raise ValueError(f"{clue_path}.source_ids 含未知來源")
    mandatory_profiles = set(route_profile_rules["required_must_not_miss_profiles"])
    missing_mandatory = mandatory_profiles - profile_ids
    if missing_mandatory:
        raise ValueError(f"疾病表缺少 Safety 必要疾病：{sorted(missing_mandatory)}")
    for profile in profiles:
        if profile["id"] in mandatory_profiles and not profile["must_not_miss"]:
            raise ValueError(f"{profile['id']} 必須標記 must_not_miss")
    return document


def read_profile_document(path: Path = PROFILE_PATH) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"疾病表 JSON 格式錯誤：{error.lineno}:{error.colno}") from error
    return validate_profile_document(document)


@lru_cache(maxsize=None)
def load_profile_document(route: str = "chest") -> dict[str, Any]:
    return read_profile_document(PROFILE_DATA_DIR / f"{route}.json")


def score_diseases(
    facts: list[dict[str, Any]] | None,
    *,
    route: str = "chest",
    computed_from: str = "live",
    document: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply signed profile votes without calling an LLM or retriever."""
    deployed = document or load_profile_document(route)
    fact_map = {fact["code"]: fact for fact in merge_facts([], facts)}
    ranked: list[dict[str, Any]] = []
    for profile in deployed["profiles"]:
        support_votes = 0
        oppose_votes = 0
        evaluated_weight = 0
        total_weight = sum(clue["weight"] for clue in profile["clues"])
        supporting: list[dict[str, Any]] = []
        opposing: list[dict[str, Any]] = []
        missing: list[str] = []
        for clue in profile["clues"]:
            fact = fact_map.get(clue["fact"])
            if fact is None:
                missing.append(clue["fact"])
                continue
            evaluated_weight += clue["weight"]
            if fact["status"] != clue["status"]:
                continue
            evidence = {
                "fact": clue["fact"],
                "evidence": fact["evidence"],
                "vote": clue["weight"],
            }
            if clue["direction"] == "support":
                support_votes += clue["weight"]
                supporting.append(evidence)
            else:
                oppose_votes += clue["weight"]
                opposing.append(evidence)
        coverage = round(evaluated_weight / total_weight, 4) if total_weight else 0.0
        ranked.append(
            {
                "id": profile["id"],
                "name": profile["name"],
                "coding": profile.get("coding"),
                "must_not_miss": bool(profile.get("must_not_miss")),
                "review_status": profile["review_status"],
                "net_votes": support_votes - oppose_votes,
                "support_votes": support_votes,
                "oppose_votes": oppose_votes,
                "coverage": coverage,
                "supporting": supporting,
                "opposing": opposing,
                "missing_facts": sorted(set(missing)),
            }
        )
    ranked.sort(
        key=lambda item: (
            -item["net_votes"],
            -item["support_votes"],
            -item["coverage"],
            item["id"],
        )
    )
    positive = [item for item in ranked if item["support_votes"] > 0]
    status = "ready" if positive else "insufficient"
    return {
        "schema_version": SCHEMA_VERSION,
        "profile_version": deployed["profile_version"],
        "method": METHOD,
        "status": status,
        "computed_from": computed_from,
        "provisional": any(item["review_status"] == "provisional" for item in ranked),
        "top": ranked[:5] if positive else [],
        "ranked": ranked,
        "must_not_miss": [item for item in ranked if item["must_not_miss"]],
    }


def attach_safety_conditions(
    route: str,
    red_flags: list[dict[str, Any]] | None,
    *,
    facts: list[dict[str, Any]] | None = None,
    computed_from: str = "live",
    assessment: dict[str, Any] | None = None,
    document: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add JSON-defined Safety directions without inventing votes or diagnoses."""
    flags = [flag for flag in red_flags or [] if isinstance(flag, dict)]
    deployed = document
    if deployed is None:
        try:
            candidate = load_profile_document(route)
            if candidate.get("route") == route:
                deployed = candidate
        except Exception:
            deployed = None

    if assessment is not None:
        result = deepcopy(assessment)
    elif deployed is not None:
        try:
            result = score_diseases(
                facts,
                route=route,
                computed_from=computed_from,
                document=deployed,
            )
        except Exception:
            result = {}
    else:
        result = {}

    if not result:
        result = {
            "schema_version": SCHEMA_VERSION,
            "profile_version": "",
            "method": "safety_rule_v1",
            "computed_from": computed_from,
            "provisional": False,
            "top": [],
            "ranked": [],
            "must_not_miss": [],
        }

    condition_candidates = load_safety_rules()["urgent_condition_candidates"]
    profile_ids: dict[str, str] = {}
    try:
        for profile_id, names in disease_profile_rules(route)[
            "required_must_not_miss_profiles"
        ].items():
            for name in names:
                profile_ids[name] = profile_id
    except ValueError:
        pass
    profile_by_id = {profile["id"]: profile for profile in (deployed or {}).get("profiles", [])}

    conditions: dict[str, dict[str, Any]] = {}
    for flag in flags:
        label = str(flag.get("label") or "").strip()
        names = list(condition_candidates.get(label, []))
        trigger = {
            "rule_code": str(flag.get("code") or "").strip(),
            "rule_label": label,
            "evidence": str(flag.get("evidence") or "").strip(),
        }
        for raw_name in names:
            name = str(raw_name).strip()
            if not name:
                continue
            profile_id = profile_ids.get(name)
            entry = conditions.setdefault(
                name,
                {
                    "name": name,
                    "profile_id": profile_id,
                    "coding": (
                        deepcopy(profile_by_id.get(profile_id, {}).get("coding"))
                        if profile_id
                        else None
                    ),
                    "source": "safety_rule",
                    "triggered_by": [],
                },
            )
            if trigger not in entry["triggered_by"]:
                entry["triggered_by"].append(trigger)

    result["status"] = "safety_triggered"
    result["safety_triggered_conditions"] = list(conditions.values())
    return result


def question_fact_codes(question: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    scalar_mappings = clinical_fact_rules()["scalar_mappings"]
    for mapping in question.get("semantic_options", {}).values():
        result.update(code for code in mapping.get("findings", []) if code in FACT_CODES)
        result.update(code for code in mapping.get("negated_findings", []) if code in FACT_CODES)
        for field, values in scalar_mappings.items():
            code = values.get(mapping.get(field))
            if code:
                result.add(code)
    return result


def question_utility(
    question: dict[str, Any],
    assessment: dict[str, Any],
    *,
    route: str = "chest",
    document: dict[str, Any] | None = None,
) -> int:
    """Count pairwise vote disagreements a question can resolve."""
    deployed = document or load_profile_document(route)
    question_codes = question_fact_codes(question)
    if not question_codes:
        return 0
    active_ids = {item["id"] for item in assessment.get("ranked", [])[:5] if item.get("id")}
    profiles = [
        profile for profile in deployed["profiles"] if not active_ids or profile["id"] in active_ids
    ]
    utility = 0
    for code in question_codes:
        directions = []
        for profile in profiles:
            vote = 0
            for clue in profile["clues"]:
                if clue["fact"] == code:
                    vote = clue["weight"] * (1 if clue["direction"] == "support" else -1)
                    break
            directions.append(vote)
        utility += sum(
            1
            for index, left in enumerate(directions)
            for right in directions[index + 1 :]
            if left != right
        )
    return utility
