"""Health and speech-to-text endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from app import runtime
from app.contracts import (
    AvatarSpeechRequest,
    AvatarStatusResponse,
    HealthResponse,
    TranscriptionResponse,
    error_responses,
)
from app.security import current_patient_session, require_patient_session
from app.services.security_audit import audit_patient, safe_log
from infrastructure.asr import ASRUnavailableError, AudioDecodeError
from infrastructure.avatar import AvatarUnavailableError

router = APIRouter(tags=["system"])

WHISPER_PROMPT = "繁體中文醫療問診。請忠實轉錄病人的原話，不要改寫、推測或正規化病人的用詞。"


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Read service health and dependency status",
)
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
        "speech_transcription": runtime.asr_service.status(),
    }


@router.post(
    "/transcribe",
    response_model=TranscriptionResponse,
    responses=error_responses(400, 413, 422, 500, 503),
    summary="Transcribe a Traditional Chinese medical audio recording",
    dependencies=[Depends(require_patient_session)],
)
async def transcribe(audio: UploadFile = File(...)):
    patient_session = current_patient_session()
    if not audio.content_type or "audio" not in audio.content_type:
        if patient_session is not None:
            audit_patient("patient.transcribe", "denied", patient_session)
        raise HTTPException(status_code=400, detail="請上傳音訊檔案")

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=422, detail="錄音內容是空的")
    if len(audio_bytes) > 10 * 1024 * 1024:
        if patient_session is not None:
            audit_patient("patient.transcribe", "denied", patient_session)
        raise HTTPException(
            status_code=413,
            detail="音訊檔案過大（上限 10MB）",
        )

    try:
        transcription = await run_in_threadpool(
            runtime.asr_service.transcribe,
            audio_bytes=audio_bytes,
            filename=audio.filename or "audio.webm",
            mime_type=audio.content_type,
            prompt=WHISPER_PROMPT,
        )
        if patient_session is not None:
            audit_patient("patient.transcribe", "success", patient_session)
        safe_log("patient.transcribe", "success")
        return transcription
    except AudioDecodeError as error:
        if patient_session is not None:
            audit_patient("patient.transcribe", "denied", patient_session)
        safe_log("patient.transcribe", "invalid_audio", error=error)
        raise HTTPException(status_code=422, detail="音訊格式無法辨識") from error
    except ASRUnavailableError as error:
        if patient_session is not None:
            audit_patient("patient.transcribe", "failure", patient_session)
        safe_log("patient.transcribe", "unavailable", error=error)
        raise HTTPException(
            status_code=503,
            detail="語音辨識服務尚未就緒，請稍後再試或改用文字輸入",
        ) from error
    except Exception as error:
        if patient_session is not None:
            audit_patient("patient.transcribe", "failure", patient_session)
        safe_log("patient.transcribe", "failure", error=error)
        raise HTTPException(
            status_code=500,
            detail="語音辨識失敗，請重試或改用文字輸入",
        ) from error


@router.get(
    "/avatar/status",
    response_model=AvatarStatusResponse,
    responses=error_responses(401),
    summary="Check the private local avatar service",
    dependencies=[Depends(require_patient_session)],
)
async def avatar_status():
    return await run_in_threadpool(runtime.avatar_client.status)


@router.post(
    "/avatar/warmup",
    response_model=AvatarStatusResponse,
    responses=error_responses(401, 500, 503),
    summary="Preload local ASR, speech, and talking-head models",
    dependencies=[Depends(require_patient_session)],
)
async def avatar_warmup():
    patient_session = current_patient_session()
    try:
        await run_in_threadpool(runtime.asr_service.warmup)
        status = await run_in_threadpool(runtime.avatar_client.warmup)
        if patient_session is not None:
            audit_patient("patient.avatar.warmup", "success", patient_session)
        safe_log("patient.avatar.warmup", "success")
        return status
    except (ASRUnavailableError, AvatarUnavailableError) as error:
        if patient_session is not None:
            audit_patient("patient.avatar.warmup", "failure", patient_session)
        safe_log("patient.avatar.warmup", "unavailable", error=error)
        raise HTTPException(
            status_code=503,
            detail="Avatar 語音模型預載失敗，請稍後再試",
        ) from error
    except Exception as error:
        if patient_session is not None:
            audit_patient("patient.avatar.warmup", "failure", patient_session)
        safe_log("patient.avatar.warmup", "failure", error=error)
        raise HTTPException(status_code=500, detail="Avatar 模型預載失敗") from error


@router.post(
    "/avatar/speak",
    response_class=Response,
    responses={
        **error_responses(401, 422, 500, 503),
        200: {
            "content": {"video/mp4": {}},
            "description": "Locally generated talking-head MP4 video.",
        },
    },
    summary="Render local CosyVoice3 speech as a MuseTalk avatar video",
    dependencies=[Depends(require_patient_session)],
)
async def avatar_speak(payload: AvatarSpeechRequest):
    patient_session = current_patient_session()
    try:
        video = await run_in_threadpool(
            runtime.avatar_client.render,
            payload.text,
            payload.language,
        )
        if patient_session is not None:
            audit_patient("patient.avatar.speak", "success", patient_session)
        safe_log("patient.avatar.speak", "success")
        return Response(
            content=video.content,
            media_type=video.content_type,
            headers={
                "Cache-Control": "private, no-store",
                "X-Speech-Model": video.speech_model,
                "X-Animation-Model": video.animation_model,
                "X-Avatar-Cache": "hit" if video.cache_hit else "miss",
            },
        )
    except AvatarUnavailableError as error:
        if patient_session is not None:
            audit_patient("patient.avatar.speak", "failure", patient_session)
        safe_log("patient.avatar.speak", "unavailable", error=error)
        raise HTTPException(status_code=503, detail="Avatar 服務目前無法使用") from error
    except Exception as error:
        if patient_session is not None:
            audit_patient("patient.avatar.speak", "failure", patient_session)
        safe_log("patient.avatar.speak", "failure", error=error)
        raise HTTPException(status_code=500, detail="Avatar 影片產生失敗") from error
