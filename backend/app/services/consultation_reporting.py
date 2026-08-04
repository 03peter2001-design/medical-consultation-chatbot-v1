"""Background generation of patient and physician consultation reports."""

from __future__ import annotations

import json
import re
import traceback
from typing import cast

from amie.clinical_facts import facts_from_legacy_data
from amie.disease_profiles import (
    attach_profile_codings,
    attach_safety_conditions,
    score_diseases,
)
from app import runtime
from app.prompts.report import build_report_prompt
from app.services.clinical_summary import clinical_patient_data, model_patient_summary
from app.services.consultation_service import (
    process_consultation_summaries,
)
from app.services.rag import deduplicate_sources, retrieve_context_block
from domain.questionnaires import (
    DISEASE_ROUTES,
    load_questionnaire_policy,
)

_DISEASE_LIKE_TERM = re.compile(
    r"[\u4e00-\u9fff]{1,12}"
    r"(?:癌|腫瘤|發炎|心肌梗塞|梗塞|栓塞|剝離|氣胸|"
    r"心律不整|症候群|缺血|出血|中風)"
)
_DIAGNOSTIC_LANGUAGE = re.compile(r"診斷|鑑別|疑似|可能(?:是|為|罹患)|考慮(?:為|是)?|符合.+疾病")


def _contains_unapproved_disease_language(
    text: str,
    *,
    allowed_names: set[str] | None = None,
    source_text: str = "",
) -> bool:
    candidate = str(text or "")
    if _DIAGNOSTIC_LANGUAGE.search(candidate):
        return True
    allowed_names = allowed_names or set()
    for match in _DISEASE_LIKE_TERM.finditer(candidate):
        term = match.group(0)
        if term in source_text or any(name in term or term in name for name in allowed_names):
            continue
        return True
    return False


def _validated_history_summary(record: dict, candidate: object) -> str:
    source = model_patient_summary(record)
    summary = str(candidate or "").strip()[:1200]
    if not summary or _contains_unapproved_disease_language(
        summary,
        source_text=source,
    ):
        return source
    return summary


def _single_paragraph(text: object) -> str:
    """Collapse model formatting so the physician report stays scan-friendly."""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _truncate_summary_part(text: str, limit: int) -> str:
    """Keep generated prose compact and prefer ending at a sentence boundary."""
    if len(text) <= limit:
        return text
    window = text[: limit + 1]
    boundary = max(window.rfind(mark) for mark in "。；！？")
    if boundary >= limit // 2:
        return window[: boundary + 1]
    return f"{text[: limit - 1].rstrip('，、； ')}…"


def _brief_evidence(value: object) -> str:
    return _truncate_summary_part(_single_paragraph(value), 36)


def _supported_condition_summaries(assessment: dict) -> list[tuple[str, list[str]]]:
    """Return at most three fixed-table conditions with verbatim evidence."""
    result: list[tuple[str, list[str]]] = []
    seen: set[str] = set()

    def already_seen(name: str) -> bool:
        return any(name in existing or existing in name for existing in seen)

    for item in assessment.get("safety_triggered_conditions", []):
        name = str(item.get("name") or "").strip()
        if not name or already_seen(name):
            continue
        evidence = list(
            dict.fromkeys(
                _brief_evidence(trigger.get("evidence") or trigger.get("rule_label") or "")
                for trigger in item.get("triggered_by", [])
                if _single_paragraph(trigger.get("evidence") or trigger.get("rule_label") or "")
            )
        )
        result.append((name, evidence[:1]))
        seen.add(name)
        if len(result) == 3:
            return result

    for item in assessment.get("top", []):
        name = str(item.get("name") or "").strip()
        if (
            not name
            or already_seen(name)
            or int(item.get("support_votes") or 0) <= 0
            or int(item.get("net_votes") or 0) <= 0
        ):
            continue
        evidence = list(
            dict.fromkeys(
                _brief_evidence(clue.get("evidence") or "")
                for clue in item.get("supporting", [])
                if _single_paragraph(clue.get("evidence") or "")
            )
        )
        if not evidence:
            continue
        result.append((name, evidence[:1]))
        seen.add(name)
        if len(result) == 3:
            break
    return result


