"""Background generation of patient and physician consultation reports."""

from __future__ import annotations

import traceback

from app import runtime
from app.prompts.doctor import (
    STRUCTURED_NOTE_SYSTEM_PROMPT,
    build_structured_note_prompt,
)
from app.prompts.report import build_report_prompt
from app.services.clinical_summary import clinical_patient_data
from app.services.consultation_service import (
    process_consultation_summaries,
)
from app.services.rag import deduplicate_sources, retrieve_context_block


def generate_structured_note(
    record: dict,
) -> tuple[str | None, list[dict]]:
    if not runtime.RAG_ENABLED:
        return None, []

    base_query = record.get("reason", "")
    primary_route = record.get("type")
    patient_data = clinical_patient_data(record.get("data"))
    try:
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
        complaint_text = (
            f"病人主訴：{base_query}。詳細問卷內容與AI初步評估"
            "請見上方提供的病人資料，請直接根據該資料進行完整分析。"
        )
        prompt = build_structured_note_prompt(
            complaint_text=complaint_text,
            patient=record,
            diag_context=diag_context,
            lab_context=lab_context,
            imaging_context=imaging_context,
        )
        note = runtime.llm_client.generate_text(
            [
                {
                    "role": "system",
                    "content": STRUCTURED_NOTE_SYSTEM_PROMPT,
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=1400,
        )
        return note, sources
    except Exception as error:
        traceback.print_exc()
        print(f"[Submit] 自動產生結構化病歷失敗: {error}")
        return None, []


def generate_ai_report(record: dict) -> str | None:
    data = record.get("data") or {}
    report = runtime.llm_client.generate_text(
        [
            {
                "role": "system",
                "content": (
                    "你是資深急診醫師。請用繁體中文、自然醫師口吻撰寫"
                    "預問診摘要。初步評估必須引用提供的醫學知識庫內容，"
                    "帶入具體的危險徵兆或診斷標準。絕對不可做正式診斷。"
                ),
            },
            {"role": "user", "content": build_report_prompt(data)},
        ],
        temperature=0.3,
        max_tokens=600,
    )
    normalized = str(report or "").strip()
    if not normalized:
        return None
    if record.get("triage_level") != "urgent":
        return normalized

    safety_report = (
        str(record.get("report") or "")
        .split(
            "\n\n【AI 預問診摘要】",
            1,
        )[0]
        .strip()
    )
    return (f"{safety_report}\n\n【AI 預問診摘要】\n{normalized}").strip()


def process_background_summaries(queue_number: str) -> None:
    try:
        status = process_consultation_summaries(
            runtime.consultation_repository,
            queue_number,
            generate_ai_report,
            generate_structured_note,
            structured_note_expected=runtime.RAG_ENABLED,
        )
        print(f"[Submit] 背景摘要處理完成：{queue_number} ({status})")
    except Exception as error:
        traceback.print_exc()
        runtime.consultation_repository.update_workflow_status(
            queue_number,
            "summary_failed",
            error=f"背景摘要處理失敗：{type(error).__name__}",
        )
        print(f"[Submit] 背景摘要處理失敗：{queue_number}: {error}")
