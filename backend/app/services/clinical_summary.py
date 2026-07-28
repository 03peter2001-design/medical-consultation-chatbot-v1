"""Pure helpers for rendering and de-identifying consultation summaries."""

from __future__ import annotations


def _onset_display(data: dict) -> str:
    return str(
        data.get("onset")
        or " ".join(
            filter(
                None,
                [
                    str(data.get("onset_num", "")).strip(),
                    str(data.get("onset_unit", "")).strip(),
                ],
            )
        )
        or "未填"
    )


def build_summary(data: dict, *, include_identity: bool = True) -> str:
    ctype = data.get("type", "chest")
    default_reason = {
        "chest": "胸痛",
        "headache": "頭痛",
        "abdomen": "腹痛",
    }.get(ctype, "胸痛")
    identity_line = (
        f"- 姓名：{data.get('name', '未提供')}\n- 出生日期：{data.get('birth_date', '未提供')}\n"
        if include_identity
        else ""
    )
    base = f"""患者基本資料：
{identity_line}- 性別：{data.get("gender", "未提供")}
- 年齡：{data.get("age", "未提供")}歲
- 血型：{data.get("blood_type", "未提供")}
- 就診原因：{data.get("reason", default_reason)}
"""

    if ctype == "headache":
        symptom_block = f"""
頭痛問卷：
- 發作時間：{_onset_display(data)}
- 發作方式：{data.get("start_type", "未填")}
- 疼痛位置：{data.get("location", "未填")}
- 是否此生最痛一次：{data.get("worst_ever", "未填")}
- 疼痛性質：{data.get("quality", "未填")}
- 加重因素：{data.get("aggravate", "未填")}
- 緩解因素：{data.get("relieve", "未填")}
- 伴隨症狀：{data.get("associated", "未填")}
- 危險因子（外傷／免疫低下／抗凝血劑／懷孕產後）：{data.get("risk_flags", "未填")}

病史：
- 抽菸：{data.get("smoke", "未填")}
- 神經血管疾病史：{data.get("neuro", "未填")}"""
    elif ctype == "abdomen":
        symptom_block = f"""
腹痛問卷：
- 發作時間：{_onset_display(data)}
- 疼痛性質：{data.get("quality", "未填")}
- 疼痛位置：{data.get("location", "未填")}
- 伴隨症狀：{data.get("associated", "未填")}
- 家人/同行是否有相同症狀：{data.get("contact_history", "未填")}

病史：
- 抽菸：{data.get("smoke", "未填")}
- 腹部相關病史：{data.get("abdomen_hx", "未填")}"""
    else:
        symptom_block = f"""
胸痛問卷：
- 發作時間：{_onset_display(data)}
- 發作方式：{data.get("start_type", "未填")}
- 疼痛位置：{data.get("location", "未填")}
- 痛點型態：{data.get("fixed", "未填")}
- 壓痛：{data.get("tender", "未填")}
- 疼痛性質：{data.get("quality", "未填")}
- 加重因素：{data.get("aggravate", "未填")}
- 緩解因素：{data.get("relieve", "未填")}
- 伴隨症狀：{data.get("associated", "未填")}

病史：
- 抽菸：{data.get("smoke", "未填")}
- 心肺疾病史：{data.get("cardio", "未填")}"""

    tail = f"""
- 慢性疾病：{data.get("chronic", "未填")}{" (" + data["chronic_detail"] + ")" if data.get("chronic_detail") else ""}
- 過去藥物治療：{data.get("past_meds", "未填")}
- 手術史：{data.get("surgery", "未填")}{" (" + data["surgery_detail"] + ")" if data.get("surgery_detail") else ""}
- 目前用藥：{data.get("current_meds", "沒有")}
- 過敏史：{data.get("allergy", "沒有")}
"""
    return (base + symptom_block + tail).strip()


def clinical_patient_data(data: dict | None) -> dict:
    identity_fields = {
        "name",
        "birth_date",
        "national_id",
        "id_number",
        "patient_id",
    }
    return {
        key: value
        for key, value in (data or {}).items()
        if key not in identity_fields and not key.startswith("_")
    }


def model_patient_summary(record: dict) -> str:
    return build_summary(
        clinical_patient_data(record.get("data")),
        include_identity=False,
    )
