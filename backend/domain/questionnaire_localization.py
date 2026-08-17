"""Display-only questionnaire localization backed by generated Taigi assets."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

QUESTIONNAIRE_DATA_DIR = Path(__file__).resolve().parents[1] / "questionnaire_data"
TAIGI_DATA_DIR = QUESTIONNAIRE_DATA_DIR / "tai"
TAIGI_MANIFEST_PATH = TAIGI_DATA_DIR / "_translation_manifest.json"
SUPPORTED_QUESTIONNAIRE_LANGUAGES = frozenset({"mandarin", "minnan"})
_EXPECTED_MODEL = "Bohanlu/Taigi-Llama-2-Translator-7B"
_EXPECTED_TARGET = "HAN"
_DURATION_NUMBER = re.compile(r"^(?P<number>\d+(?:\.\d+)?)(?P<unit>.+)$")
_REVIEW_PLACEHOLDERS = frozenset(
    {
        "審查者姓名或識別碼",
        "審查範圍與版本",
        "reviewer name or identifier",
        "review scope and version",
        "tbd",
        "todo",
    }
)


class TaigiQuestionnaireUnavailable(RuntimeError):
    """Raised when generated Taigi assets cannot be used safely."""


def normalize_questionnaire_language(value: str | None) -> str:
    return value if value in SUPPORTED_QUESTIONNAIRE_LANGUAGES else "mandarin"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _has_complete_review_record(review: Any) -> bool:
    if not isinstance(review, dict):
        return False
    values = {key: review.get(key) for key in ("reviewer", "reviewed_on", "scope")}
    if any(not isinstance(value, str) or not value.strip() for value in values.values()):
        return False
    if any(values[key].strip().casefold() in _REVIEW_PLACEHOLDERS for key in ("reviewer", "scope")):
        return False
    try:
        date.fromisoformat(values["reviewed_on"].strip())
    except ValueError:
        return False
    return True


@lru_cache(maxsize=1)
def _load_manifest() -> dict[str, Any]:
    try:
        manifest = json.loads(TAIGI_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TaigiQuestionnaireUnavailable(
            "尚未產生台語問卷，請先執行 questionnaire_data/translate_to_taigi.py。"
        ) from exc
    review = manifest.get("review") if isinstance(manifest, dict) else None
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or manifest.get("locale") != "nan-TW"
        or manifest.get("source_locale") != "zh-TW"
        or manifest.get("model") != _EXPECTED_MODEL
        or manifest.get("target_language") != _EXPECTED_TARGET
        or not isinstance(manifest.get("files"), dict)
    ):
        raise TaigiQuestionnaireUnavailable("台語問卷 manifest 格式或模型 provenance 不正確。")
    if manifest.get("review_status") != "clinically_reviewed":
        raise TaigiQuestionnaireUnavailable(
            "台語問卷目前只有未審核的機器翻譯；須由合格的台語與臨床人員逐題審查，"
            "並在 manifest 記錄 clinically_reviewed 簽核後才能使用。"
        )
    if not _has_complete_review_record(review):
        raise TaigiQuestionnaireUnavailable(
            "台語問卷 manifest 缺少有效人工審查紀錄：reviewer、reviewed_on、scope；"
            "不可使用空白、占位文字或無效日期。"
        )
    return manifest


def _validated_paths(relative_path: str) -> tuple[Path, Path]:
    manifest_item = _load_manifest()["files"].get(relative_path)
    if not isinstance(manifest_item, dict):
        raise TaigiQuestionnaireUnavailable(f"台語問卷 manifest 缺少 {relative_path}。")
    source_path = QUESTIONNAIRE_DATA_DIR / relative_path
    output_path = TAIGI_DATA_DIR / relative_path
    try:
        source_hash = _sha256(source_path)
        output_hash = _sha256(output_path)
    except OSError as exc:
        raise TaigiQuestionnaireUnavailable(f"台語問卷缺少 {relative_path}。") from exc
    if manifest_item.get("source_sha256") != source_hash:
        raise TaigiQuestionnaireUnavailable(
            f"國語來源已更新，台語問卷需要重新產生：{relative_path}"
        )
    if manifest_item.get("output_sha256") != output_hash:
        raise TaigiQuestionnaireUnavailable(f"台語問卷內容與 manifest 不一致：{relative_path}")
    return source_path, output_path


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TaigiQuestionnaireUnavailable(f"無法讀取{label}：{path.name}") from exc
    if not isinstance(document, dict):
        raise TaigiQuestionnaireUnavailable(f"{label}根節點必須是物件：{path.name}")
    return document


@lru_cache(maxsize=64)
def _paired_questions(category: str) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    relative_path = f"{category}.json"
    source_path, output_path = _validated_paths(relative_path)
    source = _load_json(source_path, label="國語問卷")
    translated = _load_json(output_path, label="台語問卷")
    if source.get("id") != category or translated.get("id") != category:
        raise TaigiQuestionnaireUnavailable(f"台語問卷 id 不一致：{relative_path}")
    source_questions = source.get("questions")
    translated_questions = translated.get("questions")
    if not isinstance(source_questions, list) or not isinstance(translated_questions, list):
        raise TaigiQuestionnaireUnavailable(f"台語問卷缺少 questions：{relative_path}")
    if len(source_questions) != len(translated_questions):
        raise TaigiQuestionnaireUnavailable(f"台語問卷題數不一致：{relative_path}")

    pairs: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for source_question, translated_question in zip(
        source_questions,
        translated_questions,
        strict=True,
    ):
        field = source_question.get("field")
        if (
            not isinstance(field, str)
            or translated_question.get("field") != field
            or translated_question.get("kind") != source_question.get("kind")
            or bool(translated_question.get("multiple")) != bool(source_question.get("multiple"))
            or bool(translated_question.get("allow_other"))
            != bool(source_question.get("allow_other"))
        ):
            raise TaigiQuestionnaireUnavailable(
                f"台語問卷結構不一致：{relative_path}:{field or 'unknown'}"
            )
        for key in ("options", "quick_options", "units"):
            if len(source_question.get(key, [])) != len(translated_question.get(key, [])):
                raise TaigiQuestionnaireUnavailable(
                    f"台語問卷 {key} 數量不一致：{relative_path}:{field}"
                )
            translated_values = translated_question.get(key, [])
            if len(translated_values) != len(set(translated_values)):
                raise TaigiQuestionnaireUnavailable(
                    f"台語問卷 {key} 有重複顯示值：{relative_path}:{field}"
                )
        if any(
            "、" in value or value.startswith("其他：")
            for value in translated_question.get("options", [])
        ):
            raise TaigiQuestionnaireUnavailable(
                f"台語問卷選項含保留分隔符或前綴：{relative_path}:{field}"
            )
        pairs[field] = (source_question, translated_question)
    return pairs


def validate_taigi_questionnaires(categories: Iterable[str]) -> None:
    """Validate every runtime category before a Taigi session is created."""
    for category in categories:
        _paired_questions(category)


def taigi_questionnaire_provenance() -> dict[str, str]:
    manifest = _load_manifest()
    return {
        "locale": manifest["locale"],
        "review_status": manifest["review_status"],
        "model": manifest["model"],
        "model_revision": str(manifest.get("model_revision") or ""),
        "target_language": manifest["target_language"],
        "reviewer": manifest["review"]["reviewer"],
        "reviewed_on": manifest["review"]["reviewed_on"],
    }


def _category_for(item: dict[str, Any]) -> str:
    if item.get("section") == "disease":
        return str(item.get("route") or "")
    return str(item.get("section") or "")


def _label_map(
    source_question: dict[str, Any],
    translated_question: dict[str, Any],
    key: str,
) -> dict[str, str]:
    source_values = source_question.get(key, [])
    translated_values = translated_question.get(key, [])
    return dict(zip(source_values, translated_values, strict=True))


def localize_question(item: dict[str, Any], language: str) -> dict[str, Any]:
    """Return a Taigi display view while retaining canonical answer values."""
    localized = deepcopy(item)
    if language != "minnan":
        return localized
    category = _category_for(item)
    field = str(item.get("base_field") or item.get("field") or "")
    try:
        source, translated = _paired_questions(category)[field]
    except KeyError as exc:
        raise TaigiQuestionnaireUnavailable(f"台語問卷找不到題目：{category}:{field}") from exc

    for key in ("prompt", "placeholder", "other_label"):
        if key in translated:
            localized[key] = translated[key]
    for key, label_key in (
        ("options", "option_labels"),
        ("quick_options", "quick_option_labels"),
        ("units", "unit_labels"),
    ):
        full_mapping = _label_map(source, translated, key)
        canonical_values = localized.get(key, [])
        try:
            localized[label_key] = {value: full_mapping[value] for value in canonical_values}
        except KeyError as exc:
            raise TaigiQuestionnaireUnavailable(
                f"台語問卷顯示值不同步：{category}:{field}:{key}"
            ) from exc
    localized["display_language"] = "minnan"
    return localized


def localize_answer_display(item: dict[str, Any], answer: str, language: str) -> str:
    """Map a canonical structured answer back to the label the patient selected."""
    if language != "minnan" or not answer:
        return answer
    localized = localize_question(item, language)
    if item.get("kind") == "choice":
        labels = localized.get("option_labels", {})
        if answer in labels:
            return labels[answer]
        parts = answer.split("、")
        if parts and all(part in labels for part in parts):
            return "、".join(labels[part] for part in parts)
        return answer
    if item.get("kind") == "duration":
        quick_labels = localized.get("quick_option_labels", {})
        if answer in quick_labels:
            return quick_labels[answer]
        match = _DURATION_NUMBER.fullmatch(answer)
        if match:
            unit_label = localized.get("unit_labels", {}).get(match.group("unit"))
            if unit_label:
                return f"{match.group('number')}{unit_label}"
    return answer


def clear_questionnaire_localization_cache() -> None:
    """Test and generation hook for replacing artifacts in one process."""
    _load_manifest.cache_clear()
    _paired_questions.cache_clear()
