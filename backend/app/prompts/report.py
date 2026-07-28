"""Prompt construction for patient-facing consultation summaries."""

from __future__ import annotations

from app import runtime
from app.services.clinical_summary import (
    build_summary,
    clinical_patient_data,
)
from app.services.rag import retrieve_context_block


def build_report_prompt(data: dict) -> str:
    consultation_type = data.get("type", "chest")
    report_data = clinical_patient_data(data)
    summary = build_summary(report_data, include_identity=False)
    chief_label = {
        "chest": "胸痛",
        "headache": "頭痛",
        "abdomen": "腹痛",
    }.get(consultation_type, "胸痛")

    rag_context = ""
    danger_context = ""
    if runtime.RAG_ENABLED:
        try:
            rag_context = runtime.build_context(
                report_data,
                consultation_type,
            )
            print(f"[RAG] build_context 撈到 {len(rag_context)} 字的內容")
        except Exception as error:
            print(f"[RAG] build_context 查詢失敗: {error}")

        try:
            danger_query = (
                f"{data.get('reason', '')} {data.get('associated', '')} 危險徵兆 紅旗症狀 鑑別診斷"
            ).strip()
            danger_context, _ = retrieve_context_block(
                danger_query,
                n_results=4,
                primary_route=consultation_type,
                patient_data=report_data,
                purpose="diagnosis",
            )
            print("[RAG] 已完成補充危險徵兆檢索")
        except Exception as error:
            print(f"[RAG] 補充危險徵兆檢索失敗: {error}")

    context_parts = []
    if rag_context:
        context_parts.append(rag_context)
    if danger_context and danger_context != "（知識庫中查無相關內容）":
        context_parts.append(
            f"【針對本次主訴與伴隨症狀額外檢索的危險徵兆／鑑別診斷內容】\n{danger_context}"
        )
    context_block = ""
    if context_parts:
        combined = "\n\n".join(context_parts)
        context_block = f"""
以下是從 Medscape 醫學文獻庫（Emergency Medicine / Infectious Diseases / Laboratory Medicine）擷取的相關醫學知識，請務必參考並引用於評估中；若有多段內容，請優先引用跟本次主訴、伴隨症狀最相關的部分：

{combined}

---
"""

    return f"""
你是一位資深急診醫師，正在審閱預問診資料並撰寫臨床評估摘要。
請用繁體中文、真實醫師的口吻回答。絕對不可做正式診斷。

{context_block}
以下是病患的預問診資料：

{summary}

請輸出以下格式的評估摘要：

【基本資料】
性別／年齡

【主訴】
{chief_label}發作狀況（時間、位置、性質）

【伴隨症狀】
列出重要伴隨症狀

【過去病史】
慢性病、手術、用藥史

【初步評估】
請直接引用上方醫學知識庫中的相關內容，說明需要特別注意的鑑別診斷方向（2～3句）。
若知識庫有提到具體的危險徵兆或診斷標準，請明確帶入，不要只說通用知識。

【建議】
一句話建議（是否需要立即就醫或可觀察）

限制：
- 總長不超過350字
- 語氣像真人醫生，不過度正式
- 初步評估必須引用 RAG 知識庫的具體內容
- 絕對不做正式診斷
"""
