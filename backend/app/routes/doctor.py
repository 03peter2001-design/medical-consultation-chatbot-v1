"""Physician consultation browsing and RAG chat endpoints."""

from __future__ import annotations

import time
import traceback

from fastapi import APIRouter, HTTPException, Query

from app import runtime
from app.models import DoctorChatRequest, LoadPatientRequest
from app.prompts.doctor import (
    DOCTOR_SYSTEM_PROMPT,
    STRUCTURED_NOTE_SYSTEM_PROMPT,
    build_structured_note_prompt,
)
from app.services.clinical_summary import (
    clinical_patient_data,
    model_patient_summary,
)
from app.services.rag import (
    deduplicate_sources,
    retrieve_context_block,
)
from domain.terminology_reference import (
    filter_supported_codings,
    terminology_reference,
)

router = APIRouter(prefix="/doctor", tags=["doctor"])


def _cleanup_sessions() -> None:
    now = time.time()
    expired = [
        session_id
        for session_id, session in runtime.doctor_sessions.items()
        if now - session.get("ts", 0) > runtime.DOCTOR_SESSION_TTL
    ]
    for session_id in expired:
        del runtime.doctor_sessions[session_id]


@router.get("/consultations")
def list_consultations(
    search: str = Query(default="", max_length=100),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return runtime.consultation_repository.list_summaries(
        search=search,
        limit=limit,
        offset=offset,
    )


@router.delete("/consultations/{queue_number}")
def delete_consultation(queue_number: str):
    normalized = queue_number.strip()[:16]
    if not normalized:
        raise HTTPException(status_code=400, detail="問診編號不可為空")
    if not runtime.consultation_repository.delete(normalized):
        raise HTTPException(status_code=404, detail="查無此問診編號")

    for session in runtime.doctor_sessions.values():
        patient = session.get("patient")
        if patient and patient.get("queue_number") == normalized:
            session["patient"] = None
            session["history"] = []
    return {"status": "deleted", "queue_number": normalized}


@router.post("/load_patient")
def load_patient(request: LoadPatientRequest):
    record = runtime.consultation_repository.get(request.queue_number)
    if not record:
        raise HTTPException(
            status_code=404,
            detail="查無此問診編號，請確認編號是否正確",
        )

    session = runtime.doctor_sessions.setdefault(
        request.session_id,
        {"history": [], "ts": time.time(), "patient": None},
    )
    session["ts"] = time.time()
    session["patient"] = record
    session["history"] = []

    structured_note = record.get("structured_note")
    structured_sources = list(record.get("structured_sources") or [])
    if structured_note:
        session["history"].append(
            {
                "user": "（系統預先產生）六段式結構化病歷分析",
                "assistant": structured_note,
            }
        )

    patient_data = {
        key: value
        for key, value in (record.get("data") or {}).items()
        if not key.startswith("_") and key != "pain_locations"
    }
    return {
        "queue_number": record["queue_number"],
        "type": record["type"],
        "reason": record["reason"],
        "patient_data": patient_data,
        "clinical_codings": filter_supported_codings(
            record.get("data", {}).get("_clinical_codings", [])
        ),
        "terminology_reference": terminology_reference(),
        "summary": record["summary"],
        "report": record["report"],
        "structured_note": structured_note,
        "structured_sources": structured_sources,
        "pain_locations": record.get("data", {}).get("pain_locations", []),
        "amie_state": record.get("data", {}).get("_amie"),
        "amie_trace": record.get("data", {}).get("_amie_trace", []),
        "chief_assessment": record.get("data", {}).get("_chief_assessment"),
        "triage_level": record.get("triage_level", "routine"),
        "workflow_status": record.get("status", "completed"),
        "summary_error": record.get("summary_error", ""),
        "rag_enabled": runtime.RAG_ENABLED,
    }


@router.delete("/patient/{session_id}")
def unload_patient(session_id: str):
    if session_id in runtime.doctor_sessions:
        runtime.doctor_sessions[session_id]["patient"] = None
        runtime.doctor_sessions[session_id]["history"] = []
    return {"status": "ok"}


@router.post("/chat")
async def doctor_chat(request: DoctorChatRequest):
    _cleanup_sessions()
    if not request.message:
        raise HTTPException(status_code=400, detail="請輸入問題內容")

    session = runtime.doctor_sessions.setdefault(
        request.session_id,
        {"history": [], "ts": time.time(), "patient": None},
    )
    session["ts"] = time.time()
    patient = session.get("patient")

    if not runtime.RAG_ENABLED:
        raise HTTPException(
            status_code=503,
            detail=("RAG 向量庫尚未建立，請先執行 python -m scripts.ingest"),
        )

    base_query = request.message
    if patient:
        base_query = f"{request.message} {patient.get('reason', '')}"

    if request.mode == "structured_note":
        primary_route = patient.get("type") if patient else None
        patient_data = clinical_patient_data(patient.get("data")) if patient else None
        diag_context, diag_sources = retrieve_context_block(
            f"{base_query} 鑑別診斷 危險徵兆 紅旗症狀",
            n_results=5,
            primary_route=primary_route,
            patient_data=patient_data,
            purpose="diagnosis",
        )
        lab_context, lab_sources = retrieve_context_block(
            f"{base_query} 抽血檢驗 實驗室檢查",
            n_results=4,
            primary_route=primary_route,
            patient_data=patient_data,
            purpose="lab",
        )
        imaging_context, imaging_sources = retrieve_context_block(
            f"{base_query} 影像學 X光 電腦斷層 CT MRI 超音波",
            n_results=4,
            primary_route=primary_route,
            patient_data=patient_data,
            purpose="imaging",
        )
        sources = deduplicate_sources(
            diag_sources,
            lab_sources,
            imaging_sources,
        )
    else:
        context_block, sources = retrieve_context_block(
            base_query,
            n_results=6,
            primary_route=patient.get("type") if patient else None,
            patient_data=(clinical_patient_data(patient.get("data")) if patient else None),
            purpose="general",
        )

    patient_block = ""
    if patient:
        patient_block = f"""目前正在討論的病人：

{model_patient_summary(patient)}

【AI初步評估】
{patient["report"]}

---

"""

    if request.mode == "structured_note":
        user_prompt = build_structured_note_prompt(
            request.message,
            patient,
            diag_context,
            lab_context,
            imaging_context,
        )
        messages = [
            {"role": "system", "content": STRUCTURED_NOTE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        max_tokens = 1400
    else:
        messages = [{"role": "system", "content": DOCTOR_SYSTEM_PROMPT}]
        for turn in session["history"][-runtime.DOCTOR_HISTORY_MAX_TURNS :]:
            messages.append({"role": "user", "content": turn["user"]})
            messages.append({"role": "assistant", "content": turn["assistant"]})
        messages.append(
            {
                "role": "user",
                "content": (
                    f"{patient_block}醫學知識庫內容：\n\n"
                    f"{context_block}\n\n---\n\n"
                    f"醫師的問題：{request.message}"
                ),
            }
        )
        max_tokens = 800

    try:
        reply = runtime.llm_client.generate_text(
            messages,
            temperature=0.2,
            max_tokens=max_tokens,
        )
    except Exception as error:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"AI 生成失敗：{error}",
        ) from error

    session["history"].append({"user": request.message, "assistant": reply})
    session["history"] = session["history"][-runtime.DOCTOR_HISTORY_MAX_TURNS :]
    return {
        "reply": reply,
        "session_id": request.session_id,
        "sources": sources,
        "patient_loaded": patient["queue_number"] if patient else None,
        "mode": request.mode,
    }


@router.delete("/session/{session_id}")
def doctor_reset(session_id: str):
    runtime.doctor_sessions.pop(session_id, None)
    return {"status": "ok", "cleared": session_id}