def _render_physician_quick_summary(
    record: dict,
    candidate: object,
    assessment: dict,
) -> str:
    """Combine Gemini's history prose with deterministic differential evidence."""
    history = _truncate_summary_part(
        _single_paragraph(_validated_history_summary(record, candidate)),
        220,
    )
    conditions = _supported_condition_summaries(assessment)
    if conditions:
        rendered_conditions = "；".join(
            f"{name}（依據：{'、'.join(evidence)}）" for name, evidence in conditions
        )
        differential = f"可能疾病包括{rendered_conditions}。"
    else:
        differential = "目前資料不足，尚無具支持線索的可能疾病可供排序。"
    return (
        f"{history.rstrip('。；，, ')}。{differential}"
        "以上為固定疾病表的線索相容結果，並非正式診斷。"
    )


def _assessment_for_record(record: dict) -> dict:
    data = record.get("data") or {}
    assessment = dict(
        data.get("_disease_assessment") or (data.get("_amie") or {}).get("disease_assessment") or {}
    )
    route = record.get("type")
    uses_disease_vote = (
        route in DISEASE_ROUTES
        and load_questionnaire_policy(route)["selection_strategy"] == "disease_vote"
    )
    red_flags = list((data.get("_amie") or {}).get("red_flags") or [])
    if red_flags and not assessment.get("safety_triggered_conditions"):
        assessment = attach_safety_conditions(
            str(route or ""),
            red_flags,
            facts=facts_from_legacy_data(data),
            computed_from="legacy_recalculation",
            assessment=assessment or None,
        )
    elif uses_disease_vote and not assessment:
        assessment = score_diseases(
            facts_from_legacy_data(data),
            route=str(route),
            computed_from="legacy_recalculation",
        )
    return attach_profile_codings(str(route or ""), assessment)


def _render_vote_assessment(assessment: dict) -> str:
    if not assessment or assessment.get("status") == "unavailable":
        return "【規則式鑑別投票】\n疾病表目前無法使用，請由醫療人員依原始問診資料判斷。"
    safety_conditions = assessment.get("safety_triggered_conditions", [])
    top = assessment.get("top", [])
    lines = []
    if safety_conditions:
        lines.append("【Safety 規則觸發的鑑別方向】")
        for index, item in enumerate(safety_conditions, start=1):
            triggers = "；".join(
                "、".join(
                    value
                    for value in (
                        trigger.get("rule_label", ""),
                        trigger.get("evidence", ""),
                    )
                    if value
                )
                for trigger in item.get("triggered_by", [])
            )
            lines.append(f"{index}. {item['name']}{f'（{triggers}）' if triggers else ''}")
        lines.append("以上來自固定 Safety 規則，不代表疾病票數、患病機率或正式診斷。")
    if not top and not safety_conditions:
        return "【規則式鑑別投票】\n目前沒有取得足夠的支持線索，無法建立鑑別排名。"
    if top:
        if lines:
            lines.append("")
        lines.append("【規則式鑑別投票】")
        for index, item in enumerate(top, start=1):
            evidence = "、".join(
                clue.get("evidence", "")
                for clue in item.get("supporting", [])
                if clue.get("evidence")
            )
            lines.append(
                f"{index}. {item['name']}：淨票 {item['net_votes']}，"
                f"資料完整度 {round(item['coverage'] * 100)}%"
                f"{f'；支持線索：{evidence}' if evidence else ''}"
            )
        lines.append("以上為固定疾病表的線索相容排序，不是患病機率或正式診斷。")
    return "\n".join(lines)


def _parse_json_object(text: str) -> dict:
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        str(text or "").strip(),
        flags=re.IGNORECASE,
    ).strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("結構化建議必須是 JSON 物件")
    return payload


def _validated_workup_items(
    payload: dict,
    key: str,
    allowed_ids: set[str],
    allowed_names: set[str] | None = None,
) -> list[dict[str, object]]:
    items = payload.get(key)
    if not isinstance(items, list):
        return []
    result = []
    for raw in items[:8]:
        if not isinstance(raw, dict) or set(raw) - {
            "item",
            "rationale",
            "linked_condition_ids",
        }:
            continue
        item = str(raw.get("item", "")).strip()[:160]
        rationale = str(raw.get("rationale", "")).strip()[:300]
        linked = raw.get("linked_condition_ids")
        if (
            not item
            or not rationale
            or not isinstance(linked, list)
            or not linked
            or any(condition_id not in allowed_ids for condition_id in linked)
            or _contains_unapproved_disease_language(
                f"{item} {rationale}",
                allowed_names=allowed_names,
            )
        ):
            continue
        result.append(
            {
                "item": item,
                "rationale": rationale,
                "linked_condition_ids": list(dict.fromkeys(linked)),
            }
        )
    return result


