"""State-aware interview graph with semantic extraction and deterministic scoring."""

from __future__ import annotations

import os
import re
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from domain.questionnaires import (
    condition_matches,
    load_questionnaire_policy,
)

from .chief_complaint import (
    ChiefComplaintExtractor,
    build_fhir_risk_profile,
)
from .clinical_facts import (
    facts_from_assessment,
    facts_from_legacy_data,
    filter_question_by_known_facts,
    merge_facts,
)
from .disease_profiles import (
    attach_safety_conditions,
    question_utility,
    score_diseases,
)
from .models import (
    AMIEEngineResult,
    ChiefComplaintAssessment,
    ChiefFinding,
    EvidenceValue,
)
from .rule_config import supported_routes
from .safety import detect_red_flags, detect_structured_red_flags

SUPPORTED_ROUTES = supported_routes()


class AMIEGraphState(TypedDict, total=False):
    route: str
    answer: str
    current_field: str
    data: dict[str, Any]
    questionnaire: list[dict[str, Any]]
    prefilled_fields: list[str]
    turn_count: int
    decision: dict[str, Any]
    next_question: dict[str, Any] | None
    action: str
    triage_level: str
    acknowledgement: str
    handoff_reason: str
    red_flags: list[dict[str, Any]]
    differential_hypotheses: list[dict[str, Any]]
    disease_assessment: dict[str, Any]
    clinical_facts: list[dict[str, Any]]
    knowledge_gaps: list[str]
    evidence_timeline: list[dict[str, Any]]
    rag_context: str
    rag_sources: list[dict[str, Any]]
    model_error: str


def _bounded_int(value: str | None, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(parsed, high))


def _trim(value: Any, limit: int = 500) -> str:
    return str(value).strip()[:limit]


