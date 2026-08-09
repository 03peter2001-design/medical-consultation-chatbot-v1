import copy
import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from amie import rule_config
from amie.rule_config import load_safety_rules, validate_safety_rules
from amie.safety import detect_red_flags
from domain.questionnaires import build_questionnaire


def _observe_rule_refresh(path, start_event, changed_event, result_queue):
    with patch.object(rule_config, "SAFETY_RULES_PATH", path):
        load_safety_rules.cache_clear()
        start_event.wait(timeout=5)
        result_queue.put(load_safety_rules()["version"])
        changed_event.wait(timeout=5)
        result_queue.put(load_safety_rules()["version"])


class SafetyRuleConfigTests(unittest.TestCase):
    def test_deployed_rule_file_is_valid_and_versioned(self):
        rules = load_safety_rules()

        self.assertEqual(rules["schema_version"], 2)
        self.assertEqual(
            set(rules["route_keywords"]),
            set(rules["supported_routes"]),
        )
        self.assertEqual(
            set(rules["semantic_extraction"]["finding_definitions"]),
            set(rules["finding_codes"]),
        )
        self.assertIn(
            "acute_monocular_visual_change_combination",
            {rule["code"] for rule in rules["raw_rules"]["combinations"]},
        )
        self.assertGreater(len(rules["structured_rules"]), 10)
        self.assertEqual(rules["safety_fact_codes"], [])
        self.assertIn(
            "急性冠心症（含心肌梗塞）",
            rules["urgent_condition_candidates"]["胸部不適合併冒冷汗"],
        )

    def test_unknown_finding_reference_is_rejected(self):
        rules = copy.deepcopy(load_safety_rules())
        rules["structured_rules"][0]["when"]["any_findings"] = ["not_a_real_finding"]

        with self.assertRaisesRegex(ValueError, "未定義值"):
            validate_safety_rules(rules)

    def test_new_phrase_rule_can_be_added_without_python_change(self):
        rules = copy.deepcopy(load_safety_rules())
        rules["urgent_condition_candidates"]["由 JSON 加入的測試規則"] = ["測試用緊急疾病"]
        rules["raw_rules"]["universal"].append(
            {
                "code": "configured_test_rule",
                "label": "由 JSON 加入的測試規則",
                "level": "urgent",
                "terms": ["測試專用觸發語句"],
            }
        )
        validate_safety_rules(rules)

        with patch("amie.safety.load_safety_rules", return_value=rules):
            flags = detect_red_flags(
                None,
                "這是測試專用觸發語句",
                {},
            )

        self.assertEqual(flags[0]["code"], "configured_test_rule")
        self.assertEqual(
            flags[0]["possible_conditions"],
            ("測試用緊急疾病",),
        )

    def test_every_urgent_rule_requires_condition_candidates(self):
        rules = copy.deepcopy(load_safety_rules())
        del rules["urgent_condition_candidates"]["意識狀態異常"]

        with self.assertRaisesRegex(ValueError, "缺少安全規則標籤"):
            validate_safety_rules(rules)

    def test_clinical_fact_and_mandatory_disease_rules_are_validated_from_json(
        self,
    ):
        rules = copy.deepcopy(load_safety_rules())
        rules["clinical_fact_rules"]["legacy_terms"]["model_invented_fact"] = ["測試"]
        with self.assertRaisesRegex(ValueError, "未知 fact"):
            validate_safety_rules(rules)

        rules = copy.deepcopy(load_safety_rules())
        rules["disease_profile_rules"]["chest"]["required_must_not_miss_profiles"][
            "invented_profile"
        ] = ["不存在的 Safety 疾病"]
        with self.assertRaisesRegex(
            ValueError,
            "未對應 urgent_condition_candidates",
        ):
            validate_safety_rules(rules)

    def test_onset_definitions_are_required_for_fact_label_governance(self):
        rules = copy.deepcopy(load_safety_rules())
        del rules["semantic_extraction"]["onset_definitions"]["sudden"]
        with self.assertRaisesRegex(ValueError, "onset_definitions"):
            validate_safety_rules(rules)

    def test_direct_safety_facts_must_use_known_clinical_fact_codes(self):
        rules = copy.deepcopy(load_safety_rules())
        rules["safety_fact_codes"] = ["severity_severe"]
        validate_safety_rules(rules)

        rules["safety_fact_codes"] = ["not_a_clinical_fact"]
        with self.assertRaisesRegex(ValueError, "safety_fact_codes"):
            validate_safety_rules(rules)

    def test_questionnaire_semantic_options_reference_known_findings(self):
        rules = load_safety_rules()
        allowed = set(rules["finding_codes"])
        referenced = {
            finding
            for route in rules["supported_routes"]
            for question in build_questionnaire(route)
            for facts in question.get("semantic_options", {}).values()
            for key in (
                "findings",
                "negated_findings",
                "resolution_facts",
            )
            for finding in facts.get(key, [])
        }

        self.assertTrue(referenced)
        self.assertEqual(referenced - allowed, set())

    def test_each_worker_observes_an_atomic_rule_file_replacement(self):
        context = multiprocessing.get_context("spawn")
        current = copy.deepcopy(load_safety_rules())
        current["version"] = "worker-refresh-before"
        updated = copy.deepcopy(current)
        updated["version"] = "worker-refresh-after"

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "safety_rules.json"
            path.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
            start_event = context.Event()
            changed_event = context.Event()
            result_queue = context.Queue()
            with patch.object(rule_config, "SAFETY_RULES_PATH", path):
                load_safety_rules.cache_clear()
                workers = [
                    context.Process(
                        target=_observe_rule_refresh,
                        args=(path, start_event, changed_event, result_queue),
                    )
                    for _ in range(2)
                ]
                for worker in workers:
                    worker.start()
                start_event.set()
                self.assertEqual(
                    sorted(result_queue.get(timeout=5) for _ in workers),
                    ["worker-refresh-before"] * 2,
                )
                replacement = path.with_suffix(".next")
                replacement.write_text(json.dumps(updated, ensure_ascii=False), encoding="utf-8")
                replacement.replace(path)
                changed_event.set()
                self.assertEqual(
                    sorted(result_queue.get(timeout=5) for _ in workers),
                    ["worker-refresh-after"] * 2,
                )
                for worker in workers:
                    worker.join(timeout=5)
                self.assertEqual([worker.exitcode for worker in workers], [0, 0])
                load_safety_rules.cache_clear()


if __name__ == "__main__":
    unittest.main()
