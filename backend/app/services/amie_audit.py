"""Persistence helpers for concise, clinician-auditable AMIE traces."""

from __future__ import annotations


def save_amie_state(session: dict, result) -> None:
    state = {
        "triage_level": result.triage_level,
        "decision": result.decision,
        "differential_hypotheses": result.differential_hypotheses,
        "knowledge_gaps": result.knowledge_gaps,
        "evidence_timeline": result.evidence_timeline,
        "rag_sources": result.rag_sources,
        "red_flags": result.red_flags,
        "model_error": result.model_error,
    }
    session["amie_state"] = state
    session["data"]["_amie"] = {key: value for key, value in state.items() if key != "model_error"}


def _decision_source(
    *,
    field: str,
    decision: dict,
    model_error: str,
    red_flags: list[dict],
) -> str:
    if red_flags:
        return "safety_rule"
    if model_error:
        return "deterministic_fallback"
    if field in {"name", "gender", "birth_date", "blood_type"}:
        return "deterministic_flow"
    if str(decision.get("audit_reason", "")).startswith("所有適用且核准的問題"):
        return "deterministic_flow"
    if decision.get("needs_retrieval"):
        return "gemini_planner_with_rag"
    return "gemini_planner"


def append_amie_trace(
    session: dict,
    *,
    current_question: dict,
    answer: str,
    result,
) -> None:
    decision = dict(result.decision or {})
    selected_field = result.next_question.get("field") if result.next_question else None
    requested_field = decision.get("next_field")
    reason = str(decision.get("audit_reason") or "").strip()
    if result.red_flags:
        labels = "、".join(flag.get("label", "") for flag in result.red_flags if flag.get("label"))
        reason = f"Safety 層偵測到需儘早就醫的警訊：{labels or '安全規則命中'}，因此停止追問。"
    elif result.action == "handoff":
        reason = result.handoff_reason or reason or "流程無法安全繼續，轉交醫療人員。"
    elif requested_field and selected_field != requested_field:
        reason = (
            f"{reason + ' ' if reason else ''}"
            f"規劃器建議 {requested_field}，但流程依必要欄位與"
            f"核准問題庫改選 {selected_field or '結束問診'}。"
        )
    elif not reason:
        reason = {
            "ask": "依目前缺少的必要資訊選擇下一題。",
            "complete": "必要資訊已足夠，結束本次預問診。",
        }.get(result.action, "依目前問診狀態完成流程決策。")

    semantic = (
        {}
        if current_question.get("field") in {"name", "gender", "birth_date", "blood_type"}
        else (result.data or {}).get("_last_semantic_safety") or {}
    )
    trace = {
        "turn": session["turn_count"],
        "question": {
            "field": current_question.get("field", ""),
            "prompt": current_question.get("prompt", ""),
        },
        "answer": answer,
        "result": {
            "extracted_facts": decision.get("extracted_facts", {}),
            "negated_findings": decision.get("negated_findings", []),
            "semantic_safety": semantic.get("extraction"),
            "red_flags": result.red_flags,
            "triage_level": result.triage_level,
            "knowledge_gaps": result.knowledge_gaps,
            "differential_hypotheses": result.differential_hypotheses,
        },
        "decision": {
            "action": result.action,
            "requested_next_field": requested_field,
            "selected_next_field": selected_field,
            "next_question": (result.next_question.get("prompt") if result.next_question else None),
            "needs_retrieval": bool(decision.get("needs_retrieval")),
            "retrieval_query": decision.get("retrieval_query", ""),
            "source": _decision_source(
                field=current_question.get("field", ""),
                decision=decision,
                model_error=result.model_error,
                red_flags=result.red_flags,
            ),
        },
        "reason": reason,
        "model_error": result.model_error,
        "rag_sources": result.rag_sources,
    }
    session.setdefault("transcript", []).append(trace)
    session["data"]["_amie_trace"] = list(session["transcript"])


def append_manual_amie_trace(
    session: dict,
    *,
    current_question: dict,
    answer: str,
    action: str,
    reason: str,
    triage_level: str = "routine",
    red_flags: list[dict] | None = None,
    source: str = "safety_rule",
) -> None:
    trace = {
        "turn": session["turn_count"],
        "question": {
            "field": current_question.get("field", ""),
            "prompt": current_question.get("prompt", ""),
        },
        "answer": answer,
        "result": {
            "extracted_facts": {},
            "negated_findings": [],
            "semantic_safety": (
                session.get("data", {}).get("_chief_assessment", {}).get("extraction")
            ),
            "red_flags": red_flags or [],
            "triage_level": triage_level,
            "knowledge_gaps": session.get("amie_state", {}).get("knowledge_gaps", []),
            "differential_hypotheses": [],
        },
        "decision": {
            "action": action,
            "requested_next_field": None,
            "selected_next_field": None,
            "next_question": None,
            "needs_retrieval": False,
            "retrieval_query": "",
            "source": source,
        },
        "reason": reason,
        "model_error": (
            session.get("data", {}).get("_chief_assessment", {}).get("model_error", "")
        ),
        "rag_sources": [],
    }
    session.setdefault("transcript", []).append(trace)
    session["data"]["_amie_trace"] = list(session["transcript"])
