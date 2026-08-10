"""Prompt construction for the physician quick-view history summary."""

from __future__ import annotations

from app.services.clinical_summary import (
    build_summary,
    clinical_patient_data,
)
from domain.questionnaires import ALL_ROUTE_LABELS


def build_report_prompt(data: dict) -> str:
    consultation_type = data.get("type", "other")
    report_data = clinical_patient_data(data)
    summary = build_summary(report_data, include_identity=False)
    chief_label = ALL_ROUTE_LABELS.get(consultation_type, "其他不適")

    return f"""
你是醫療預問診的病史整理助手，只能把既有資料整理成摘要。
不得提出疾病名稱、鑑別診斷、患病機率、檢查或治療建議。
以下是病患的預問診資料：

{summary}

請將資料整理成一段供醫師快速閱讀的病史摘要，依序交代：
性別與年齡、{chief_label}主訴、發作或事件經過、已回答的重要問卷資訊，
以及與判斷有關的既往病史、用藥和過敏史。

限制：
- 使用繁體中文，語氣專業、簡單、直接
- 只輸出一個自然段落，不要標題、條列、Markdown 或前言
- 以160至220字為目標；資料不足時寧可簡短，不得補寫
- 只能重述上方已有資料，不得新增任何臨床事實
- 這一段不要提出疾病、鑑別診斷、患病機率、檢查或治療建議；
  可能疾病與理由會由系統依固定疾病表另外接在同一段文字後方，
  組成總長約300字的醫師速覽摘要
"""
