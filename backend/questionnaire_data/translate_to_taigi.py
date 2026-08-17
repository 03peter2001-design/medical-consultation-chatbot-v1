#!/usr/bin/env python3
"""Translate questionnaire JSON display text to Taigi Hanzi with Taigi-Llama-2.

The source files are never edited. Translated copies and their provenance are
written below ``questionnaire_data/tai`` while identifiers and clinical logic
remain unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

MODEL_ID = "Bohanlu/Taigi-Llama-2-Translator-7B"
MODEL_REVISION = "784ecc27f53659d710c13cdaec651ade2b65799f"
MODEL_LICENSE = "CC-BY-NC-SA-4.0"
TARGET_LANGUAGE = "HAN"
PROMPT_TEMPLATE = "[TRANS]\n{source_sentence}\n[/TRANS]\n[HAN]\n"

DATA_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = DATA_DIR / "tai"
MANIFEST_NAME = "_translation_manifest.json"
CACHE_NAME = ".translation-cache.json"
QUESTION_SCALAR_FIELDS = ("prompt", "placeholder", "other_label")
QUESTION_LIST_FIELDS = ("options", "exclusive_options", "quick_options", "units")
DEFAULT_OTHER_LABEL = "其他／補充說明"
PLACEHOLDER_PATTERN = re.compile(r"(\{[A-Za-z_][A-Za-z0-9_]*\})")


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _source_paths() -> list[Path]:
    paths = sorted(DATA_DIR.glob("*.json"))
    patient_messages = DATA_DIR / "ui" / "patient_messages.json"
    if patient_messages.is_file():
        paths.append(patient_messages)
    return paths


def _relative(path: Path) -> str:
    return path.relative_to(DATA_DIR).as_posix()


def _literal_segments(value: str) -> list[str]:
    """Return non-placeholder chunks so format fields remain byte-for-byte stable."""
    return [part for part in PLACEHOLDER_PATTERN.split(value) if part and not part.startswith("{")]


def _question_strings(question: dict[str, Any]) -> list[str]:
    strings = [str(question[key]) for key in QUESTION_SCALAR_FIELDS if question.get(key)]
    strings.extend(
        str(value) for key in QUESTION_LIST_FIELDS for value in question.get(key, []) if value
    )
    condition = question.get("condition") or {}
    strings.extend(str(value) for value in condition.get("contains_any", []) if value)
    for option, condition in (question.get("option_conditions") or {}).items():
        strings.append(str(option))
        strings.extend(str(value) for value in condition.get("exclude_equals_any", []) if value)
    strings.extend(str(option) for option in (question.get("semantic_options") or {}))
    if question.get("allow_other") and not question.get("other_label"):
        strings.append(DEFAULT_OTHER_LABEL)
    return strings


def collect_strings(documents: dict[str, dict[str, Any]]) -> list[str]:
    strings: list[str] = []
    for relative_path, document in documents.items():
        if relative_path == "ui/patient_messages.json":
            for message in document.get("messages", {}).values():
                strings.extend(_literal_segments(str(message)))
            continue
        if document.get("label"):
            strings.append(str(document["label"]))
        for question in document.get("questions", []):
            strings.extend(_question_strings(question))
    return list(dict.fromkeys(value for value in strings if value.strip()))


def _translated_template(value: str, translations: dict[str, str]) -> str:
    parts = PLACEHOLDER_PATTERN.split(value)
    return "".join(
        part if PLACEHOLDER_PATTERN.fullmatch(part) else translations.get(part, part)
        for part in parts
    )


def _translated_mapping_keys(
    mapping: dict[str, Any],
    translations: dict[str, str],
    *,
    context: str,
) -> dict[str, Any]:
    translated: dict[str, Any] = {}
    for key, value in mapping.items():
        translated_key = translations.get(key, key)
        if translated_key in translated:
            raise ValueError(f"翻譯後 key 碰撞：{context}.{translated_key}")
        translated[translated_key] = value
    return translated


def _validate_translated_question(question: dict[str, Any], *, context: str) -> None:
    for key in QUESTION_LIST_FIELDS:
        values = question.get(key, [])
        if len(values) != len(set(values)):
            raise ValueError(f"翻譯後出現重複值：{context}.{key}")
    options = set(question.get("options", []))
    if not set(question.get("exclusive_options", [])).issubset(options):
        raise ValueError(f"翻譯後 exclusive_options 不在 options：{context}")
    if not set((question.get("semantic_options") or {})).issubset(options):
        raise ValueError(f"翻譯後 semantic_options key 不在 options：{context}")
    if not set((question.get("option_conditions") or {})).issubset(options):
        raise ValueError(f"翻譯後 option_conditions key 不在 options：{context}")


def translate_questionnaire_document(
    document: dict[str, Any],
    translations: dict[str, str],
    *,
    relative_path: str,
) -> dict[str, Any]:
    output = deepcopy(document)
    if output.get("label"):
        output["label"] = translations[str(output["label"])]
    for question in output.get("questions", []):
        field = str(question.get("field", ""))
        for key in QUESTION_SCALAR_FIELDS:
            if question.get(key):
                question[key] = translations[str(question[key])]
        if question.get("allow_other") and not question.get("other_label"):
            question["other_label"] = translations[DEFAULT_OTHER_LABEL]
        for key in QUESTION_LIST_FIELDS:
            question[key] = [translations[str(value)] for value in question.get(key, [])]

        condition = question.get("condition")
        if condition:
            condition["contains_any"] = [
                translations[str(value)] for value in condition.get("contains_any", [])
            ]

        option_conditions = question.get("option_conditions") or {}
        translated_conditions: dict[str, Any] = {}
        for option, option_condition in option_conditions.items():
            translated_option = translations[str(option)]
            if translated_option in translated_conditions:
                raise ValueError(f"翻譯後 option_conditions key 碰撞：{relative_path}:{field}")
            translated_condition = deepcopy(option_condition)
            translated_condition["exclude_equals_any"] = [
                translations[str(value)] for value in option_condition.get("exclude_equals_any", [])
            ]
            translated_conditions[translated_option] = translated_condition
        question["option_conditions"] = translated_conditions

        question["semantic_options"] = _translated_mapping_keys(
            question.get("semantic_options") or {},
            translations,
            context=f"{relative_path}:{field}.semantic_options",
        )
        _validate_translated_question(question, context=f"{relative_path}:{field}")
    return output


def translate_patient_messages(
    document: dict[str, Any],
    translations: dict[str, str],
) -> dict[str, Any]:
    output = deepcopy(document)
    output["locale"] = "nan-TW"
    output["messages"] = {
        key: _translated_template(str(value), translations)
        for key, value in output.get("messages", {}).items()
    }
    for key, source in document.get("messages", {}).items():
        source_fields = PLACEHOLDER_PATTERN.findall(str(source))
        output_fields = PLACEHOLDER_PATTERN.findall(output["messages"][key])
        if source_fields != output_fields:
            raise ValueError(f"patient_messages placeholder 改變：{key}")
    return output


def build_outputs(
    documents: dict[str, dict[str, Any]],
    translations: dict[str, str],
) -> dict[str, dict[str, Any]]:
    return {
        relative_path: (
            translate_patient_messages(document, translations)
            if relative_path == "ui/patient_messages.json"
            else translate_questionnaire_document(
                document,
                translations,
                relative_path=relative_path,
            )
        )
        for relative_path, document in documents.items()
    }


def _load_cache(path: Path, *, force: bool) -> dict[str, str]:
    if force or not path.is_file():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    if (
        document.get("model") != MODEL_ID
        or document.get("model_revision") != MODEL_REVISION
        or document.get("target_language") != TARGET_LANGUAGE
    ):
        return {}
    translations = document.get("translations")
    return translations if isinstance(translations, dict) else {}


def _write_cache(path: Path, translations: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "model": MODEL_ID,
                "model_revision": MODEL_REVISION,
                "target_language": TARGET_LANGUAGE,
                "translations": translations,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


class TaigiTranslator:
    def __init__(self, *, device: str, dtype: str) -> None:
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "需要 torch、transformers、accelerate 與 sentencepiece；"
                "請在隔離的生成環境安裝後重試。"
            ) from exc

        self.torch = torch
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(
                MODEL_ID,
                revision=MODEL_REVISION,
                use_fast=False,
            )
        except ImportError as exc:
            raise RuntimeError("缺少 sentencepiece，請先安裝 sentencepiece。") from exc
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        self.tokenizer.padding_side = "left"

        resolved_device = device
        if device == "auto":
            resolved_device = "cuda" if torch.cuda.is_available() else "cpu"
        resolved_dtype = dtype
        if dtype == "auto":
            resolved_dtype = "float16" if resolved_device == "cuda" else "bfloat16"
        dtype_value = getattr(torch, resolved_dtype)
        self.model = AutoModelForCausalLM.from_pretrained(
            MODEL_ID,
            revision=MODEL_REVISION,
            torch_dtype=dtype_value,
            device_map={"": resolved_device},
            low_cpu_mem_usage=True,
        )
        self.model.eval()
        self.input_device = next(self.model.parameters()).device

    def translate_batch(self, sources: list[str], *, max_new_tokens: int) -> list[str]:
        prompts = [PROMPT_TEMPLATE.format(source_sentence=source) for source in sources]
        encoded = self.tokenizer(prompts, return_tensors="pt", padding=True)
        encoded = {key: value.to(self.input_device) for key, value in encoded.items()}
        terminators = [
            token_id
            for token_id in (self.tokenizer.eos_token_id, self.tokenizer.pad_token_id)
            if token_id is not None
        ]
        with self.torch.inference_mode():
            output = self.model.generate(
                **encoded,
                do_sample=False,
                repetition_penalty=1.1,
                max_new_tokens=max_new_tokens,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=list(dict.fromkeys(terminators)),
            )
        generated = output[:, encoded["input_ids"].shape[1] :]
        results: list[str] = []
        for source, token_ids in zip(sources, generated, strict=True):
            value = self.tokenizer.decode(token_ids, skip_special_tokens=True)
            value = value.split("[/", 1)[0].strip()
            if not value:
                raise RuntimeError(f"模型沒有產生翻譯：{source}")
            results.append(value)
        return results


def _load_documents(paths: list[Path]) -> dict[str, dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        relative_path = _relative(path)
        if relative_path == "ui/patient_messages.json":
            if not isinstance(document.get("messages"), dict):
                raise ValueError(f"{relative_path} 缺少 messages")
        elif not isinstance(document.get("questions"), list):
            raise ValueError(f"{relative_path} 缺少 questions")
        documents[relative_path] = document
    return documents


def _write_outputs(
    output_dir: Path,
    outputs: dict[str, dict[str, Any]],
    source_paths: list[Path],
) -> None:
    output_hashes: dict[str, str] = {}
    for relative_path, document in outputs.items():
        output_path = output_dir / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        output_path.write_text(content, encoding="utf-8")
        output_hashes[relative_path] = _sha256_bytes(content.encode("utf-8"))

    manifest = {
        "schema_version": 1,
        "locale": "nan-TW",
        "source_locale": "zh-TW",
        "review_status": "machine_translated_unreviewed",
        "model": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "model_license": MODEL_LICENSE,
        "target_language": TARGET_LANGUAGE,
        "prompt_template": PROMPT_TEMPLATE,
        "generation": {"do_sample": False, "repetition_penalty": 1.1},
        "generated_on": date.today().isoformat(),
        "notice": "機器翻譯不得視為台語或臨床內容簽核；正式使用前須由合格人員審查。",
        "files": {
            _relative(path): {
                "source_sha256": _sha256_file(path),
                "output_sha256": output_hashes[_relative(path)],
            }
            for path in source_paths
        },
    }
    (output_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def check_outputs(output_dir: Path, source_paths: list[Path]) -> int:
    manifest_path = output_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        print(f"找不到翻譯 manifest：{manifest_path}")
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    for source_path in source_paths:
        relative_path = _relative(source_path)
        item = manifest.get("files", {}).get(relative_path, {})
        output_path = output_dir / relative_path
        if item.get("source_sha256") != _sha256_file(source_path):
            failures.append(f"來源已變更：{relative_path}")
        if not output_path.is_file() or item.get("output_sha256") != _sha256_file(output_path):
            failures.append(f"輸出缺少或已變更：{relative_path}")
    if failures:
        print("\n".join(failures))
        return 1
    print(f"台語問卷輸出完整，共 {len(source_paths)} 份 JSON：{output_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--max-new-tokens", type=int, default=192)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument(
        "--dtype",
        choices=("auto", "float32", "bfloat16", "float16"),
        default="auto",
    )
    parser.add_argument("--force", action="store_true", help="忽略翻譯 cache，全部重跑")
    parser.add_argument("--dry-run", action="store_true", help="只驗證與統計，不載入模型")
    parser.add_argument("--check", action="store_true", help="驗證既有輸出與來源 hash")
    args = parser.parse_args()

    source_paths = _source_paths()
    documents = _load_documents(source_paths)
    strings = collect_strings(documents)
    output_dir = args.output_dir.resolve()
    if args.check:
        return check_outputs(output_dir, source_paths)

    cache_path = output_dir / CACHE_NAME
    translations = _load_cache(cache_path, force=args.force)
    pending = [value for value in strings if value not in translations]
    print(
        f"來源 {len(source_paths)} 份 JSON；不重複文字 {len(strings)} 段；"
        f"已快取 {len(strings) - len(pending)} 段；待翻譯 {len(pending)} 段。"
    )
    if args.dry_run:
        return 0

    if pending:
        translator = TaigiTranslator(device=args.device, dtype=args.dtype)
        batch_size = max(1, args.batch_size)
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            generated = translator.translate_batch(
                batch,
                max_new_tokens=max(16, args.max_new_tokens),
            )
            translations.update(zip(batch, generated, strict=True))
            _write_cache(cache_path, translations)
            print(f"已翻譯 {min(start + batch_size, len(pending))}/{len(pending)}")

    outputs = build_outputs(documents, translations)
    _write_outputs(output_dir, outputs, source_paths)
    print(f"完成：{len(outputs)} 份台語 JSON 已寫入 {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
