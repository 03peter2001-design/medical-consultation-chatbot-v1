"""Process-wide services and configuration shared by application modules."""

from __future__ import annotations

import os
from threading import RLock

from dotenv import load_dotenv

from domain.patient_messages import patient_message
from infrastructure.asr import SpeechTranscriber
from infrastructure.avatar import AvatarClient
from infrastructure.consultation_repository import ConsultationRepository
from infrastructure.llm import LLMClient

load_dotenv()

llm_client = LLMClient()
print(f"[LLM] 使用 {llm_client.provider}（{llm_client.model}）")
asr_service = SpeechTranscriber(llm_client=llm_client)
print(f"[ASR] 使用 {asr_service.status()['provider']}（{asr_service.status()['model']}，延遲載入）")
avatar_client = AvatarClient()
if not avatar_client.enabled:
    avatar_runtime_label = "未啟用"
elif avatar_client.animation_enabled:
    avatar_runtime_label = "啟用本地 CosyVoice3 + MuseTalk"
else:
    avatar_runtime_label = "啟用本地 CosyVoice3 靜態醫師模式"
print(f"[Avatar] {avatar_runtime_label}")


def _normalize_interview_engine(value: str) -> str:
    configured = value.strip().lower()
    aliases = {"legacy": "questionnaire", "simple": "questionnaire"}
    normalized = aliases.get(configured, configured)
    if normalized not in {"amie", "questionnaire"}:
        raise RuntimeError("INTERVIEW_ENGINE 僅支援 questionnaire（legacy／simple 別名）或 amie")
    return normalized


INTERVIEW_ENGINE = _normalize_interview_engine(os.getenv("INTERVIEW_ENGINE", "questionnaire"))
print(f"[Interview] 使用 {INTERVIEW_ENGINE} 問診引擎")

_gemini_summary_client: LLMClient | None = None


def get_gemini_summary_client() -> LLMClient:
    """Return the Gemini client used after a fixed questionnaire is complete."""

    global _gemini_summary_client
    if _gemini_summary_client is None:
        env = dict(os.environ)
        env["LLM_PROVIDER"] = "gemini"
        _gemini_summary_client = LLMClient(env)
    return _gemini_summary_client


AMIE_DEBUG_TRACE = os.getenv("AMIE_DEBUG_TRACE", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

sessions: dict[str, dict] = {}
# Patient interview memory is only a cache.  Its lifetime must not be shorter
# than the authenticated patient session persisted in SQLite, otherwise an
# otherwise-valid cookie loses the in-progress interview after 30 minutes.
SESSION_TTL = 8 * 60 * 60
# A browser-provided session id is not an authorization boundary.  Physician
# sessions are therefore namespaced by the verified UCC tenant and clinician.
# Route code must always construct this key from the authenticated JWT
# principal; never from identity fields supplied by the client.
DoctorSessionKey = tuple[str, str, str]
doctor_sessions: dict[DoctorSessionKey, dict] = {}
doctor_sessions_lock = RLock()
DOCTOR_SESSION_TTL = 60 * 60
DOCTOR_HISTORY_MAX_TURNS = 8

URGENT_CARE_MESSAGE = patient_message("safety.urgent_care")

consultation_repository = ConsultationRepository.from_environment()

RAG_ENABLED = False
RAG_STATUS = {
    "enabled": False,
    "index_version": "unavailable",
    "collections": [],
    "legacy_available": False,
}
try:
    from knowledge.retrieval import (
        build_context,
        get_rag_status,
        retrieve,
    )

    RAG_STATUS = get_rag_status()
    RAG_ENABLED = RAG_STATUS["enabled"]
    if RAG_ENABLED:
        print(
            "[RAG] 向量庫已啟用："
            f"version={RAG_STATUS['index_version']} "
            f"collections={RAG_STATUS['collections']}"
        )
    else:
        print(f"[RAG] 找不到完整的作用中索引：{RAG_STATUS}")
except Exception as error:
    print(f"[RAG] 初始化失敗，RAG 停用：{error}")
    build_context = None
    get_rag_status = None
    retrieve = None
