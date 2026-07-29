import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from amie.rule_config import load_safety_rules, read_safety_rules
from app.services import rule_management


class _TemporaryRuleLoader:
    def __init__(self, path: Path):
        self.path = path

    def __call__(self):
        return read_safety_rules(self.path)

    def cache_clear(self):
        return None


class _FakeRuleAssistant:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def generate_text(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return json.dumps(self.payload, ensure_ascii=False)


class RuleManagementTests(unittest.TestCase):
    def test_rule_center_describes_all_routes_and_safety_rules(self):
        payload = rule_management.rule_center_payload()

        self.assertEqual(
            {item["route"] for item in payload["routes"]},
            {"chest", "headache", "abdomen"},
        )
        self.assertEqual(len(payload["revision"]), 64)
        self.assertEqual([item["step"] for item in payload["flow"]], [1, 2, 3, 4])
        self.assertTrue(payload["safety_groups"])
        self.assertTrue(all(group["rules"] for group in payload["safety_groups"]))
        self.assertTrue(all(group["categories"] for group in payload["safety_groups"]))
        self.assertEqual(len(payload["fact_catalog"]), payload["fact_count"])
        catalog = {item["code"]: item for item in payload["fact_catalog"]}
        self.assertEqual(set(catalog), set(payload["fact_codes"]))
        self.assertIn(
            "safety",
            catalog["altered_consciousness"]["categories"],
        )
        self.assertIn("chest", catalog["chest_pressure"]["categories"])
        self.assertTrue(all(item["description"] for item in payload["fact_catalog"]))

    def test_editor_must_unlock_with_matching_token(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(PermissionError, "尚未設定"):
                rule_management.authorize_rule_editor("secret")

        with patch.dict(
            os.environ,
            {"SAFETY_RULE_ADMIN_TOKEN": "correct-secret"},
            clear=False,
        ):
            with self.assertRaisesRegex(PermissionError, "權杖不正確"):
                rule_management.authorize_rule_editor("wrong")
            self.assertEqual(
                rule_management.authorize_rule_editor("correct-secret"),
                {"authorized": True},
            )

    def test_edit_cannot_add_remove_or_reclassify_rules(self):
        current = load_safety_rules()
        groups = rule_management._rule_groups(current)

        missing_rule = copy.deepcopy(groups)
        missing_rule[0]["rules"].pop()
        with self.assertRaisesRegex(ValueError, "code 不可新增、刪除或變更"):
            rule_management._candidate_document(current, missing_rule)

        changed_scope = copy.deepcopy(groups)
        changed_scope[0]["rules"][0]["scope"] = "route"
        with self.assertRaisesRegex(ValueError, "是唯讀欄位"):
            rule_management._candidate_document(current, changed_scope)

    def test_edit_updates_json_label_terms_and_condition_candidates(self):
        current = load_safety_rules()
        groups = rule_management._rule_groups(current)
        edited = copy.deepcopy(groups)
        edited[0]["label"] = "醫師校訂安全標籤"
        edited[0]["possible_conditions"] = ["醫師校訂鑑別方向"]
        phrase_rule = next(
            rule for group in edited for rule in group["rules"] if rule["kind"] == "phrase"
        )
        phrase_rule["terms"] = ["醫師校訂觸發詞"]

        candidate = rule_management._candidate_document(current, edited)

        all_rules = [
            *candidate["raw_rules"]["universal"],
            *(rule for rules in candidate["raw_rules"]["routes"].values() for rule in rules),
            *candidate["raw_rules"]["combinations"],
            *candidate["structured_rules"],
        ]
        self.assertEqual(
            candidate["urgent_condition_candidates"]["醫師校訂安全標籤"],
            ["醫師校訂鑑別方向"],
        )
        self.assertEqual(
            next(rule for rule in all_rules if rule["code"] == phrase_rule["code"])["terms"],
            ["醫師校訂觸發詞"],
        )

    def test_structured_rule_features_can_be_selected_from_catalog(self):
        current = load_safety_rules()
        groups = rule_management._rule_groups(current)
        edited = copy.deepcopy(groups)
        structured = next(
            rule
            for group in edited
            for rule in group["rules"]
            if rule["code"] == "semantic_altered_consciousness"
        )
        structured["when"] = {
            "all_findings": [
                "altered_consciousness",
                "syncope",
            ]
        }

        candidate = rule_management._candidate_document(current, edited)
        saved = next(
            rule
            for rule in candidate["structured_rules"]
            if rule["code"] == "semantic_altered_consciousness"
        )

        self.assertEqual(
            saved["when"],
            structured["when"],
        )

    def test_update_requires_configured_matching_token_and_current_revision(self):
        current = load_safety_rules()
        groups = rule_management._rule_groups(current)
        revision = rule_management._revision(current)
        common = {
            "expected_revision": revision,
            "confirmation": "更新安全規則",
            "change_note": "測試安全規則更新",
            "actor_session_id": "test-session",
            "groups": groups,
        }

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(PermissionError, "尚未設定"):
                rule_management.update_safety_rules(admin_token="secret", **common)

        with patch.dict(
            os.environ,
            {"SAFETY_RULE_ADMIN_TOKEN": "correct-secret"},
            clear=False,
        ):
            with self.assertRaisesRegex(PermissionError, "權杖不正確"):
                rule_management.update_safety_rules(admin_token="wrong", **common)
            with self.assertRaisesRegex(RuntimeError, "其他人更新"):
                rule_management.update_safety_rules(
                    admin_token="correct-secret",
                    **{**common, "expected_revision": "0" * 64},
                )

    def test_assistant_returns_validated_unsaved_selected_draft(self):
        current = load_safety_rules()
        groups = rule_management._rule_groups(current)
        selected = copy.deepcopy(groups[0])
        selected["label"] = f"{selected['label']}（助理草稿）"
        assistant = _FakeRuleAssistant(
            {
                "reply": "已依要求調整標籤。",
                "safety_groups": [selected],
            }
        )

        result = rule_management.suggest_safety_rule_edits(
            llm_client=assistant,
            message="在標籤後加上助理草稿",
            selected_labels=[groups[0]["original_label"]],
            groups=groups,
            history=[],
        )

        suggested = next(
            group
            for group in result["safety_groups"]
            if group["original_label"] == groups[0]["original_label"]
        )
        self.assertFalse(result["saved"])
        self.assertEqual(suggested["label"], selected["label"])
        self.assertEqual(
            load_safety_rules()["urgent_condition_candidates"],
            current["urgent_condition_candidates"],
        )
        self.assertEqual(len(assistant.calls), 1)

    def test_assistant_cannot_modify_unselected_group(self):
        current = load_safety_rules()
        groups = rule_management._rule_groups(current)
        assistant = _FakeRuleAssistant(
            {
                "reply": "嘗試修改其他標籤。",
                "safety_groups": [groups[1]],
            }
        )

        with self.assertRaisesRegex(ValueError, "未勾選"):
            rule_management.suggest_safety_rule_edits(
                llm_client=assistant,
                message="修改規則",
                selected_labels=[groups[0]["original_label"]],
                groups=groups,
                history=[],
            )

    def test_successful_update_writes_json_audit_and_new_revision(self):
        current = load_safety_rules()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rules_path = root / "safety_rules.json"
            audit_dir = root / "audit"
            rules_path.write_text(
                json.dumps(current, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            loader = _TemporaryRuleLoader(rules_path)
            groups = rule_management._rule_groups(current)
            groups[0]["label"] = f"{groups[0]['label']}（校訂）"

            with (
                patch.dict(
                    os.environ,
                    {"SAFETY_RULE_ADMIN_TOKEN": "correct-secret"},
                    clear=False,
                ),
                patch.object(rule_management, "SAFETY_RULES_PATH", rules_path),
                patch.object(rule_management, "AUDIT_DIR", audit_dir),
                patch.object(rule_management, "load_safety_rules", loader),
            ):
                result = rule_management.update_safety_rules(
                    admin_token="correct-secret",
                    expected_revision=rule_management._revision(current),
                    confirmation="更新安全規則",
                    change_note="依急診科會議校訂標籤",
                    actor_session_id="doctor-session",
                    groups=groups,
                )

            saved = read_safety_rules(rules_path)
            audit_files = list(audit_dir.glob("*.json"))
            audit = json.loads(audit_files[0].read_text(encoding="utf-8"))
            self.assertNotEqual(
                result["revision"],
                rule_management._revision(current),
            )
            self.assertIn(
                groups[0]["label"],
                saved["urgent_condition_candidates"],
            )
            self.assertEqual(len(audit_files), 1)
            self.assertEqual(audit["actor_session_id"], "doctor-session")
            self.assertEqual(
                audit["previous_revision"],
                rule_management._revision(current),
            )


if __name__ == "__main__":
    unittest.main()
