import copy
import unittest
from unittest.mock import patch

from amie.rule_config import load_safety_rules, validate_safety_rules
from amie.safety import detect_red_flags
from domain.questionnaires import build_questionnaire


class SafetyRuleConfigTests(unittest.TestCase):
    def test_deployed_rule_file_is_valid_and_versioned(self):
        rules = load_safety_rules()

        self.assertEqual(rules["schema_version"], 1)
        self.assertEqual(
            set(rules["route_keywords"]),
            set(rules["supported_routes"]),
        )
        self.assertEqual(
            set(rules["semantic_extraction"]["finding_definitions"]),
            set(rules["finding_codes"]),
        )
        self.assertEqual(rules["raw_rules"]["combinations"], [])
        self.assertGreater(len(rules["structured_rules"]), 10)

    def test_unknown_finding_reference_is_rejected(self):
        rules = copy.deepcopy(load_safety_rules())
        rules["structured_rules"][0]["when"]["any_findings"] = ["not_a_real_finding"]

        with self.assertRaisesRegex(ValueError, "未定義值"):
            validate_safety_rules(rules)

    def test_new_phrase_rule_can_be_added_without_python_change(self):
        rules = copy.deepcopy(load_safety_rules())
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

    def test_questionnaire_semantic_options_reference_known_findings(self):
        rules = load_safety_rules()
        allowed = set(rules["finding_codes"])
        referenced = {
            finding
            for route in rules["supported_routes"]
            for question in build_questionnaire(route)
            for facts in question.get("semantic_options", {}).values()
            for finding in facts.get("findings", [])
        }

        self.assertTrue(referenced)
        self.assertEqual(referenced - allowed, set())


if __name__ == "__main__":
    unittest.main()
