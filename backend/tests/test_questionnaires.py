import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from domain.questionnaires import (
    ALL_DISEASE_ROUTES,
    CANDIDATE_DISEASE_ROUTES,
    CHIEF_QUESTIONNAIRE,
    DISEASE_QUESTIONNAIRES,
    DISEASE_ROUTES,
    QUESTIONNAIRE_DATA_DIR,
    ROUTE_DISPOSITIONS,
    ROUTE_KEYWORDS,
    ROUTE_LABELS,
    build_questionnaire,
    filter_question_by_context,
    load_questionnaire_category,
    load_questionnaire_policy,
    next_question_index,
    parse_birth_date,
    parse_onset_answer,
    questionnaire_disposition,
)
from scripts.export_questionnaire_frontend import export_payload, selected_targets
from scripts.promote_questionnaires import DRAFT_DIR, prepare_promotions, validate_signoff_manifest


class QuestionnaireDefinitionTests(unittest.TestCase):
    def test_questionnaire_content_is_split_into_category_json_files(self):
        expected = {"chief", "basic", "history", *ALL_DISEASE_ROUTES}
        actual = {path.stem for path in QUESTIONNAIRE_DATA_DIR.glob("*.json")}
        self.assertEqual(actual, expected)
        for category in expected:
            document = json.loads(
                (QUESTIONNAIRE_DATA_DIR / f"{category}.json").read_text(encoding="utf-8")
            )
            self.assertEqual(document["id"], category)
            self.assertTrue(document["questions"])

    def test_category_loader_is_cached_and_rejects_unknown_category(self):
        first = load_questionnaire_category("chest")
        second = load_questionnaire_category("chest")
        self.assertIs(first, second)
        with self.assertRaisesRegex(ValueError, "不支援"):
            load_questionnaire_category("unknown")

    def test_flow_is_chief_then_basic_history_and_disease(self):
        questionnaire = build_questionnaire("abdomen")
        sections = [item["section"] for item in questionnaire]
        first_basic = sections.index("basic")
        first_history = sections.index("history")
        first_disease = sections.index("disease")

        self.assertEqual(questionnaire[0]["field"], "reason")
        self.assertLess(first_basic, first_history)
        self.assertLess(first_history, first_disease)

    def test_each_supported_route_has_a_disease_questionnaire(self):
        self.assertEqual(
            set(DISEASE_QUESTIONNAIRES),
            set(DISEASE_ROUTES),
        )
        self.assertEqual(set(DISEASE_ROUTES), {"chest", "headache", "abdomen"})
        for route in DISEASE_QUESTIONNAIRES:
            questionnaire = build_questionnaire(route)
            self.assertTrue(any(item["section"] == "disease" for item in questionnaire))
            self.assertTrue(ROUTE_LABELS[route])
            self.assertTrue(ROUTE_KEYWORDS[route])
            self.assertIn(ROUTE_DISPOSITIONS[route], {"questionnaire", "handoff", "urgent"})

    def test_provisional_routes_remain_validated_candidates_but_not_runtime_routes(self):
        self.assertEqual(len(CANDIDATE_DISEASE_ROUTES), 49)
        for route in CANDIDATE_DISEASE_ROUTES:
            document = json.loads(
                (QUESTIONNAIRE_DATA_DIR / f"{route}.json").read_text(encoding="utf-8")
            )
            self.assertEqual(document["review_status"], "source_structured_provisional")
            self.assertEqual(document["policy"]["selection_strategy"], "fixed_order")
            self.assertEqual(
                document["provenance"]["pipeline_version"], "questionnaire-structure-v2"
            )
            self.assertNotIn("source_lines", json.dumps(document, ensure_ascii=False))
            self.assertTrue(load_questionnaire_category(route))
            self.assertNotIn(route, ROUTE_KEYWORDS)
            self.assertNotIn(route, ROUTE_LABELS)
            self.assertNotIn(route, ROUTE_DISPOSITIONS)

        with self.assertRaisesRegex(ValueError, "不支援"):
            build_questionnaire("fever")
        with self.assertRaisesRegex(ValueError, "不支援"):
            questionnaire_disposition("stroke")

    def test_route_selection_and_completion_rules_come_from_json_policy(self):
        chest = load_questionnaire_policy("chest")
        headache = load_questionnaire_policy("headache")
        abdomen = load_questionnaire_policy("abdomen")

        self.assertEqual(chest["schema_version"], 2)
        self.assertEqual(chest["selection_strategy"], "disease_vote")
        self.assertEqual(chest["coverage_threshold"], 0.7)
        self.assertEqual(chest["max_turns"], 24)
        self.assertEqual(chest["frontier_vote_margin"], 2)
        self.assertEqual(chest["frontier_max_candidates"], 5)
        self.assertEqual(chest["priority_fields"][0], "start_type")
        self.assertIn("severity", chest["required_fields"])
        self.assertEqual(headache["selection_strategy"], "disease_vote")
        self.assertEqual(headache["coverage_threshold"], 0.7)
        self.assertEqual(headache["frontier_vote_margin"], 2)
        self.assertEqual(headache["frontier_max_candidates"], 5)
        self.assertEqual(headache["priority_fields"][0], "start_type")
        self.assertEqual(abdomen["selection_strategy"], "disease_vote")
        self.assertEqual(abdomen["coverage_threshold"], 0.7)
        self.assertEqual(abdomen["frontier_vote_margin"], 2)
        self.assertEqual(abdomen["frontier_max_candidates"], 5)
        self.assertIn("severity", abdomen["required_fields"])

    def test_multiple_symptom_routes_share_demographics_but_keep_answers_separate(self):
        questionnaire = build_questionnaire(["headache", "abdomen"])
        fields = [item["field"] for item in questionnaire]
        disease = [item for item in questionnaire if item["section"] == "disease"]

        self.assertEqual(fields.count("name"), 1)
        self.assertEqual(len(fields), len(set(fields)))
        self.assertEqual(
            [item["route"] for item in disease if item["base_field"] == "onset"],
            ["headache", "abdomen"],
        )
        self.assertIn("onset", fields)
        self.assertIn("abdomen__onset", fields)
        self.assertIn("abdomen__location", fields)

    def test_selectable_basic_fields_are_structured(self):
        questionnaire = build_questionnaire("chest")
        by_field = {item["field"]: item for item in questionnaire}
        self.assertEqual(by_field["gender"]["kind"], "choice")
        self.assertEqual(by_field["birth_date"]["kind"], "date")
        self.assertEqual(by_field["blood_type"]["kind"], "choice")

    def test_optional_chronic_detail_is_skipped(self):
        questionnaire = build_questionnaire("headache")
        chronic_index = next(
            index for index, item in enumerate(questionnaire) if item["field"] == "chronic"
        )
        next_index = next_question_index(
            questionnaire,
            chronic_index,
            {"chronic": "以上皆無"},
        )
        self.assertEqual(questionnaire[next_index]["field"], "past_meds")

    def test_fhir_prefilled_basic_fields_are_skipped(self):
        questionnaire = build_questionnaire("abdomen")
        next_index = next_question_index(
            questionnaire,
            0,
            {},
            skip_fields={
                "name",
                "gender",
                "birth_date",
                "blood_type",
            },
        )
        self.assertEqual(questionnaire[next_index]["field"], "smoke")

    def test_headache_neuro_and_surgery_prefill_skips_both_questions(self):
        questionnaire = build_questionnaire("headache")
        risk_index = next(
            index for index, item in enumerate(questionnaire) if item["field"] == "risk_flags"
        )
        self.assertIsNone(
            next_question_index(
                questionnaire,
                risk_index,
                {},
                skip_fields={"neuro", "surgery"},
            )
        )

    def test_initial_questionnaire_only_asks_for_chief_complaint(self):
        self.assertEqual(len(CHIEF_QUESTIONNAIRE), 1)
        self.assertEqual(CHIEF_QUESTIONNAIRE[0]["kind"], "text")

    def test_male_context_removes_female_specific_options(self):
        abdomen = {item["field"]: item for item in build_questionnaire("abdomen")}
        associated = filter_question_by_context(
            abdomen["associated"],
            {"gender": "男性"},
        )
        surgery = filter_question_by_context(
            abdomen["surgery"],
            {"gender": "男性"},
        )
        headache_risk = next(
            item for item in build_questionnaire("headache") if item["field"] == "risk_flags"
        )
        headache_risk = filter_question_by_context(
            headache_risk,
            {"gender": "男性"},
        )

        self.assertTrue(
            {
                "月經過期",
                "陰道出血",
                "陰道分泌物增加",
            }.isdisjoint(associated["options"])
        )
        self.assertNotIn("剖腹產", surgery["options"])
        self.assertNotIn("子宮切除", surgery["options"])
        self.assertNotIn("懷孕或產後六週內", headache_risk["options"])
        self.assertTrue(
            {
                "missed_period",
                "vaginal_bleeding",
                "vaginal_discharge",
            }.isdisjoint(associated["semantic_options"]["以上皆無"]["negated_findings"])
        )
        self.assertNotIn(
            "pregnancy_postpartum",
            headache_risk["semantic_options"]["以上皆無"]["negated_findings"],
        )
        self.assertEqual(
            surgery["semantic_options"]["未曾手術"]["negated_findings"],
            ["prior_abdominal_surgery"],
        )

    def test_female_or_unknown_context_keeps_female_specific_options(self):
        associated = next(
            item for item in build_questionnaire("abdomen") if item["field"] == "associated"
        )

        for data in (
            {"gender": "女性"},
            {"gender": "其他"},
            {"gender": "不便透露"},
            {},
        ):
            filtered = filter_question_by_context(associated, data)
            self.assertIn("月經過期", filtered["options"])
            self.assertIn("陰道出血", filtered["options"])
        self.assertIn("陰道分泌物增加", filtered["options"])


