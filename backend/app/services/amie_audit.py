"""Persistence helpers for concise, clinician-auditable AMIE traces."""

from __future__ import annotations


def interview_length_profile(session: dict) -> dict:
    """Summarise where an interview spent its turns.

    Interview length is dominated by the shared basic/history sections, which are
    identical for every route and are exactly what a record prefill can remove.
    Measuring that split is the only way to tell whether a long interview needs a
    better funnel or better record integration, so it is recorded per session.

    Only field names, section names and counts are kept. No answer, free text or
    clinical value enters this summary.
    """
    prefilled = set(session.get("prefilled_fields") or [])
    answered = {
        str((trace.get("question") or {}).get("field") or "")
        for trace in session.get("transcript") or []
    }
    answered.discard("")

    by_section: dict[str, dict[str, int]] = {}
    for item in session.get("questionnaire") or []:
        field = str(item.get("field") or "")
        # ``reason`` is the chief complaint that opens every interview, so it is
        # never a candidate for prefill or for being skipped.
        if not field or field == "reason":
            continue
        bucket = by_section.setdefault(
            str(item.get("section") or ""),
            {"total": 0, "asked": 0, "prefilled": 0},
        )
        bucket["total"] += 1
        if field in prefilled:
            bucket["prefilled"] += 1
        elif field in answered:
            bucket["asked"] += 1

    total = sum(bucket["total"] for bucket in by_section.values())
    asked = sum(bucket["asked"] for bucket in by_section.values())
    from_record = sum(bucket["prefilled"] for bucket in by_section.values())
    return {
        "turns": int(session.get("turn_count") or 0),
        "questions_total": total,
        "asked": asked,
        "prefilled": from_record,
        # Neither asked nor prefilled: the funnel stopped early or a condition
        # excluded the question.
        "unasked": total - asked - from_record,
        "prefill_coverage": round(from_record / total, 4) if total else 0.0,
        "by_section": by_section,
    }


def _refresh_interview_length(session: dict) -> None:
    """Recompute the profile once the current turn is in the transcript.

    ``save_amie_state`` runs before the trace is appended, and the manual trace
    paths never call it at all, so both append helpers refresh the count instead
    of leaving it one turn behind.
    """
    profile = interview_length_profile(session)
    state = session.get("amie_state")
    if isinstance(state, dict):
        state["interview_length"] = profile
    stored = (session.get("data") or {}).get("_amie")
    if isinstance(stored, dict):
        stored["interview_length"] = profile


def save_amie_state(session: dict, result) -> None:
    state = {
        "triage_level": result.triage_level,
        "decision": result.decision,
        "differential_hypotheses": result.differential_hypotheses,
        "disease_assessment": result.disease_assessment,
        "clinical_facts": result.clinical_facts,
        "knowledge_gaps": result.knowledge_gaps,
        "evidence_timeline": result.evidence_timeline,
        "rag_sources": result.rag_sources,
        "red_flags": result.red_flags,
        "model_error": result.model_error,
        "interview_length": interview_length_profile(session),
    }
    session["amie_state"] = state
    session["data"]["_amie"] = {key: value for key, value in state.items() if key != "model_error"}
    session["data"]["_clinical_facts"] = list(result.clinical_facts or [])
    session["data"]["_disease_assessment"] = dict(result.disease_assessment or {})


def _decision_source(
    *,
    section: str,
    decision: dict,
    model_error: str,
    red_flags: list[dict],
) -> str:
    if red_flags:
        return "safety_rule"
    if model_error:
        return "deterministic_fallback"
    if section == "basic":
        return "deterministic_flow"
    if str(decision.get("audit_reason", "")).startswith("所有適用且核准的問題"):
        return "deterministic_flow"
    if decision.get("scoring_method"):
        return "deterministic_disease_vote"
    return "deterministic_flow"


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
            "disease_assessment": result.disease_assessment,
            "clinical_facts": result.clinical_facts,
        },
        "decision": {
            "action": result.action,
            "requested_next_field": requested_field,
            "selected_next_field": selected_field,
            "next_question": (result.next_question.get("prompt") if result.next_question else None),
            "needs_retrieval": bool(decision.get("needs_retrieval")),
            "retrieval_query": decision.get("retrieval_query", ""),
            "question_utility": decision.get("question_utility", 0),
            "selection_phase": decision.get("selection_phase", ""),
            "selection_tier": decision.get("selection_tier", ""),
            "candidate_frontier": list(decision.get("candidate_frontier", [])),
            "target_fact_codes": list(decision.get("target_fact_codes", [])),
            "funnel_score": dict(decision.get("funnel_score", {})),
            "source": _decision_source(
                section=current_question.get("section", ""),
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
    _refresh_interview_length(session)


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
            "disease_assessment": session.get("data", {}).get(
                "_disease_assessment",
                {},
            ),
            "clinical_facts": session.get("data", {}).get("_clinical_facts", []),
        },
        "decision": {
            "action": action,
            "requested_next_field": None,
            "selected_next_field": None,
            "next_question": None,
            "needs_retrieval": False,
            "retrieval_query": "",
            "question_utility": 0,
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
    _refresh_interview_length(session)
