import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from domain import questionnaire_localization as localization
from domain.questionnaires import build_questionnaire


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class QuestionnaireLocalizationTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_directory.name) / "questionnaire_data"
        self.taigi_dir = self.data_dir / "tai"
        self.data_dir.mkdir()
        self.taigi_dir.mkdir()
        source_path = localization.QUESTIONNAIRE_DATA_DIR / "basic.json"
        self.source = json.loads(source_path.read_text(encoding="utf-8"))
        self.translated = deepcopy(self.source)
        for question in self.translated["questions"]:
            question["prompt"] = f"台語：{question['prompt']}"
            question["options"] = [f"台語：{value}" for value in question.get("options", [])]
            question["quick_options"] = [
                f"台語：{value}" for value in question.get("quick_options", [])
            ]
            question["units"] = [f"台語：{value}" for value in question.get("units", [])]
            if question.get("allow_other"):
                question["other_label"] = "台語：其他"
        self.source_path = self.data_dir / "basic.json"
        self.output_path = self.taigi_dir / "basic.json"
        self.source_path.write_text(
            json.dumps(self.source, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.output_path.write_text(
            json.dumps(self.translated, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.manifest_path = self.taigi_dir / "_translation_manifest.json"
        self._write_manifest()
        self.path_patches = (
            patch.object(localization, "QUESTIONNAIRE_DATA_DIR", self.data_dir),
            patch.object(localization, "TAIGI_DATA_DIR", self.taigi_dir),
            patch.object(localization, "TAIGI_MANIFEST_PATH", self.manifest_path),
        )
        for path_patch in self.path_patches:
            path_patch.start()
        localization.clear_questionnaire_localization_cache()

    def tearDown(self):
        localization.clear_questionnaire_localization_cache()
        for path_patch in reversed(self.path_patches):
            path_patch.stop()
        self.temp_directory.cleanup()

    def _write_manifest(self, *, review_status: str = "clinically_reviewed") -> None:
        self.manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "locale": "nan-TW",
                    "source_locale": "zh-TW",
                    "review_status": review_status,
                    "review": {
                        "reviewer": "合成測試審查者",
                        "reviewed_on": "2026-08-13",
                        "scope": "synthetic localization fixture",
                    },
                    "model": "Bohanlu/Taigi-Llama-2-Translator-7B",
                    "model_revision": "test-revision",
                    "target_language": "HAN",
                    "files": {
                        "basic.json": {
                            "source_sha256": _sha256(self.source_path),
                            "output_sha256": _sha256(self.output_path),
                        }
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def _gender_question(self) -> dict:
        return next(item for item in build_questionnaire("chest") if item["field"] == "gender")

    def test_localizes_display_but_retains_canonical_values(self):
        localized = localization.localize_question(self._gender_question(), "minnan")

        self.assertTrue(localized["prompt"].startswith("台語："))
        self.assertEqual(localized["options"], ["男性", "女性"])
        self.assertEqual(
            localized["option_labels"],
            {"男性": "台語：男性", "女性": "台語：女性"},
        )
        self.assertEqual(
            localization.localize_answer_display(self._gender_question(), "女性", "minnan"),
            "台語：女性",
        )

    def test_unreviewed_machine_translation_fails_closed(self):
        self._write_manifest(review_status="machine_translated_unreviewed")
        localization.clear_questionnaire_localization_cache()

        with self.assertRaisesRegex(
            localization.TaigiQuestionnaireUnavailable,
            "未審核的機器翻譯",
        ):
            localization.validate_taigi_questionnaires(["basic"])

    def test_reviewed_manifest_requires_complete_review_record(self):
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest.pop("review")
        self.manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        localization.clear_questionnaire_localization_cache()

        with self.assertRaisesRegex(
            localization.TaigiQuestionnaireUnavailable,
            "reviewer、reviewed_on、scope",
        ):
            localization.validate_taigi_questionnaires(["basic"])

    def test_reviewed_manifest_rejects_placeholder_review_record(self):
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest["review"] = {
            "reviewer": "審查者姓名或識別碼",
            "reviewed_on": "2026-08-13",
            "scope": "審查範圍與版本",
        }
        self.manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        localization.clear_questionnaire_localization_cache()

        with self.assertRaisesRegex(
            localization.TaigiQuestionnaireUnavailable,
            "占位文字",
        ):
            localization.validate_taigi_questionnaires(["basic"])

    def test_source_or_output_drift_fails_closed(self):
        self.source_path.write_text("{}\n", encoding="utf-8")
        localization.clear_questionnaire_localization_cache()

        with self.assertRaisesRegex(
            localization.TaigiQuestionnaireUnavailable,
            "來源已更新",
        ):
            localization.validate_taigi_questionnaires(["basic"])

    def test_translated_choice_cannot_contain_protocol_separator(self):
        gender = next(
            question for question in self.translated["questions"] if question["field"] == "gender"
        )
        gender["options"][0] = "查埔、男性"
        self.output_path.write_text(
            json.dumps(self.translated, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._write_manifest()
        localization.clear_questionnaire_localization_cache()

        with self.assertRaisesRegex(
            localization.TaigiQuestionnaireUnavailable,
            "保留分隔符",
        ):
            localization.validate_taigi_questionnaires(["basic"])


if __name__ == "__main__":
    unittest.main()
