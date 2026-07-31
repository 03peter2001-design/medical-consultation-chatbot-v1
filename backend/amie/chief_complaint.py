"""Evidence-grounded semantic extraction for a free-text chief complaint."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any, cast

from domain.questionnaires import DISEASE_ROUTES, load_questionnaire_category

from .models import (
    ChiefComplaintAssessment,
    ChiefFinding,
    EvidenceValue,
    QuestionnaireAnswerEvidence,
    RouteEvidence,
    SymptomAssessment,
    SymptomEvidence,
)
from .rule_config import finding_codes, load_safety_rules, supported_routes

_DIRECT_IDENTIFIER = re.compile(
    r"\b(?:[A-Z][12]\d{8}|\d{8,12})\b",
    flags=re.IGNORECASE,
)
_NORMALIZE_EVIDENCE = re.compile(r"[\s，,。.!！?？；;：:'\"「」『』、]+")
_ONSET_TIME_PHRASE = re.compile(
    r"(?:"
    r"剛剛|方才|"
    r"(?:約|大約)?"
    r"(?:\d+(?:\.\d+)?|[零〇一二兩三四五六七八九十百半]+)"
    r"(?:分鐘|小時|天|週|星期|個月|年)(?:前|之前)"
    r")"
)
_ONGOING_DURATION_PHRASE = re.compile(
    r"(?:已經)?持續(?:了)?"
    r"(?P<value>(?:\d+(?:\.\d+)?|[零〇一二兩三四五六七八九十百半]+)"
    r"(?:分鐘|小時|天|週|星期|個月|年))"
    r"(?:了)?"
)

# Only these symptom concepts are allowed to start one of the deployed
# pain questionnaires. Associated findings such as dizziness, visual change,
# or vomiting remain available to safety rules, but are not evidence that the
# patient reported headache, chest pain, or abdominal pain.
_QUESTIONNAIRE_ROUTING_SYMPTOMS = frozenset(
    {
        "headache",
        "chest_pain",
        "chest_tightness",
        "abdominal_pain",
    }
)


@lru_cache(maxsize=1)
def _questionnaire_answer_definitions() -> dict[str, dict[str, dict[str, Any]]]:
    """Return deployed information needs keyed by questionnaire route and field."""
    return {
        route: {
            item["field"]: item
            for item in load_questionnaire_category(route)
            if item["kind"] in {"choice", "duration"}
        }
        for route in DISEASE_ROUTES
    }


def _questionnaire_answer_catalog(
    routes: list[str] | tuple[str, ...] = DISEASE_ROUTES,
) -> list[dict[str, Any]]:
    return [
        {
            "route": route,
            "field": field,
            "question": question["prompt"],
            "kind": question["kind"],
            "multiple": bool(question["multiple"]),
            **({"options": question["options"]} if question["kind"] == "choice" else {}),
        }
        for route, questions in _questionnaire_answer_definitions().items()
        if route in routes
        for field, question in questions.items()
    ]


def _trim(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _normalized(value: str) -> str:
    return _NORMALIZE_EVIDENCE.sub("", value).lower()


def _evidence_occurrences(text: str, evidence: str) -> list[int]:
    normalized_text = _normalized(text)
    normalized_evidence = _normalized(evidence)
    if not normalized_evidence:
        return []
    starts = []
    offset = 0
    while True:
        index = normalized_text.find(normalized_evidence, offset)
        if index < 0:
            break
        starts.append(index)
        offset = index + max(len(normalized_evidence), 1)
    return starts


def _has_grounded_evidence(
    text: str,
    evidence: str,
    *,
    expected_absent: bool = False,
) -> bool:
    rules = load_safety_rules()
    negation_terms = rules["negation"]["terms"]
    lookback = rules["negation"]["lookback_chars"]
    normalized_text = _normalized(text)
    normalized_evidence = _normalized(evidence)
    for index in _evidence_occurrences(text, evidence):
        prefix = normalized_text[max(0, index - lookback) : index]
        negated = any(term in prefix for term in negation_terms)
        if negated == expected_absent:
            return True
    # An absent finding may quote the whole negated phrase, in which case
    # the configured negation term is inside the evidence itself.
    return bool(
        expected_absent
        and normalized_evidence
        and normalized_evidence in normalized_text
        and any(term in normalized_evidence for term in negation_terms)
    )


def _validated_evidence_value(
    text: str,
    item: EvidenceValue,
    allowed_values: set[str],
) -> EvidenceValue:
    value = _trim(item.value, 40).lower()
    evidence = _trim(item.evidence, 160)
    if (
        value not in allowed_values
        or value == "unknown"
        or not _has_grounded_evidence(text, evidence)
    ):
        return EvidenceValue(value="unknown", evidence="")
    return EvidenceValue(value=value, evidence=evidence)


def _validated_onset_time(
    text: str,
    item: EvidenceValue,
) -> EvidenceValue:
    """Keep a verbatim elapsed onset time, never an inferred clock value."""
    evidence = _trim(item.evidence, 160)
    if not _has_grounded_evidence(text, evidence):
        return EvidenceValue()
    match = _ONSET_TIME_PHRASE.search(evidence)
    if match:
        return EvidenceValue(value=match.group(0), evidence=evidence)
    duration_match = _ONGOING_DURATION_PHRASE.search(evidence)
    if duration_match:
        return EvidenceValue(
            value=duration_match.group("value"),
            evidence=evidence,
        )
    return EvidenceValue()


def _deterministic_onset_time(text: str) -> EvidenceValue:
    """Recover only elapsed times explicitly linked to symptom onset."""
    for match in _ONSET_TIME_PHRASE.finditer(text):
        following = text[match.end() : match.end() + 8]
        if re.match(r"(?:就|才|便)?(?:開始|出現|發作)", following):
            value = match.group(0)
            return EvidenceValue(value=value, evidence=value)
    duration_match = _ONGOING_DURATION_PHRASE.search(text)
    if duration_match:
        return EvidenceValue(
            value=duration_match.group("value"),
            evidence=duration_match.group(0),
        )
    return EvidenceValue()


def _validated_findings(
    text: str,
    findings: list[ChiefFinding],
    *,
    force_absent: bool = False,
) -> list[ChiefFinding]:
    validated: list[ChiefFinding] = []
    seen: set[tuple[str, str]] = set()
    allowed_findings = finding_codes()
    for finding in findings[:24]:
        status = "absent" if force_absent else finding.status
        if finding.code not in allowed_findings or status not in {"present", "absent"}:
            continue
        evidence = _trim(finding.evidence, 160)
        if not _has_grounded_evidence(
            text,
            evidence,
            expected_absent=status == "absent",
        ):
            continue
        key = (finding.code, status)
        if key in seen:
            continue
        seen.add(key)
        validated.append(
            ChiefFinding(
                code=finding.code,
                status=status,
                evidence=evidence,
            )
        )
    return validated


def _validated_routes(
    text: str,
    routes: list[str | RouteEvidence],
    allowed_routes: set[str],
    route_evidence: dict[str, list[str]],
    route_keywords: dict[str, list[str]],
) -> list[str]:
    def evidence_supports_route(route: str, evidence: str) -> bool:
        normalized_evidence = _normalized(evidence)
        if not normalized_evidence:
            return False
        if any(
            _normalized(keyword) in normalized_evidence for keyword in route_keywords.get(route, [])
        ):
            return True
        return any(
            (
                _normalized(symptom_evidence) in normalized_evidence
                or normalized_evidence in _normalized(symptom_evidence)
            )
            for symptom_evidence in route_evidence.get(route, [])
            if _normalized(symptom_evidence)
        )

    validated: list[str] = []
    for item in routes[:12]:
        if isinstance(item, RouteEvidence):
            route = _trim(item.route, 40).lower()
            evidence = _trim(item.evidence, 160)
            if not _has_grounded_evidence(text, evidence) or not evidence_supports_route(
                route,
                evidence,
            ):
                continue
        else:
            route = _trim(item, 40).lower()
            if not route_evidence.get(route):
                continue
        if route not in allowed_routes and route != "other":
            continue
        if route not in validated:
            validated.append(route)
    return validated


def _validated_symptoms(
    text: str,
    symptoms: list[SymptomEvidence],
    definitions: dict[str, dict[str, str]],
) -> list[SymptomEvidence]:
    validated: list[SymptomEvidence] = []
    seen: set[str] = set()
    for symptom in symptoms[:12]:
        code = _trim(symptom.code, 80).lower()
        evidence = _trim(symptom.evidence, 160)
        if code not in definitions or code in seen or not _has_grounded_evidence(text, evidence):
            continue
        seen.add(code)
        validated.append(SymptomEvidence(code=code, evidence=evidence))
    return validated


def _validated_questionnaire_answers(
    text: str,
    answers: list[QuestionnaireAnswerEvidence],
) -> list[QuestionnaireAnswerEvidence]:
    definitions = _questionnaire_answer_definitions()
    validated: list[QuestionnaireAnswerEvidence] = []
    seen: set[tuple[str, str]] = set()
    for answer in answers[:24]:
        route = _trim(answer.route, 40).lower()
        field = _trim(answer.field, 80)
        value = _trim(answer.value, 300)
        evidence = _trim(answer.evidence, 160)
        question = definitions.get(route, {}).get(field)
        key = (route, field)
        if not question or key in seen or not _has_grounded_evidence(text, evidence):
            continue
        if question["kind"] == "choice":
            selected = value.split("、")
            if (
                not selected
                or any(item not in question["options"] for item in selected)
                or (not question["multiple"] and len(selected) != 1)
            ):
                continue
        else:
            # Duration answers remain verbatim; the normal input validator
            # checks them again if the patient later edits the value.
            value = evidence
        seen.add(key)
        validated.append(
            QuestionnaireAnswerEvidence(
                route=route,
                field=field,
                value=value,
                evidence=evidence,
            )
        )
    return validated


def _literal_questionnaire_answers(text: str) -> list[QuestionnaireAnswerEvidence]:
    """Recover unambiguous option phrases even when the model omits them."""
    recovered: list[QuestionnaireAnswerEvidence] = []
    for route, questions in _questionnaire_answer_definitions().items():
        for field, question in questions.items():
            if question["kind"] != "choice":
                continue
            if question["multiple"]:
                matched_options = [
                    option
                    for option in question["options"]
                    if (len(_normalized(option)) >= 2 and _has_grounded_evidence(text, option))
                ]
                if matched_options:
                    recovered.append(
                        QuestionnaireAnswerEvidence(
                            route=route,
                            field=field,
                            value="、".join(matched_options),
                            evidence=(
                                matched_options[0] if len(matched_options) == 1 else text[:160]
                            ),
                        )
                    )
                continue
            matches: list[tuple[str, str]] = []
            for option in question["options"]:
                fragments = re.split(r"[，,、/／]|或", option)
                evidence = next(
                    (
                        fragment
                        for fragment in fragments
                        if len(_normalized(fragment)) >= 5
                        and _has_grounded_evidence(text, fragment)
                    ),
                    "",
                )
                if evidence:
                    matches.append((option, evidence))
            if len(matches) != 1:
                continue
            value, evidence = matches[0]
            recovered.append(
                QuestionnaireAnswerEvidence(
                    route=route,
                    field=field,
                    value=value,
                    evidence=evidence,
                )
            )
    return recovered


def validate_assessment(
    text: str,
    assessment: ChiefComplaintAssessment,
) -> ChiefComplaintAssessment:
    """Discard every model claim that is not grounded in the raw text."""
    rules = load_safety_rules()
    allowed_routes = supported_routes()
    symptom_definitions = rules["semantic_extraction"]["symptom_definitions"]
    route_keywords = rules["route_keywords"]
    symptoms = _validated_symptoms(
        text,
        assessment.symptoms,
        symptom_definitions,
    )
    questionnaire_answers = _validated_questionnaire_answers(
        text,
        assessment.questionnaire_answers,
    )
    answered_fields = {(answer.route, answer.field) for answer in questionnaire_answers}
    questionnaire_answers.extend(
        answer
        for answer in _literal_questionnaire_answers(text)
        if (answer.route, answer.field) not in answered_fields
    )
    route_evidence: dict[str, list[str]] = {}
    for symptom in symptoms:
        if symptom.code not in _QUESTIONNAIRE_ROUTING_SYMPTOMS:
            continue
        route = symptom_definitions[symptom.code]["route"]
        route_evidence.setdefault(route, []).append(symptom.evidence)

    primary_symptom_code = _trim(assessment.primary_symptom_code, 80).lower()
    primary_concept = next(
        (item for item in symptoms if item.code == primary_symptom_code),
        None,
    )
    if primary_concept is None:
        primary_symptom_code = "unknown"
    primary_evidence = _trim(assessment.primary_evidence, 160)
    primary_symptom = assessment.primary_symptom
    if primary_concept and primary_concept.code in _QUESTIONNAIRE_ROUTING_SYMPTOMS:
        primary_symptom = symptom_definitions[primary_concept.code]["route"]
        primary_evidence = primary_concept.evidence
    validated_primary_routes = _validated_routes(
        text,
        [RouteEvidence(route=primary_symptom, evidence=primary_evidence)],
        allowed_routes,
        route_evidence,
        route_keywords,
    )
    if not validated_primary_routes:
        primary_symptom = "unknown"
        primary_evidence = ""
    else:
        primary_symptom = validated_primary_routes[0]

    onset_time = _validated_onset_time(text, assessment.onset_time)
    if onset_time.value == "unknown":
        onset_time = _deterministic_onset_time(text)
    onset = _validated_evidence_value(
        text,
        assessment.onset,
        {"sudden", "gradual", "unknown"},
    )
    course = _validated_evidence_value(
        text,
        assessment.course,
        {"episodic", "continuous", "recurrent", "unknown"},
    )
    duration = _validated_evidence_value(
        text,
        assessment.duration,
        {"brief", "prolonged", "unknown"},
    )
    severity = _validated_evidence_value(
        text,
        assessment.severity,
        {"mild", "moderate", "severe", "unknown"},
    )
    is_new_or_changed = _validated_evidence_value(
        text,
        assessment.is_new_or_changed,
        {"true", "false", "unknown"},
    )
    findings = _validated_findings(text, assessment.findings)
    negated = _validated_findings(
        text,
        assessment.negated_findings,
        force_absent=True,
    )

    supported_domains = _validated_routes(
        text,
        assessment.symptom_domains,
        allowed_routes,
        route_evidence,
        route_keywords,
    )
    route_candidates = _validated_routes(
        text,
        assessment.route_candidates,
        allowed_routes,
        route_evidence,
        route_keywords,
    )
    symptom_routes = [
        symptom_definitions[item.code]["route"]
        for item in symptoms
        if item.code in _QUESTIONNAIRE_ROUTING_SYMPTOMS
    ]
    supported_domains = list(dict.fromkeys([*supported_domains, *symptom_routes]))
    route_candidates = list(dict.fromkeys([*route_candidates, *symptom_routes]))
    if primary_symptom != "unknown" and primary_symptom not in route_candidates:
        route_candidates.insert(0, primary_symptom)

    symptom_assessments: list[SymptomAssessment] = []
    seen_symptom_keys: set[tuple[str, str]] = set()
    for symptom in assessment.symptom_assessments[:4]:
        symptom_code = _trim(symptom.symptom_code, 80).lower()
        definition = symptom_definitions.get(symptom_code)
        route = definition["route"] if definition else _trim(symptom.route, 40).lower()
        evidence = _trim(symptom.evidence, 160)
        key = (route, symptom_code)
        validated_profile_routes = _validated_routes(
            text,
            [RouteEvidence(route=route, evidence=evidence)],
            allowed_routes,
            route_evidence,
            route_keywords,
        )
        if (
            not validated_profile_routes
            or key in seen_symptom_keys
            or not _has_grounded_evidence(text, evidence)
            or (definition is not None and symptom_code not in _QUESTIONNAIRE_ROUTING_SYMPTOMS)
        ):
            continue
        if symptom_code != "unknown" and definition is None:
            continue
        seen_symptom_keys.add(key)
        symptom_assessments.append(
            SymptomAssessment(
                route=route,
                evidence=evidence,
                symptom_code=symptom_code,
                onset_time=_validated_onset_time(
                    text,
                    symptom.onset_time,
                ),
                onset=_validated_evidence_value(
                    text,
                    symptom.onset,
                    {"sudden", "gradual", "unknown"},
                ),
                course=_validated_evidence_value(
                    text,
                    symptom.course,
                    {"episodic", "continuous", "recurrent", "unknown"},
                ),
                duration=_validated_evidence_value(
                    text,
                    symptom.duration,
                    {"brief", "prolonged", "unknown"},
                ),
                severity=_validated_evidence_value(
                    text,
                    symptom.severity,
                    {"mild", "moderate", "severe", "unknown"},
                ),
                is_new_or_changed=_validated_evidence_value(
                    text,
                    symptom.is_new_or_changed,
                    {"true", "false", "unknown"},
                ),
                findings=_validated_findings(text, symptom.findings),
                negated_findings=_validated_findings(
                    text,
                    symptom.negated_findings,
                    force_absent=True,
                ),
            )
        )

    return ChiefComplaintAssessment(
        primary_symptom=primary_symptom,
        primary_evidence=primary_evidence,
        primary_symptom_code=primary_symptom_code,
        symptoms=symptoms,
        symptom_domains=cast(
            list[str | RouteEvidence],
            list(dict.fromkeys(supported_domains))[:4],
        ),
        onset_time=onset_time,
        onset=onset,
        course=course,
        duration=duration,
        severity=severity,
        is_new_or_changed=is_new_or_changed,
        findings=findings,
        negated_findings=negated,
        route_candidates=cast(
            list[str | RouteEvidence],
            list(dict.fromkeys(route_candidates))[:4],
        ),
        symptom_assessments=symptom_assessments,
        questionnaire_answers=questionnaire_answers[:24],
        uncertain_fields=[
            _trim(field, 80) for field in assessment.uncertain_fields[:12] if _trim(field, 80)
        ],
    )


def build_fhir_risk_profile(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Normalize selected historical risk factors without sending raw FHIR."""
    rules = load_safety_rules()
    history_fields = rules["fhir_history_fields"]
    history = "、".join(_trim(data.get(field), 500) for field in history_fields if data.get(field))
    profile: dict[str, dict[str, Any]] = {}
    for risk, patterns in rules["fhir_risk_patterns"].items():
        pattern = "|".join(f"(?:{item})" for item in patterns)
        match = re.search(pattern, history, flags=re.IGNORECASE)
        profile[risk] = {
            "present": bool(match),
            "evidence": match.group(0) if match else "",
        }
    return profile


