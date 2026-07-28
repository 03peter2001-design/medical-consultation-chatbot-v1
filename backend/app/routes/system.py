"""Health and speech-to-text endpoints."""

from __future__ import annotations

import traceback

from fastapi import APIRouter, File, HTTPException, UploadFile

from app import runtime

router = APIRouter()

WHISPER_PROMPT = "繁體中文醫療問診。請忠實轉錄病人的原話，不要改寫、推測或正規化病人的用詞。"


@router.get("/health")
def health():
    current_rag_status = runtime.get_rag_status() if runtime.get_rag_status else runtime.RAG_STATUS
    return {
        "status": "ok",
        "interview_engine": runtime.INTERVIEW_ENGINE,
        "llm_provider": runtime.llm_client.provider,
        "llm_model": runtime.llm_client.model,
        "sessions": len(runtime.sessions),
        "doctor_sessions": len(runtime.doctor_sessions),
        "stored_consultations": runtime.consultation_repository.count(),
        "consultation_database": "sqlite",
        "rag_enabled": current_rag_status["enabled"],
        "rag_index_version": current_rag_status["index_version"],
        "rag_collections": current_rag_status["collections"],
        "rag_legacy_available": current_rag_status["legacy_available"],
        "rag_query_translation": current_rag_status.get(
            "query_translation",
            {
                "enabled": False,
                "provider": "off",
                "query_mode": "dual",
                "model": "",
            },
        ),
    }


@router.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    if not audio.content_type or "audio" not in audio.content_type:
        raise HTTPException(status_code=400, detail="請上傳音訊檔案")

    audio_bytes = await audio.read()
    if len(audio_bytes) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail="音訊檔案過大（上限 10MB）",
        )

    try:
        raw_text = runtime.llm_client.transcribe(
            audio_bytes=audio_bytes,
            filename=audio.filename or "audio.webm",
            mime_type=audio.content_type,
            prompt=WHISPER_PROMPT,
        )
        transcript = str(raw_text or "").strip()
        print(f"[Transcribe:{runtime.llm_client.provider}] 已完成原文轉錄")
        return {"text": transcript}
    except Exception as error:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"語音辨識失敗：{error}",
        ) from error