class QuestionnaireGovernanceToolTests(unittest.TestCase):
    @staticmethod
    def _draft() -> dict:
        return {
            "id": "candidate",
            "generation": {"source_sha256": "route-sha"},
            "review_notes": [
                {
                    "severity": "warning",
                    "note": "需由臨床人員確認",
                    "source_ids": ["source-1"],
                }
            ],
        }

    @staticmethod
    def _signoff() -> dict:
        return {
            "schema_version": 1,
            "reviewer": {"name": "合成測試審查者", "role": "clinical reviewer"},
            "reviewed_on": "2026-08-09",
            "source_sha256": "manifest-sha",
            "route_catalog_sha256": "catalog-sha",
            "routes": {
                "candidate": {
                    "approved": True,
                    "source_sha256": "route-sha",
                    "review_notes": [],
                }
            },
        }

    def test_promotion_refuses_to_run_without_a_signoff_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "clinical_signoff.json"
            with self.assertRaisesRegex(RuntimeError, "找不到必要檔案"):
                prepare_promotions(DRAFT_DIR, missing)

    def test_signoff_requires_every_warning_or_critical_note_to_be_resolved(self):
        signoff = self._signoff()
        with self.assertRaisesRegex(ValueError, "尚有未處理"):
            validate_signoff_manifest(
                signoff,
                {"candidate": self._draft()},
                {"source": {"sha256": "manifest-sha"}},
                "catalog-sha",
            )

        signoff["routes"]["candidate"]["review_notes"] = [
            {
                "note_index": 0,
                "resolution": "mitigated",
                "rationale": "合成測試中已加入安全轉交",
            }
        ]
        validated = validate_signoff_manifest(
            signoff,
            {"candidate": self._draft()},
            {"source": {"sha256": "manifest-sha"}},
            "catalog-sha",
        )
        self.assertEqual(
            validated["routes"]["candidate"]["review_notes"][0]["resolution"],
            "mitigated",
        )

    def test_export_defaults_to_development_frontend_and_check_never_writes(self):
        default_targets = selected_targets(include_frontend_v2=False)
        production_targets = selected_targets(include_frontend_v2=True)
        self.assertEqual(len(default_targets), 1)
        self.assertNotIn("frontend-v2", str(default_targets[0]))
        self.assertEqual(len(production_targets), 2)
        self.assertIn("frontend-v2", str(production_targets[1]))

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "questionnaireRoutes.js"
            target.write_text("old", encoding="utf-8")
            self.assertFalse(export_payload("new", (target,), check=True))
            self.assertEqual(target.read_text(encoding="utf-8"), "old")
            self.assertTrue(export_payload("new", (target,), check=False))
            self.assertEqual(target.read_text(encoding="utf-8"), "new")


class QuestionnaireParserTests(unittest.TestCase):
    def test_birth_date_derives_age(self):
        self.assertEqual(
            parse_birth_date("1990-08-01", today=date(2026, 7, 27)),
            ("1990-08-01", 35),
        )

    def test_future_birth_date_is_rejected(self):
        self.assertIsNone(parse_birth_date("2027-01-01", today=date(2026, 7, 27)))

    def test_onset_preserves_months(self):
        self.assertEqual(
            parse_onset_answer("一個月以前"),
            ("1", "個月前"),
        )
        self.assertEqual(parse_onset_answer("1個月以前"), ("1", "個月前"))

    def test_onset_does_not_default_to_hours(self):
        self.assertIsNone(parse_onset_answer("有一陣子了"))


if __name__ == "__main__":
    unittest.main()
