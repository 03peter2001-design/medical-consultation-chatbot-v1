"""State-aware, Gemini-backed interview graph inspired by AMIE research."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from domain.questionnaires import condition_matches, parse_onset_answer

from .chief_complaint import (
    ChiefComplaintExtractor,
    build_fhir_risk_profile,
)
from .models import (
    AMIEDecision,
    AMIEEngineResult,
    ChiefComplaintAssessment,
    ChiefFinding,
    EvidenceValue,
)
from .rule_config import supported_routes
from .safety import detect_red_flags, detect_structured_red_flags

SUPPORTED_ROUTES = supported_routes()
PROTECTED_MODEL_FIELDS = {
    "name",
    "birth_date",
    "national_id",
    "id_number",
    "patient_id",
}
BASIC_FIELDS = ("name", "gender", "birth_date", "blood_type")
REQUIRED_FIELDS = {
    "chest": {
        "onset",
        "location",
        "quality",
        "aggravate",
        "associated",
        "current_meds",
        "allergy",
    },
    "headache": {
        "onset",
        "start_type",
        "worst_ever",
        "associated",
        "risk_flags",
        "current_meds",
        "allergy",
    },
    "abdomen": {
        "onset",
        "location",
        "associated",
        "current_meds",
        "allergy",
    },
}


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
    red_flags: list[dict[str, str]]
    differential_hypotheses: list[dict[str, Any]]
    knowledge_gaps: list[str]
    evidence_timeline: list[dict[str, Any]]
    rag_context: str
    rag_sources: list[dict[str, Any]]
    model_error: str


Retriever = Callable[..., tuple[str, list[dict[str, Any]]]]


def _bounded_int(value: str | None, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(parsed, high))


def _trim(value: Any, limit: int = 500) -> str:
    return str(value).strip()[:limit]


def _redact_identifiers(text: str) -> str:
    text = re.sub(r"\b[A-Z][12]\d{8}\b", "[已遮蔽身分證]", text)
    text = re.sub(r"\b\d{8,12}\b", "[已遮蔽識別碼]", text)
    return text


class AMIEEngine:
    """Run one state transition per patient answer.

    The graph controls safety, optional retrieval, and question selection.
    The injected LLM is currently Gemini, while its interface remains replaceable
    by a future MedGemma service.
    """

    def __init__(
        self,
        llm_client: Any,
        *,
        retriever: Retriever | None = None,
        max_turns: int | None = None,
    ):
        self.llm = llm_client
        self.retriever = retriever
        self.max_turns = max_turns or _bounded_int(
            os.getenv("AMIE_MAX_TURNS"),
            default=24,
            low=8,
            high=40,
        )
        self.chief_extractor = ChiefComplaintExtractor(llm_client)
        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(AMIEGraphState)
        workflow.add_node("safety", self._safety_node)
        workflow.add_node("plan", self._plan_node)
        workflow.add_node("retrieve", self._retrieve_node)
        workflow.add_node("mx_refine", self._mx_refine_node)
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
        workflow.add_conditional_edges(
            "plan",
            self._retrieval_branch,
            {"retrieve": "retrieve", "validate": "validate"},
        )
        workflow.add_edge("retrieve", "mx_refine")
        workflow.add_edge("mx_refine", "validate")
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
    def _structured_answer_assessment(
        state: AMIEGraphState,
    ) -> ChiefComplaintAssessment | None:
        """Convert a validated UI option into semantic facts without an LLM."""
        current_field = state.get("current_field", "")
        question = next(
            (item for item in state.get("questionnaire", []) if item.get("field") == current_field),
            None,
        )
        if not question:
            return None

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
            return ChiefComplaintAssessment(primary_symptom=state.get("route", "unknown"))
        if kind != "choice":
            return None

        options = set(question.get("options", []))
        if current_field == "location" and state.get("data", {}).get("pain_locations"):
            return ChiefComplaintAssessment(primary_symptom=state.get("route", "unknown"))

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
        severity = EvidenceValue()
        new_or_changed = EvidenceValue()
        findings: list[ChiefFinding] = []
        for option in selected:
            facts = semantic_options.get(option, {})
            if value := facts.get("onset"):
                onset = EvidenceValue(value=value, evidence=option)
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
        return ChiefComplaintAssessment(
            primary_symptom=state.get("route", "unknown"),
            onset=onset,
            severity=severity,
            is_new_or_changed=new_or_changed,
            findings=findings,
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
        return ChiefComplaintAssessment(
            primary_symptom=primary,
            primary_evidence=primary_evidence,
            symptom_domains=list(
                dict.fromkeys(
                    [
                        *base.symptom_domains,
                        *delta.symptom_domains,
                    ]
                )
            ),
            onset=latest_value(delta.onset, base.onset),
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
                        *base.route_candidates,
                        *delta.route_candidates,
                    ]
                )
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
            return {
                "red_flags": flags,
                "triage_level": "urgent",
                "action": "complete",
                "next_question": None,
                "acknowledgement": "",
            }

        # Identity fields remain local. All clinical free text gets a
        # semantic safety pass before the planning model may select a
        # follow-up question.
        if state.get("current_field") in BASIC_FIELDS:
            return {
                "red_flags": [],
                "triage_level": "routine",
            }

        data = dict(state.get("data", {}))
        delta = self._structured_answer_assessment(state)
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
        if not semantic_flags:
            return {
                "data": data,
                "red_flags": [],
                "triage_level": "routine",
            }
        return {
            "data": data,
            "red_flags": semantic_flags,
            "triage_level": "urgent",
            "action": "complete",
            "next_question": None,
            "acknowledgement": "",
        }

    def _plan_node(self, state: AMIEGraphState) -> dict[str, Any]:
        candidates = self._remaining_questions(state)
        if not candidates:
            return {
                "decision": AMIEDecision(
                    action="complete",
                    audit_reason=("所有適用且核准的問題皆已完成，流程可結束。"),
                ).as_dict()
            }

        # Basic identity collection stays deterministic and local. In
        # particular, a patient's typed name or birth date is never sent to
        # the external model. Once the last basic field is collected, analyze
        # the already-redacted free-text chief complaint instead.
        current_field = state.get("current_field", "")
        basic_candidate = next(
            (item for field in BASIC_FIELDS for item in candidates if item["field"] == field),
            None,
        )
        if current_field in BASIC_FIELDS and basic_candidate:
            return {
                "decision": AMIEDecision(
                    action="ask",
                    next_field=basic_candidate["field"],
                    audit_reason="基本資料於院內以確定性流程收集",
                ).as_dict()
            }

        planning_state = state.copy()
        if current_field in BASIC_FIELDS:
            planning_state["answer"] = _trim(state.get("data", {}).get("reason", ""), 1000)

        prompt = self._decision_prompt(planning_state, candidates)
        decision, error = self._ask_model(prompt)
        data = self._merge_extracted_facts(
            state.get("data", {}),
            state.get("questionnaire", []),
            decision.extracted_facts,
        )
        timeline = list(state.get("evidence_timeline", []))
        if (
            decision.extracted_facts
            or decision.negated_findings
            or decision.differential_hypotheses
        ):
            timeline.append(
                {
                    "turn": state.get("turn_count", 0),
                    "answer_excerpt": _trim(state.get("answer", ""), 240),
                    "extracted_facts": decision.extracted_facts,
                    "negated_findings": decision.negated_findings[:12],
                    "differential_hypotheses": [
                        item.as_dict() for item in decision.differential_hypotheses[:8]
                    ],
                    "audit_reason": _trim(decision.audit_reason, 300),
                }
            )

        hypotheses = [item.as_dict() for item in decision.differential_hypotheses[:8]]
        return {
            "decision": decision.as_dict(),
            "data": data,
            "differential_hypotheses": (
                hypotheses if hypotheses else state.get("differential_hypotheses", [])
            ),
            "knowledge_gaps": decision.knowledge_gaps[:12],
            "evidence_timeline": timeline[-30:],
            "model_error": error,
        }

    def _retrieval_branch(self, state: AMIEGraphState) -> str:
        decision = state.get("decision", {})
        if (
            self.retriever
            and decision.get("needs_retrieval")
            and _trim(decision.get("retrieval_query", ""))
        ):
            return "retrieve"
        return "validate"

    def _retrieve_node(self, state: AMIEGraphState) -> dict[str, Any]:
        decision = state.get("decision", {})
        query = _redact_identifiers(_trim(decision.get("retrieval_query", ""), 300))
        if not query or not self.retriever:
            return {"rag_context": "", "rag_sources": []}
        try:
            context, sources = self.retriever(
                query,
                n_results=4,
                primary_route=state.get("route"),
                patient_data=self._clinical_snapshot(state.get("data", {})),
                purpose="diagnosis",
            )
        except Exception as exc:
            return {
                "rag_context": "",
                "model_error": (
                    f"{state.get('model_error', '')}; RAG查詢失敗：{type(exc).__name__}"
                ).strip("; "),
            }
        existing = list(state.get("rag_sources", []))
        seen = {(item.get("title"), item.get("url")) for item in existing}
        for source in sources:
            key = (source.get("title"), source.get("url"))
            if key not in seen:
                existing.append(source)
                seen.add(key)
        return {
            "rag_context": context[:6000],
            "rag_sources": existing[-20:],
        }

    def _mx_refine_node(self, state: AMIEGraphState) -> dict[str, Any]:
        context = state.get("rag_context", "")
        if not context:
            return {}
        candidates = self._remaining_questions(state)
        prompt = self._decision_prompt(
            state,
            candidates,
            rag_context=context,
            previous_decision=state.get("decision"),
        )
        decision, error = self._ask_model(prompt, mx_agent=True)
        data = self._merge_extracted_facts(
            state.get("data", {}),
            state.get("questionnaire", []),
            decision.extracted_facts,
        )
        hypotheses = [
            (item.model_dump() if hasattr(item, "model_dump") else item.dict())
            for item in decision.differential_hypotheses[:8]
        ]
        update = {
            "decision": decision.as_dict(),
            "data": data,
            "knowledge_gaps": decision.knowledge_gaps[:12],
            "model_error": (
                f"{state.get('model_error', '')}; {error}".strip("; ")
                if error
                else state.get("model_error", "")
            ),
        }
        if hypotheses:
            update["differential_hypotheses"] = hypotheses
        return update

    def _validate_node(self, state: AMIEGraphState) -> dict[str, Any]:
        data = state.get("data", {})
        candidates = self._remaining_questions({**state, "data": data})
        basic = next(
            (item for field in BASIC_FIELDS for item in candidates if item["field"] == field),
            None,
        )
        if basic:
            return {
                "action": "ask",
                "next_question": basic,
                "acknowledgement": "",
            }

        decision = state.get("decision", {})

        if state.get("turn_count", 0) >= self.max_turns:
            return {
                "action": "handoff",
                "next_question": None,
                "handoff_reason": ("已達動態問診輪數上限，仍有資訊需要醫療人員確認"),
            }

        required_missing = self._required_missing(
            state.get("route", ""),
            data,
        )
        by_field = {item["field"]: item for item in candidates}

        if decision.get("action") == "complete" and not required_missing:
            return {
                "action": "complete",
                "next_question": None,
                "acknowledgement": _trim(decision.get("acknowledgement"), 120),
            }

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

    def _ask_model(
        self,
        prompt: str,
        *,
        mx_agent: bool = False,
    ) -> tuple[AMIEDecision, str]:
        role = (
            "你是AMIE-inspired背景管理推理（Mx）代理人。"
            if mx_agent
            else "你是AMIE-inspired狀態感知問診規劃代理人。"
        )
        try:
            text = self.llm.generate_text(
                [
                    {
                        "role": "system",
                        "content": (
                            f"{role}"
                            "你的輸出只供程式控制流程，不直接向病人顯示。"
                            "不得輸出思維鏈，只能輸出指定JSON與簡短稽核理由。"
                            "不得把語意支持度當作患病機率。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=1000,
            )
            return AMIEDecision.from_model_text(text), ""
        except Exception as exc:
            return (
                AMIEDecision(
                    action="ask",
                    audit_reason="模型輸出失敗，使用確定性問題庫fallback",
                ),
                f"{type(exc).__name__}: {_trim(exc, 200)}",
            )

    def _decision_prompt(
        self,
        state: AMIEGraphState,
        candidates: list[dict[str, Any]],
        *,
        rag_context: str = "",
        previous_decision: dict[str, Any] | None = None,
    ) -> str:
        route = state.get("route", "")
        candidate_payload = [
            {
                "field": item["field"],
                "section": item["section"],
                "prompt": item["prompt"],
                "options": item.get("options", [])[:20],
            }
            for item in candidates
            if item["field"] not in BASIC_FIELDS
        ]
        allowed_extract_fields = [
            item["field"]
            for item in state.get("questionnaire", [])
            if item["field"] not in PROTECTED_MODEL_FIELDS
        ]
        required_missing = self._required_missing(
            route,
            state.get("data", {}),
        )
        knowledge = f"\n\n【已檢索醫療知識】\n{rag_context[:6000]}" if rag_context else ""
        prior = (
            "\n\n【檢索前決策】\n"
            + json.dumps(
                previous_decision,
                ensure_ascii=False,
            )[:2500]
            if previous_decision
            else ""
        )
        return f"""