class ChiefComplaintExtractor:
    """Use an LLM for semantic extraction while retaining deterministic control."""

    def __init__(self, llm_client: Any):
        self.llm = llm_client

    def extract(
        self,
        text: str,
    ) -> tuple[ChiefComplaintAssessment | None, str]:
        redacted = _DIRECT_IDENTIFIER.sub("[已遮蔽識別碼]", _trim(text, 1200))
        try:
            response = self.llm.generate_text(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是醫療預問診的主訴資訊抽取器，不是診斷或分流模型。"
                            "只能整理病人明確說出的內容。每個非unknown欄位都必須"
                            "附上病人原句中的逐字evidence，不得補充、推測或改寫。"
                            "只能輸出指定JSON，不得輸出診斷、建議或Markdown。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": self._prompt(redacted),
                    },
                ],
                temperature=0,
                max_tokens=1200,
            )
            parsed = ChiefComplaintAssessment.from_model_text(response)
            return validate_assessment(redacted, parsed), ""
        except Exception as error:
            return None, f"{type(error).__name__}: {_trim(error, 240)}"

    @staticmethod
    def _prompt(text: str) -> str:
        rules = load_safety_rules()
        route_values = "、".join([*rules["supported_routes"], "other", "unknown"])
        finding_values = "、".join(rules["finding_codes"])
        example_finding = rules["finding_codes"][0]
        semantic = rules["semantic_extraction"]
        normalization_guidance = "\n".join(
            f"- {item}" for item in semantic["normalization_instructions"]
        )
        severity_guidance = json.dumps(
            semantic["severity_definitions"],
            ensure_ascii=False,
        )
        course_guidance = json.dumps(
            semantic["course_definitions"],
            ensure_ascii=False,
        )
        duration_guidance = json.dumps(
            semantic["duration_definitions"],
            ensure_ascii=False,
        )
        symptom_guidance = json.dumps(
            semantic["symptom_definitions"],
            ensure_ascii=False,
        )
        example_symptom = next(iter(semantic["symptom_definitions"]))
        finding_guidance = json.dumps(
            semantic["finding_definitions"],
            ensure_ascii=False,
        )
        matched_routes = [
            route
            for route, keywords in rules["route_keywords"].items()
            if any(keyword in text for keyword in keywords)
        ]
        questionnaire_catalog = json.dumps(
            _questionnaire_answer_catalog(
                matched_routes if len(matched_routes) == 1 else DISEASE_ROUTES
            ),
            ensure_ascii=False,
        )
        return f"""
請將以下病人自由主訴轉成結構化JSON。不要判斷urgent，不要診斷。

病人原文：
{text}

規則：
1. primary_symptom只能是單一字串：
   {route_values}。
   symptom_domains及route_candidates必須是物件陣列，每個物件只能包含
   route與evidence；route只能使用上述值，evidence必須逐字取自病人原文。
2. symptoms只能輸出白名單症狀code與逐字evidence；primary_symptom_code
   必須是其中一個code，不能自行創造症狀。
3. onset只描述開始方式：sudden、gradual、unknown。
4. onset_time記錄「幾分鐘／小時／天／週／月／年前開始」等明確時間；
   value及evidence都必須來自原文。沒有明確時間就用unknown。
5. course只描述時間型態：episodic、continuous、recurrent、unknown。
6. duration只描述持續長短：brief、prolonged、unknown；沒有明確描述就用unknown。
7. severity.value只能是mild、moderate、severe、unknown。
8. is_new_or_changed.value只能是JSON字串"true"、"false"、"unknown"，
   不可輸出JSON boolean。
9. finding.code只能使用下列代碼：
   {finding_values}。
10. findings只放present；negated_findings只放病人明確否認的項目。
11. 每個非unknown值、症狀、route及finding都必須附原文逐字evidence。
12. 即使有多個症狀，symptom_domains及route_candidates仍不可輸出字串以外
   的route值，也不可使用domain、value等其他欄位名稱。
13. 有多個症狀時，symptom_assessments要為每個症狀分別整理onset_time、
   onset、course、duration、嚴重程度、是否新發或改變及相關finding；
   不可把一個症狀的時間資訊套用到另一個症狀。
14. 只有 headache、chest_pain、chest_tightness、abdominal_pain 可以啟動
   對應的症狀問卷。頭暈、頭部外傷、視覺異常、噁心或嘔吐若沒有上述症狀，
   不得輸出 headache、chest 或 abdomen route；它們只能記錄為finding或
   非路由症狀。
15. questionnaire_answers記錄病人原文已回答的核准問卷資訊。route、field
   及value必須使用下方目錄中的原值；evidence必須逐字取自病人原文。
   沒有回答的欄位不可輸出，也不可自行創造答案。multiple=true的題目中，
   單一已知選項只代表部分答案，不代表整題已完成；仍要將該症狀輸出為
   finding，讓系統移除已知選項後繼續詢問其他選項。

語意正規化原則：
{normalization_guidance}

severity定義：
{severity_guidance}

course定義：
{course_guidance}

duration定義：
{duration_guidance}

症狀白名單：
{symptom_guidance}

finding定義：
{finding_guidance}

可預填的問卷資訊目錄：
{questionnaire_catalog}

只回傳：
{{
  "primary_symptom": "unknown",
  "primary_evidence": "",
  "primary_symptom_code": "unknown",
  "symptoms": [
    {{"code": "{example_symptom}", "evidence": "原文症狀片段"}}
  ],
  "symptom_domains": [
    {{"route": "unknown", "evidence": ""}}
  ],
  "onset_time": {{"value": "unknown", "evidence": ""}},
  "onset": {{"value": "unknown", "evidence": ""}},
  "course": {{"value": "unknown", "evidence": ""}},
  "duration": {{"value": "unknown", "evidence": ""}},
  "severity": {{"value": "unknown", "evidence": ""}},
  "is_new_or_changed": {{"value": "unknown", "evidence": ""}},
  "findings": [
    {{"code": "{example_finding}", "status": "present", "evidence": "原文片段"}}
  ],
  "negated_findings": [],
  "route_candidates": [
    {{"route": "unknown", "evidence": ""}}
  ],
  "symptom_assessments": [
    {{
      "route": "unknown",
      "evidence": "",
      "symptom_code": "unknown",
      "onset_time": {{"value": "unknown", "evidence": ""}},
      "onset": {{"value": "unknown", "evidence": ""}},
      "course": {{"value": "unknown", "evidence": ""}},
      "duration": {{"value": "unknown", "evidence": ""}},
      "severity": {{"value": "unknown", "evidence": ""}},
      "is_new_or_changed": {{"value": "unknown", "evidence": ""}},
      "findings": [],
      "negated_findings": []
    }}
  ],
  "questionnaire_answers": [],
  "uncertain_fields": []
}}
""".strip()