def _render_structured_note(
    record: dict,
    assessment: dict,
    payload: dict,
) -> str:
    ranked = assessment.get("ranked", [])
    names = {item["id"]: item["name"] for item in ranked}
    top = assessment.get("top", [])
    must_not_miss = assessment.get("must_not_miss", [])

    def disease_lines(items: list[dict], limit: int) -> str:
        selected = items[:limit]
        if not selected:
            return "目前資料不足，無法由固定疾病表建立排序。"
        return "\n".join(
            f"{index}. {item['name']}（淨票 {item['net_votes']}；"
            f"完整度 {round(item['coverage'] * 100)}%）"
            for index, item in enumerate(selected, start=1)
        )

    def workup_lines(key: str) -> str:
        items = _validated_workup_items(
            payload,
            key,
            set(names),
            set(names.values()),
        )
        if not items:
            return "此段建議請依臨床判斷。"
        return "\n".join(
            f"- {item['item']}：{item['rationale']}（對應："
            + "、".join(
                names[condition_id]
                for condition_id in cast(list[str], item["linked_condition_ids"])
            )
            + "）"
            for item in items
        )

    summary = _validated_history_summary(
        record,
        payload.get("emr_summary", ""),
    )
    return f"""【病歷摘要 EMR】
{summary}

【初步鑑別診斷（前3項最可能）】
{disease_lines(top, 3)}

【防漏診鑑別 — 5個絕對不能漏掉的隱形殺手】
{disease_lines(must_not_miss, 5)}

【理學檢查建議】
{workup_lines("physical_exam")}

【檢驗建議（抽血／驗尿）】
{workup_lines("laboratory")}

【影像學決策】
{workup_lines("imaging")}

固定疾病表投票僅供臨床決策參考，不是患病機率或正式診斷。"""


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
        assessment = _assessment_for_record(record)
        allowed = [
            {"id": item["id"], "name": item["name"]} for item in assessment.get("ranked", [])
        ]
        prompt = f"""
你只能整理病史，並針對固定疾病 ID 提出理學檢查、檢驗與影像項目。
不得新增疾病、不得修改疾病排名、不得輸出患病機率。

病人資料：
{model_patient_summary(record)}

允許引用的固定疾病：
{json.dumps(allowed, ensure_ascii=False)}

鑑別與危險徵兆文獻：
{diag_context}

檢驗文獻：
{lab_context}

影像文獻：
{imaging_context}

只回傳 JSON：
{{
  "emr_summary": "只重述既有病史的摘要",
  "physical_exam": [
    {{
      "item": "檢查名稱",
      "rationale": "依文獻的簡短理由",
      "linked_condition_ids": ["只能使用允許的ID"]
    }}
  ],
  "laboratory": [],
  "imaging": []
}}
""".strip()
        response = runtime.llm_client.generate_text(
            [
                {
                    "role": "system",
                    "content": (
                        "你是受限的臨床工作檢查建議抽取器。只能輸出指定 JSON，"
                        "疾病只能用使用者提供的 ID 引用，不得生成疾病候選。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=1400,
        )
        payload = _parse_json_object(response)
        note = _render_structured_note(record, assessment, payload)
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
                    "你是協助醫師快速掌握病況的醫療預問診病史整理助手。"
                    "只能重述既有資料；疾病與理由由後端固定規則補入，"
                    "你不得自行提出疾病、鑑別診斷、檢查或治療建議。"
                ),
            },
            {"role": "user", "content": build_report_prompt(data)},
        ],
        temperature=0.3,
        max_tokens=500,
    )
    assessment = _assessment_for_record(record)
    normalized = _render_physician_quick_summary(record, report, assessment)
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
    return (f"{safety_report}\n\n【醫師速覽摘要】\n{normalized}").strip()


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
