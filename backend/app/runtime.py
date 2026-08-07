"""Process-wide services and configuration shared by application modules."""

from __future__ import annotations

import os
from threading import RLock

from dotenv import load_dotenv

from infrastructure.asr import SpeechTranscriber
from infrastructure.avatar import AvatarClient
from infrastructure.consultation_repository import ConsultationRepository
from infrastructure.llm import LLMClient

load_dotenv()

llm_client = LLMClient()
print(f"[LLM] 使用 {llm_client.provider}（{llm_client.model}）")
asr_service = SpeechTranscriber(llm_client=llm_client)
print(
    "[ASR] 使用 "
    f"{asr_service.status()['provider']}（{asr_service.status()['model']}，延遲載入）"
)
avatar_client = AvatarClient()
print(
    "[Avatar] "
    + ("啟用本地 CosyVoice3 + MuseTalk" if avatar_client.enabled else "未啟用")
)

INTERVIEW_ENGINE = os.getenv("INTERVIEW_ENGINE", "amie").strip().lower()
if INTERVIEW_ENGINE not in {"amie", "legacy"}:
    raise RuntimeError("INTERVIEW_ENGINE 僅支援 amie 或 legacy")
print(f"[Interview] 使用 {INTERVIEW_ENGINE} 問診引擎")

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

URGENT_CARE_MESSAGE = (
    "根據您目前提供的症狀，可能有需要立即處理的危險狀況。"
    "請立刻告知現場醫護人員；若不在醫療院所，請聯絡當地緊急醫療服務。"
)

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