根據目前累積狀態，抽取本輪回答中的臨床事實，並決定下一步。

問診路由：{route}
安全分級：{state.get("triage_level", "routine")}
已偵測警訊：
{json.dumps(state.get("red_flags", []), ensure_ascii=False)}
本輪病人回答：{_redact_identifiers(_trim(state.get("answer", ""), 1000))}
去識別化臨床狀態：
{json.dumps(self._clinical_snapshot(state.get("data", {})), ensure_ascii=False)[:5000]}

尚未詢問的候選問題：
{json.dumps(candidate_payload, ensure_ascii=False)[:9000]}

仍缺少的最低必要欄位：
{json.dumps(required_missing, ensure_ascii=False)}

可抽取欄位：
{json.dumps(allowed_extract_fields, ensure_ascii=False)}
{prior}{knowledge}

規則：
1. extracted_facts只能使用「可抽取欄位」中的field，不可推測姓名、生日或識別資訊。
2. 已明確取得的資料不要重複詢問；一次只能選一個next_field。
3. 優先詢問可辨識急症或最能區分鑑別方向的資訊缺口。
4. 一般病史追問不需要RAG；只有需要指引、藥物或外部醫療依據時才設定needs_retrieval=true。
5. routine流程中，action=complete只適用於最低必要欄位已齊全且沒有高價值問題。
6. differential_hypotheses只能列定性假說及正反證據，不可提供數字機率。
7. acknowledgement最多60個繁體中文字，不可診斷、不可建議用藥。
8. audit_reason只寫一至兩句可稽核理由，不得輸出隱藏思維鏈。