def prioritized_routes(
    assessment: ChiefComplaintAssessment | None,
    risk_profile: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Rank evidenced symptom routes while retaining every supported route."""
    if not assessment:
        return []
    allowed_routes = supported_routes()
    candidates = [
        route
        for route in assessment.route_candidates
        if isinstance(route, str) and route in allowed_routes
    ]
    profiles = {
        profile.route: profile
        for profile in assessment.symptom_assessments
        if profile.route in allowed_routes
    }
    for route in profiles:
        if route not in candidates:
            candidates.append(route)
    if (
        assessment.primary_symptom in allowed_routes
        and assessment.primary_evidence
        and assessment.primary_symptom not in candidates
    ):
        candidates.insert(0, assessment.primary_symptom)

    risks = risk_profile or {}
    rules = load_safety_rules()["structured_rules"]
    route_risks: dict[str, set[str]] = {route: set() for route in allowed_routes}
    for rule in rules:
        primary_routes = rule.get("when", {}).get("primary_in", [])
        requested_risks = {
            *rule.get("when", {}).get("all_risks", []),
            *rule.get("when", {}).get("any_risks", []),
        }
        for route in primary_routes:
            if route in route_risks:
                route_risks[route].update(requested_risks)

    severity_score = {"severe": 30, "moderate": 20, "mild": 10}
    onset_score = {"sudden": 12, "gradual": 4}

    def priority(route: str) -> int:
        profile = profiles.get(route)
        if not profile:
            return 0
        score = severity_score.get(profile.severity.value, 0)
        score += onset_score.get(profile.onset.value, 0)
        score += 6 if profile.is_new_or_changed.value == "true" else 0
        score += len({finding.code for finding in profile.findings if finding.status == "present"})
        score += 3 * sum(
            bool(risks.get(risk, {}).get("present")) for risk in route_risks.get(route, set())
        )
        return score

    return sorted(candidates, key=priority, reverse=True)


def preferred_route(
    assessment: ChiefComplaintAssessment | None,
    risk_profile: dict[str, dict[str, Any]] | None = None,
) -> str | None:
    if not assessment:
        return None
    ranked = prioritized_routes(assessment, risk_profile)
    if assessment.symptom_assessments and ranked:
        return ranked[0]
    allowed_routes = supported_routes()
    if assessment.primary_symptom in {*allowed_routes, "other"} and assessment.primary_evidence:
        return assessment.primary_symptom
    supported = [
        route
        for route in assessment.route_candidates
        if isinstance(route, str) and route in allowed_routes
    ]
    return supported[0] if len(supported) == 1 else None