class AMIEEngine:
    """Run one state transition per patient answer.

    The injected LLM only extracts evidence-grounded clinical facts. Safety,
    disease voting, completion, and question selection remain deterministic.
    """

    def __init__(
        self,
        llm_client: Any,
        *,
        max_turns: int | None = None,
    ):
        self.llm = llm_client
        policy_default = max(
            load_questionnaire_policy(route)["max_turns"] for route in SUPPORTED_ROUTES
        )
        configured_max_turns = os.getenv("AMIE_MAX_TURNS")
        self.max_turns = max_turns or (
            _bounded_int(
                configured_max_turns,
                default=policy_default,
                low=1,
                high=100,
            )
            if configured_max_turns is not None
            else policy_default
        )
        self.chief_extractor = ChiefComplaintExtractor(llm_client)
        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(AMIEGraphState)
        workflow.add_node("safety", self._safety_node)
        workflow.add_node("plan", self._plan_node)
        workflow.add_node("validate", self._validate_node)
        workflow.add_edge(START, "safety")
        workflow.add_conditional_edges(
            "safety",
            self._safety_branch,
            {
                "urgent": END,
                "handoff": END,
                "routine": "plan",
            },
        )
        workflow.add_edge("plan", "validate")
        workflow.add_edge("validate", END)
        return workflow.compile()

    @staticmethod
    def _safety_branch(state: AMIEGraphState) -> str:
        if state.get("triage_level") == "urgent":
            return "urgent"
        if state.get("action") == "handoff":
            return "handoff"
        return "routine"

    @staticmethod
    def _question_for_field(
        state: AMIEGraphState,
        field: str,
    ) -> dict[str, Any] | None:
        return next(
            (item for item in state.get("questionnaire", []) if item.get("field") == field),
            None,
        )

    @staticmethod
    def _structured_answer_assessment(
        state: AMIEGraphState,
    ) -> ChiefComplaintAssessment | None:
        """Convert a validated UI option into semantic facts without an LLM."""
        current_field = state.get("current_field", "")
        question = AMIEEngine._question_for_field(
            state,
            current_field,
        )
        if not question:
            return None
        question_route = question.get("route") or state.get("route", "unknown")
        base_field = question.get("base_field", current_field)

        kind = question.get("kind")
        answer = _trim(state.get("answer", ""), 1000)
        if kind == "duration":
            quick_options = set(question.get("quick_options", []))
            units = sorted(
                question.get("units", []),
                key=len,
                reverse=True,
            )
            is_numeric_duration = any(
                re.fullmatch(
                    rf"\d+(?:\.\d+)?{re.escape(unit)}",
                    answer,
                )
                for unit in units
            )
            if answer not in quick_options and not is_numeric_duration:
                return None
            return ChiefComplaintAssessment(primary_symptom=question_route)
        if kind != "choice":
            return None

        options = set(question.get("options", []))
        field_prefix = current_field[: -len(base_field)] if current_field != base_field else ""
        if base_field == "location" and state.get("data", {}).get(f"{field_prefix}pain_locations"):
            return ChiefComplaintAssessment(primary_symptom=question_route)

        selected: list[str] = []
        remaining = answer
        ordered_options = sorted(options, key=len, reverse=True)
        while remaining:
            matched = next(
                (option for option in ordered_options if remaining.startswith(option)),
                None,
            )
            if not matched:
                return None
            selected.append(matched)
            remaining = remaining[len(matched) :]
            if not remaining:
                break
            if not remaining.startswith("、"):
                return None
            remaining = remaining[1:]

        if not selected:
            return None

        semantic_options = question.get("semantic_options", {})
        onset = EvidenceValue()
        course = EvidenceValue()
        duration = EvidenceValue()
        severity = EvidenceValue()
        new_or_changed = EvidenceValue()
        findings: list[ChiefFinding] = []
        negated_findings: list[ChiefFinding] = []
        for option in selected:
            facts = semantic_options.get(option, {})
            if value := facts.get("onset"):
                onset = EvidenceValue(value=value, evidence=option)
            if value := facts.get("course"):
                course = EvidenceValue(value=value, evidence=option)
            if value := facts.get("duration"):
                duration = EvidenceValue(value=value, evidence=option)
            if value := facts.get("severity"):
                severity = EvidenceValue(value=value, evidence=option)
            if value := facts.get("new_or_changed"):
                new_or_changed = EvidenceValue(
                    value=value,
                    evidence=option,
                )
            findings.extend(
                ChiefFinding(
                    code=code,
                    status="present",
                    evidence=option,
                )
                for code in facts.get("findings", [])
            )
            negated_findings.extend(
                ChiefFinding(
                    code=code,
                    status="absent",
                    evidence=option,
                )
                for code in facts.get("negated_findings", [])
            )
        return ChiefComplaintAssessment(
            primary_symptom=question_route,
            onset=onset,
            course=course,
            duration=duration,
            severity=severity,
            is_new_or_changed=new_or_changed,
            findings=findings,
            negated_findings=negated_findings,
        )

    @staticmethod
    def _merge_safety_assessment(
        data: dict[str, Any],
        route: str,
        delta: ChiefComplaintAssessment,
    ) -> ChiefComplaintAssessment:
        stored = data.get("_semantic_safety_state")
        if not stored:
            stored = (
                data.get("_chief_assessment", {}).get("extraction")
                if isinstance(data.get("_chief_assessment"), dict)
                else None
            )
        try:
            base = (
                ChiefComplaintAssessment.model_validate(stored)
                if stored
                else ChiefComplaintAssessment()
            )
        except Exception:
            base = ChiefComplaintAssessment()

        def latest_value(
            newer: EvidenceValue,
            older: EvidenceValue,
        ) -> EvidenceValue:
            return newer if newer.value != "unknown" else older

        findings = {(item.code, item.status): item for item in [*base.findings, *delta.findings]}
        negated = {
            (item.code, item.status): item
            for item in [
                *base.negated_findings,
                *delta.negated_findings,
            ]
        }
        primary = (
            delta.primary_symptom
            if delta.primary_symptom != "unknown"
            else (base.primary_symptom if base.primary_symptom != "unknown" else route)
        )
        primary_evidence = (
            delta.primary_evidence if delta.primary_evidence else base.primary_evidence
        )

        def route_code(item: str | Any) -> str:
            return str(getattr(item, "route", item))

        return ChiefComplaintAssessment(
            primary_symptom=primary,
            primary_evidence=primary_evidence,
            primary_symptom_code=(
                delta.primary_symptom_code
                if delta.primary_symptom_code != "unknown"
                else base.primary_symptom_code
            ),
            symptoms=list({item.code: item for item in [*base.symptoms, *delta.symptoms]}.values()),
            symptom_domains=list(
                dict.fromkeys(
                    [
                        *(route_code(item) for item in base.symptom_domains),
                        *(route_code(item) for item in delta.symptom_domains),
                    ]
                )
            ),
            onset=latest_value(delta.onset, base.onset),
            course=latest_value(delta.course, base.course),
            duration=latest_value(delta.duration, base.duration),
            severity=latest_value(delta.severity, base.severity),
            is_new_or_changed=latest_value(
                delta.is_new_or_changed,
                base.is_new_or_changed,
            ),
            findings=list(findings.values()),
            negated_findings=list(negated.values()),
            route_candidates=list(
                dict.fromkeys(
                    [
                        *(route_code(item) for item in base.route_candidates),
                        *(route_code(item) for item in delta.route_candidates),
                    ]
                )
            ),
            symptom_assessments=list(
                {
                    (item.route, item.symptom_code): item
                    for item in [
                        *base.symptom_assessments,
                        *delta.symptom_assessments,
                    ]
                }.values()
            ),
            uncertain_fields=list(
                dict.fromkeys(
                    [
                        *base.uncertain_fields,
                        *delta.uncertain_fields,
                    ]
                )
            ),
        )

    def run_turn(
        self,
        *,
        route: str,
        answer: str,
        current_field: str,
        data: dict[str, Any],
        questionnaire: list[dict[str, Any]],
        prefilled_fields: set[str] | None = None,
        turn_count: int = 1,
        previous_state: dict[str, Any] | None = None,
    ) -> AMIEEngineResult:
        previous_state = previous_state or {}
        state: AMIEGraphState = {
            "route": route,
            "answer": answer,
            "current_field": current_field,
            "data": dict(data),
            "questionnaire": questionnaire,
            "prefilled_fields": sorted(prefilled_fields or set()),
            "turn_count": turn_count,
            "triage_level": previous_state.get("triage_level", "routine"),
            "red_flags": list(previous_state.get("red_flags", [])),
            "differential_hypotheses": list(previous_state.get("differential_hypotheses", [])),
            "disease_assessment": dict(previous_state.get("disease_assessment", {})),
            "clinical_facts": list(
                previous_state.get("clinical_facts", data.get("_clinical_facts", []))
            ),
            "knowledge_gaps": list(previous_state.get("knowledge_gaps", [])),
            "evidence_timeline": list(previous_state.get("evidence_timeline", [])),
            "rag_sources": list(previous_state.get("rag_sources", [])),
            "model_error": "",
        }
        result = self.graph.invoke(state)
        return AMIEEngineResult(
            action=result.get("action", "handoff"),
            triage_level=result.get("triage_level", "routine"),
            data=result.get("data", data),
            decision=result.get("decision", {}),
            next_question=result.get("next_question"),
            acknowledgement=result.get("acknowledgement", ""),
            handoff_reason=result.get("handoff_reason", ""),
            red_flags=result.get("red_flags", []),
            differential_hypotheses=result.get("differential_hypotheses", []),
            disease_assessment=result.get("disease_assessment", {}),
            clinical_facts=result.get("clinical_facts", []),
            knowledge_gaps=result.get("knowledge_gaps", []),
            evidence_timeline=result.get("evidence_timeline", []),
            rag_sources=result.get("rag_sources", []),
            model_error=result.get("model_error", ""),
        )

    def _safety_node(self, state: AMIEGraphState) -> dict[str, Any]:
        new_flags = detect_red_flags(
            state.get("route"),
            state.get("answer", ""),
            state.get("data", {}),
        )
        existing = list(state.get("red_flags", []))
        seen = {flag.get("code") for flag in existing}
        flags = [
            *existing,
            *(flag for flag in new_flags if flag.get("code") not in seen),
        ]
        if flags:
            data = dict(state.get("data", {}))
            clinical_facts = list(state.get("clinical_facts", data.get("_clinical_facts", [])))
            assessment = attach_safety_conditions(
                state.get("route", ""),
                flags,
                facts=clinical_facts,
            )
            data["_disease_assessment"] = assessment
            return {
                "data": data,
                "red_flags": flags,
                "triage_level": "urgent",
                "action": "complete",
                "next_question": None,
                "acknowledgement": "",
                "disease_assessment": assessment,
                "clinical_facts": clinical_facts,
            }

        # Identity fields remain local. All clinical free text gets a
        # semantic safety pass before the planning model may select a
        # follow-up question.
        current_question = self._question_for_field(
            state,
            state.get("current_field", ""),
        )
        if current_question and current_question.get("section") == "basic":
            return {
                "red_flags": [],
                "triage_level": "routine",
            }

        data = dict(state.get("data", {}))
        delta = self._structured_answer_assessment(state)
        structured_answer = delta is not None
        reused_chief_extraction = False
        if delta is None and state.get("current_field") == "reason":
            stored_extraction = (
                data.get("_chief_assessment", {}).get("extraction")
                if isinstance(data.get("_chief_assessment"), dict)
                else None
            )
            if stored_extraction:
                try:
                    delta = ChiefComplaintAssessment.model_validate(stored_extraction)
                    reused_chief_extraction = True
                except Exception:
                    delta = None
        semantic_error = ""
        if delta is None:
            delta, semantic_error = self.chief_extractor.extract(state.get("answer", ""))
        if not delta:
            data["_last_semantic_safety"] = {
                "extraction": None,
                "model_error": semantic_error,
            }
            return {
                "data": data,
                "red_flags": [],
                "triage_level": "routine",
                "action": "handoff",
                "next_question": None,
                "handoff_reason": ("語意安全檢查暫時無法完成，請由醫療人員確認"),
                "model_error": semantic_error,
            }

        assessment = self._merge_safety_assessment(
            data,
            state.get("route", ""),
            delta,
        )
        risk_profile = build_fhir_risk_profile(data)
        semantic_flags = detect_structured_red_flags(
            assessment,
            risk_profile,
            state.get("route"),
        )
        data["_last_semantic_safety"] = {
            "extraction": delta.as_dict(),
            "fhir_risk_profile": risk_profile,
            "safety_flags": semantic_flags,
            "model_error": "",
        }
        data["_semantic_safety_state"] = assessment.as_dict()
        clinical_facts = merge_facts(
            state.get("clinical_facts", data.get("_clinical_facts", [])),
            facts_from_assessment(
                delta,
                turn=state.get("turn_count", 0),
                source=(
                    "structured_option"
                    if structured_answer
                    else "chief_semantic_extraction"
                    if reused_chief_extraction
                    else "semantic_extraction"
                ),
            ),
        )
        data["_clinical_facts"] = clinical_facts
        if not semantic_flags:
            return {
                "data": data,
                "red_flags": [],
                "triage_level": "routine",
                "clinical_facts": clinical_facts,
            }
        disease_assessment = attach_safety_conditions(
            state.get("route", ""),
            semantic_flags,
            facts=clinical_facts,
        )
        data["_disease_assessment"] = disease_assessment
        return {
            "data": data,
            "red_flags": semantic_flags,
            "triage_level": "urgent",
            "action": "complete",
            "next_question": None,
            "acknowledgement": "",
            "clinical_facts": clinical_facts,
            "disease_assessment": disease_assessment,
        }

    def _plan_node(self, state: AMIEGraphState) -> dict[str, Any]:
        candidates = self._remaining_questions(state)
        if not candidates:
            return {
                "decision": {
                    "action": "complete",
                    "next_field": None,
                    "needs_retrieval": False,
                    "retrieval_query": "",
                    "audit_reason": "所有適用且核准的問題皆已完成，流程可結束。",
                }
            }

        current_field = state.get("current_field", "")
        basic_candidate = next(
            (item for item in candidates if item.get("section") == "basic"),
            None,
        )
        current_question = self._question_for_field(
            state,
            current_field,
        )
        if current_question and current_question.get("section") == "basic" and basic_candidate:
            return {
                "decision": {
                    "action": "ask",
                    "next_field": basic_candidate["field"],
                    "needs_retrieval": False,
                    "retrieval_query": "",
                    "audit_reason": "基本資料於院內以確定性流程收集",
                }
            }

        data = dict(state.get("data", {}))
        clinical_facts = merge_facts(
            state.get("clinical_facts", data.get("_clinical_facts", [])),
            facts_from_legacy_data(data),
        )
        data["_clinical_facts"] = clinical_facts
        route = state.get("route", "")
        policy = load_questionnaire_policy(route)
        use_disease_vote = policy["selection_strategy"] == "disease_vote"
        scoring_error = ""
        assessment: dict[str, Any] = {}
        if use_disease_vote:
            try:
                assessment = score_diseases(
                    clinical_facts,
                    route=route,
                    computed_from="live",
                )
            except Exception as error:
                scoring_error = f"{type(error).__name__}: {_trim(error, 200)}"
                assessment = {
                    "schema_version": 1,
                    "method": "unit_vote_v1",
                    "status": "unavailable",
                    "computed_from": "live",
                    "top": [],
                    "ranked": [],
                    "must_not_miss": [],
                }
        if assessment:
            data["_disease_assessment"] = assessment

        required_missing = self._required_missing(
            data,
            state.get("questionnaire", []),
            clinical_facts,
        )
        candidate_by_field = {item["field"]: item for item in candidates}
        priority_fields = tuple(policy["priority_fields"])
        selected = next(
            (candidate_by_field[field] for field in priority_fields if field in candidate_by_field),
            None,
        )
        utilities = {}
        if use_disease_vote and not scoring_error:
            utilities = {
                item["field"]: question_utility(
                    item,
                    assessment,
                    route=route,
                )
                for item in candidates
            }
        if use_disease_vote and selected is None:
            selected = max(
                candidates,
                key=lambda item: (
                    utilities.get(item["field"], 0),
                    -candidates.index(item),
                ),
            )
        elif not use_disease_vote:
            selected = candidates[0]

        top = assessment.get("top", [])
        coverage_ready = bool(top) and all(
            item["coverage"] >= policy["coverage_threshold"] for item in top
        )
        no_score_changing_question = not any(utilities.values())
        can_complete = (
            not scoring_error
            and not required_missing
            and (
                not use_disease_vote
                and not candidates
                or use_disease_vote
                and (coverage_ready or no_score_changing_question)
            )
        )
        action = "handoff" if scoring_error else "complete" if can_complete else "ask"
        next_field = selected["field"] if action == "ask" and selected else None
        reason = (
            "固定疾病表無法使用，停止自動評分並轉交醫療人員。"
            if scoring_error
            else "最低必要資料已完成，且候選疾病完整度已達門檻。"
            if coverage_ready and can_complete
            else "最低必要資料已完成，剩餘問題不會改變目前疾病票數。"
            if no_score_changing_question and can_complete
            else "依安全優先順序選擇下一題。"
            if selected and selected["field"] in priority_fields
            else "依目前候選疾病間的投票區辨力選擇下一題。"
            if use_disease_vote
            else "非胸痛路由依核准問卷固定順序追問。"
        )
        decision = {
            "action": action,
            "next_field": next_field,
            "extracted_facts": {},
            "negated_findings": [],
            "knowledge_gaps": sorted(
                {
                    fact
                    for item in assessment.get("top", [])
                    for fact in item.get("missing_facts", [])
                }
            )[:12],
            "needs_retrieval": False,
            "retrieval_query": "",
            "acknowledgement": "",
            "audit_reason": reason,
            "question_utility": utilities.get(next_field, 0) if next_field else 0,
            "scoring_method": assessment.get("method", ""),
        }
        timeline = list(state.get("evidence_timeline", []))
        timeline.append(
            {
                "turn": state.get("turn_count", 0),
                "answer_excerpt": _trim(state.get("answer", ""), 240),
                "clinical_facts": clinical_facts,
                "disease_votes": [
                    {
                        "id": item["id"],
                        "net_votes": item["net_votes"],
                        "coverage": item["coverage"],
                    }
                    for item in assessment.get("top", [])
                ],
                "audit_reason": reason,
            }
        )
        return {
            "decision": decision,
            "data": data,
            "differential_hypotheses": [],
            "disease_assessment": assessment,
            "clinical_facts": clinical_facts,
            "knowledge_gaps": decision["knowledge_gaps"],
            "evidence_timeline": timeline[-30:],
            "rag_sources": [],
            "model_error": scoring_error,
        }

    def _validate_node(self, state: AMIEGraphState) -> dict[str, Any]:
        data = state.get("data", {})
        candidates = self._remaining_questions({**state, "data": data})
        basic = next(
            (item for item in candidates if item.get("section") == "basic"),
            None,
        )
        if basic:
            return {
                "action": "ask",
                "next_question": basic,
                "acknowledgement": "",
            }

        decision = state.get("decision", {})
        required_missing = self._required_missing(
            data,
            state.get("questionnaire", []),
            state.get(
                "clinical_facts",
                data.get("_clinical_facts", []),
            ),
        )

        if decision.get("action") == "handoff":
            return {
                "action": "handoff",
                "next_question": None,
                "handoff_reason": (
                    decision.get("audit_reason") or "自動問診無法安全繼續，請由醫療人員確認"
                ),
            }

        if decision.get("action") == "complete" and not required_missing:
            return {
                "action": "complete",
                "next_question": None,
                "acknowledgement": _trim(
                    decision.get("acknowledgement"),
                    120,
                ),
            }

        if state.get("turn_count", 0) >= self.max_turns:
            return {
                "action": "handoff",
                "next_question": None,
                "handoff_reason": ("已達動態問診輪數上限，仍有資訊需要醫療人員確認"),
            }

        by_field = {item["field"]: item for item in candidates}

        selected = by_field.get(decision.get("next_field"))
        if selected is None:
            selected = next(
                (by_field[field] for field in required_missing if field in by_field),
                candidates[0] if candidates else None,
            )

        if selected is None:
            if required_missing:
                return {
                    "action": "handoff",
                    "next_question": None,
                    "handoff_reason": ("必要欄位無可用問題，請由醫療人員補充確認"),
                }
            return {"action": "complete", "next_question": None}

        return {
            "action": "ask",
            "next_question": selected,
            "acknowledgement": _trim(decision.get("acknowledgement"), 120),
        }

    def _remaining_questions(
        self,
        state: AMIEGraphState,
    ) -> list[dict[str, Any]]:
        data = state.get("data", {})
        skip = set(state.get("prefilled_fields", []))
        remaining = []
        for item in state.get("questionnaire", []):
            if (
                item["field"] == "reason"
                or item["field"] in data
                or item["field"] in skip
                or not condition_matches(item, data)
            ):
                continue
            filtered = filter_question_by_known_facts(
                item,
                state.get(
                    "clinical_facts",
                    data.get("_clinical_facts", []),
                ),
            )
            if filtered is not None:
                remaining.append(filtered)
        return remaining

    @staticmethod
    def _required_missing(
        data: dict[str, Any],
        questionnaire: list[dict[str, Any]],
        clinical_facts: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        selected_routes = [
            route for route in data.get("types", [data.get("type")]) if route in SUPPORTED_ROUTES
        ]
        required_by_route = {
            route: set(load_questionnaire_policy(route)["required_fields"])
            for route in selected_routes
        }
        shared_required = set().union(*required_by_route.values())
        missing: list[str] = []
        for item in questionnaire:
            field = item["field"]
            base_field = item.get("base_field", field)
            item_route = item.get("route")
            required = (
                base_field in required_by_route.get(item_route, set())
                if item_route
                else base_field in shared_required
            )
            unresolved_question = filter_question_by_known_facts(
                item,
                clinical_facts,
            )
            if required and not _trim(data.get(field, "")) and unresolved_question is not None:
                missing.append(field)
        return missing
