"""Pure helpers for rendering and de-identifying consultation summaries."""

from __future__ import annotations

from domain.questionnaires import (
    ALL_DISEASE_ROUTES,
    ALL_ROUTE_LABELS,
    load_questionnaire_category,
)


def _route_value(
    data: dict,
    route: str,
    field: str,
    *,
    primary_route: str,
    default: str = "未填",
) -> str:
    key = field if route == primary_route else f"{route}__{field}"
    return str(data.get(key) or default)


def _onset_display(data: dict, route: str, *, primary_route: str) -> str:
    prefix = "" if route == primary_route else f"{route}__"
    return str(
        data.get(f"{prefix}onset")
        or " ".join(
            filter(
                None,
                [
                    str(data.get(f"{prefix}onset_num", "")).strip(),
                    str(data.get(f"{prefix}onset_unit", "")).strip(),
                ],
            )
        )
        or "未填"
    )


def build_summary(data: dict, *, include_identity: bool = True) -> str:
    ctype = data.get("type", "chest")
    routes: list[str] = [
        str(route) for route in data.get("types", [ctype]) if route in ALL_DISEASE_ROUTES
    ]
    primary_route = routes[0] if routes else ""
    default_reason = (
        "、".join(ALL_ROUTE_LABELS.get(route) or route for route in routes) or "其他不適"
    )
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

    symptom_blocks = []
    for route in routes:

        def value(field: str) -> str:
            return _route_value(
                data,
                route,
                field,
                primary_route=primary_route,
            )

        onset = _onset_display(data, route, primary_route=primary_route)
        if route == "headache":
            symptom_blocks.append(f"""
頭痛問卷：
- 發作時間：{onset}
- 發作方式：{value("start_type")}
- 疼痛位置：{value("location")}
- 是否此生最痛一次：{value("worst_ever")}
- 疼痛性質：{value("quality")}
- 加重因素：{value("aggravate")}
- 緩解因素：{value("relieve")}
- 伴隨症狀：{value("associated")}
- 危險因子（外傷／免疫低下／抗凝血劑／懷孕產後）：{value("risk_flags")}
- 神經血管疾病史：{value("neuro")}
- 頭痛相關手術史：{value("surgery")}""")
        elif route == "abdomen":
            symptom_blocks.append(f"""
腹痛問卷：
- 發作時間：{onset}
- 疼痛性質：{value("quality")}
- 疼痛位置：{value("location")}
- 伴隨症狀：{value("associated")}
- 家人/同行是否有相同症狀：{value("contact_history")}
- 腹部相關病史：{value("abdomen_hx")}
- 腹部手術史：{value("surgery")}""")
        elif route == "chest":
            symptom_blocks.append(f"""
胸痛問卷：
- 發作時間：{onset}
- 發作方式：{value("start_type")}
- 疼痛位置：{value("location")}
- 痛點型態：{value("fixed")}
- 壓痛：{value("tender")}
- 疼痛性質：{value("quality")}
- 加重因素：{value("aggravate")}
- 緩解因素：{value("relieve")}
- 伴隨症狀：{value("associated")}
- 心肺疾病史：{value("cardio")}
- 胸痛相關手術史：{value("surgery")}""")
        else:
            answers = []
            for question in load_questionnaire_category(route):
                answer = _route_value(
                    data,
                    route,
                    question["field"],
                    primary_route=primary_route,
                    default="",
                )
                if answer:
                    answers.append(f"- {question['prompt'].rstrip(' *')}：{answer}")
            content = "\n".join(answers) or "- 尚未填寫（入口已轉交醫療人員）"
            symptom_blocks.append(f"\n{ALL_ROUTE_LABELS.get(route, route)}問卷：\n{content}")

    tail = f"""
- 抽菸：{data.get("smoke", "未填")}
- 慢性疾病：{data.get("chronic", "未填")}{" (" + data["chronic_detail"] + ")" if data.get("chronic_detail") else ""}
- 過去藥物治療：{data.get("past_meds", "未填")}
- 目前用藥：{data.get("current_meds", "沒有")}
- 過敏史：{data.get("allergy", "沒有")}
"""
    return (base + "".join(symptom_blocks) + "\n\n一般病史：" + tail).strip()


def build_structured_emr(data: dict) -> str:
    """Render questionnaire answers without adding clinical interpretation."""

    route = str(data.get("type") or "other")
    raw_age = str(data.get("age") or "年齡未提供").strip()
    age = raw_age if raw_age.endswith("歲") or raw_age == "年齡未提供" else f"{raw_age}歲"
    raw_gender = str(data.get("gender") or "").strip()
    gender = {"男": "男性", "男性": "男性", "女": "女性", "女性": "女性"}.get(
        raw_gender,
        raw_gender or "性別未提供",
    )
    reason = str(data.get("reason") or "未提供").strip()
    onset = str(
        data.get("onset")
        or " ".join(
            value
            for value in (
                str(data.get("onset_num") or "").strip(),
                str(data.get("onset_unit") or "").strip(),
            )
            if value
        )
        or "未提供"
    )
    emr_header = f"{age}{gender}｜症狀：{reason}｜持續時間：{onset}"
    history_summary = (
        f"過去病史：{str(data.get('chronic') or '未提供').strip()}；"
        f"目前用藥：{str(data.get('current_meds') or '未提供').strip()}。"
    )
    allergy_summary = f"過敏史：{str(data.get('allergy') or '未提供').strip()}。"
    sections: list[tuple[str, list[str]]] = []

    def answered_lines(category: str) -> list[str]:
        lines = []
        for question in load_questionnaire_category(category):
            field = question["field"]
            if field not in data:
                continue
            value = str(data.get(field) or "").strip()
            if value:
                lines.append(f"- {question['prompt'].rstrip(' *')}：{value}")
        return lines

    basic = answered_lines("basic")
    if data.get("age"):
        basic.append(f"- 年齡（由出生日期計算）：{data['age']}歲")
    sections.append(("基本資料", basic or ["- 未提供"]))
    sections.append(("主訴", [f"- {str(data.get('reason') or '未提供').strip()}"]))
    sections.append(("一般病史", answered_lines("history") or ["- 未提供"]))

    if route in ALL_DISEASE_ROUTES:
        route_answers = answered_lines(route)
        sections.append(
            (
                f"{ALL_ROUTE_LABELS.get(route, route)}問卷",
                route_answers or ["- 未提供"],
            )
        )

    content = "\n\n".join(f"{title}：\n" + "\n".join(lines) for title, lines in sections)
    return (
        f"【病歷摘要 EMR】\n{emr_header}\n{history_summary}{allergy_summary}\n\n"
        f"問卷原始回答：\n{content}\n\n"
        "本紀錄僅整理病人提供或院方預填的問卷資料，不含診斷或臨床推論。"
    )


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