只回傳以下JSON，不要Markdown：
{{
  "action": "ask",
  "next_field": "候選問題的field或null",
  "extracted_facts": {{"field": "病人明確說出的值"}},
  "negated_findings": ["病人明確否認的症狀"],
  "differential_hypotheses": [
    {{
      "condition": "候選方向",
      "supporting_evidence": ["證據"],
      "opposing_evidence": ["反對證據"]
    }}
  ],
  "knowledge_gaps": ["尚缺資訊"],
  "needs_retrieval": false,
  "retrieval_query": "",
  "acknowledgement": "簡短同理或承接語",
  "audit_reason": "簡短選題理由"
}}
""".strip()

    def _remaining_questions(
        self,
        state: AMIEGraphState,
    ) -> list[dict[str, Any]]:
        data = state.get("data", {})
        skip = set(state.get("prefilled_fields", []))
        return [
            item
            for item in state.get("questionnaire", [])
            if item["field"] != "reason"
            and item["field"] not in data
            and item["field"] not in skip
            and condition_matches(item, data)
        ]

    def _required_missing(
        self,
        route: str,
        data: dict[str, Any],
    ) -> list[str]:
        required = REQUIRED_FIELDS.get(route, set())
        questionnaire_order = [item["field"] for item in self._questionnaire_for_order(route, data)]
        return [
            field
            for field in questionnaire_order
            if field in required and not _trim(data.get(field, ""))
        ]

    @staticmethod
    def _questionnaire_for_order(
        route: str,
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        # The caller only needs the stable field order. Import lazily to avoid
        # loading unrelated disease questionnaires during process startup.
        from domain.questionnaires import build_questionnaire

        if route not in SUPPORTED_ROUTES:
            return []
        return build_questionnaire(route)

    def _merge_extracted_facts(
        self,
        data: dict[str, Any],
        questionnaire: list[dict[str, Any]],
        facts: dict[str, str],
    ) -> dict[str, Any]:
        merged = dict(data)
        allowed = {
            item["field"] for item in questionnaire if item["field"] not in PROTECTED_MODEL_FIELDS
        }
        for field, raw_value in facts.items():
            value = _trim(raw_value)
            if field not in allowed or not value or merged.get(field):
                continue
            merged[field] = value
            if field == "onset":
                parsed = parse_onset_answer(value)
                if parsed:
                    merged["onset_num"], merged["onset_unit"] = parsed
        return merged

    @staticmethod
    def _clinical_snapshot(data: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in data.items()
            if key not in PROTECTED_MODEL_FIELDS
            and not key.startswith("_")
            and value not in (None, "", [], {})
        }
