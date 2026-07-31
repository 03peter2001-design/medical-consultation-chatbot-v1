"""Prompt construction for patient-facing consultation summaries."""

from __future__ import annotations

from app.services.clinical_summary import (
    build_summary,
    clinical_patient_data,
)


def build_report_prompt(data: dict) -> str:
    consultation_type = data.get("type", "chest")
    report_data = clinical_patient_data(data)
    summary = build_summary(report_data, include_identity=False)
    chief_label = {
        "chest": "胸痛",
        "headache": "頭痛",
        "abdomen": "腹痛",
    }.get(consultation_type, "胸痛")

    return f"""
你是醫療預問診的病史整理助手，只能把既有資料整理成摘要。
不得提出疾病名稱、鑑別診斷、患病機率、檢查或治療建議。
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

限制：
- 總長不超過250字
- 只能重述上方已有資料，不得新增任何臨床事實
- 不得輸出「初步評估」「鑑別診斷」或「建議」段落
"""
