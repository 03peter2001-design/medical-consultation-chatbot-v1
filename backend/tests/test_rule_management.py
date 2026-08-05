import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from amie.clinical_facts import FACT_CODES
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
        self.assertEqual(set(catalog), set(FACT_CODES))
        self.assertFalse(catalog["altered_consciousness"]["is_safety"])
        self.assertGreater(
            catalog["altered_consciousness"]["conditional_safety_rule_count"],
            0,
        )
        self.assertIn("chest", catalog["chest_pressure"]["categories"])
        self.assertIn("abdomen", catalog["onset_sudden"]["categories"])
        self.assertEqual(
            catalog["severity_severe"]["description"],
            "患者明確表達症狀非常強烈、難以忍受或接近可承受極限；必須結合症狀部位判斷。",
        )
        mesenteric = next(
            profile
            for route in payload["routes"]
            if route["route"] == "abdomen"
            for profile in route["profiles"]
            if profile["id"] == "mesenteric_ischemia"
        )
        self.assertTrue(
            {clue["fact"] for clue in mesenteric["clues"]}.issubset(catalog),
        )
        self.assertTrue(all(item["description"] for item in payload["fact_catalog"]))
        self.assertEqual(payload["fact_confirmation_text"], "更新標籤設定")
        self.assertEqual(payload["disease_confirmation_text"], "更新疾病票數")
        self.assertEqual(payload["max_clue_weight"], 10)
        self.assertTrue(all(len(item["profile_revision"]) == 64 for item in payload["routes"]))
        self.assertTrue(all(item["profiles"] for item in payload["routes"]))

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

    def test_publisher_uses_facade_patched_dependencies(self):
        current = load_safety_rules()
        groups = rule_management._rule_groups(current)
        groups[0]["label"] = f"{groups[0]['label']}（seam test）"
        original_revision = rule_management._revision
        original_candidate_document = rule_management._candidate_document

        with (
            patch.object(rule_management, "_require_admin_token") as require_token,
            patch.object(
                rule_management,
                "_revision",
                wraps=original_revision,
            ) as revision,
            patch.object(
                rule_management,
                "_candidate_document",
                wraps=original_candidate_document,
            ) as candidate_document,
            patch.object(
                rule_management,
                "_atomic_write",
                side_effect=RuntimeError("patched atomic writer"),
            ) as atomic_write,
        ):
            with self.assertRaisesRegex(RuntimeError, "patched atomic writer"):
                rule_management.update_safety_rules(
                    admin_token="patched-token",
                    expected_revision=original_revision(current),
                    confirmation="更新安全規則",
                    change_note="驗證 facade dependency seam",
                    actor_session_id="seam-test",
                    groups=groups,
                )

        require_token.assert_called_once_with("patched-token")
        candidate_document.assert_called_once_with(current, groups)
        self.assertEqual(revision.call_count, 2)
        atomic_write.assert_called_once()

    def test_rule_center_uses_facade_patched_profile_loader(self):
        original_loader = rule_management.load_profile_document
        with patch.object(
            rule_management,
            "load_profile_document",
            wraps=original_loader,
        ) as profile_loader:
            payload = rule_management.rule_center_payload()

        self.assertEqual(
            [call.args[0] for call in profile_loader.call_args_list],
            [item["route"] for item in payload["routes"]],
        )

    def test_general_fact_label_governance_updates_descriptions_only(self):
        current = load_safety_rules()
        labels = [
            {
                "code": item["code"],
                "description": item["description"],
                "is_safety": item["is_safety"],
            }
            for item in rule_management._fact_catalog(current)
        ]
        target = next(item for item in labels if item["code"] == "onset_sudden")
        target["description"] = "醫師校訂的一般標籤說明。"
        target["is_safety"] = True

        candidate, changes = rule_management._candidate_fact_labels(
            current,
            labels,
        )

        self.assertEqual(
            candidate["semantic_extraction"]["onset_definitions"]["sudden"],
            target["description"],
        )
        self.assertEqual(changes[0]["code"], target["code"])
        self.assertTrue(changes[0]["next_is_safety"])
        self.assertIn(target["code"], candidate["safety_fact_codes"])
        self.assertEqual(len(changes), 1)

        missing = copy.deepcopy(labels[:-1])
        with self.assertRaisesRegex(ValueError, "不可新增或刪除"):
            rule_management._candidate_fact_labels(current, missing)

        duplicate = copy.deepcopy(labels)
        duplicate[-1]["code"] = duplicate[0]["code"]
        with self.assertRaisesRegex(ValueError, "不正確或重複"):
            rule_management._candidate_fact_labels(current, duplicate)

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

    def test_successful_fact_label_update_writes_audit_snapshot(self):
        current = load_safety_rules()
        labels = [
            {
                "code": item["code"],
                "description": item["description"],
                "is_safety": item["is_safety"],
            }
            for item in rule_management._fact_catalog(current)
        ]
        labels[0]["description"] = "醫師覆核後的一般標籤說明。"

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rules_path = root / "safety_rules.json"
            audit_dir = root / "audit"
            rules_path.write_text(
                json.dumps(current, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            loader = _TemporaryRuleLoader(rules_path)

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
                result = rule_management.update_fact_labels(
                    admin_token="correct-secret",
                    expected_revision=rule_management._revision(current),
                    confirmation="更新標籤設定",
                    change_note="依臨床會議校訂標籤說明",
                    actor_session_id="doctor-session",
                    labels=labels,
                )

            saved = read_safety_rules(rules_path)
            audit_files = list(audit_dir.glob("*.json"))
            audit = json.loads(audit_files[0].read_text(encoding="utf-8"))
            saved_catalog = {
                item["code"]: item["description"] for item in rule_management._fact_catalog(saved)
            }
            self.assertEqual(saved_catalog[labels[0]["code"]], labels[0]["description"])
            self.assertNotEqual(
                result["revision"],
                rule_management._revision(current),
            )
            self.assertEqual(audit["event_type"], "fact_labels_updated")
            self.assertEqual(audit["changes"][0]["code"], labels[0]["code"])

    def test_disease_profile_governance_only_changes_weights_and_review_metadata(self):
        current = rule_management._read_profile_source("chest")
        profiles = [
            {
                "id": profile["id"],
                "safety_rule_codes": list(profile["safety_rule_codes"]),
                "clues": [
                    {key: clue[key] for key in ("fact", "status", "direction", "weight")}
                    for clue in profile["clues"]
                ],
            }
            for profile in current["profiles"]
        ]
        profiles[0]["clues"][0]["weight"] = 3
        reviewed_at = datetime(2026, 8, 4, 8, 30, tzinfo=timezone.utc)

        candidate, changes = rule_management._candidate_profile_document(
            current,
            profiles,
            reviewer="王醫師",
            reviewed_at=reviewed_at,
        )

        self.assertEqual(candidate["profiles"][0]["clues"][0]["weight"], 3)
        self.assertEqual(candidate["profiles"][0]["review_status"], "reviewed")
        self.assertEqual(candidate["profiles"][0]["reviewer"], "王醫師")
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["previous_weight"], 1)
        self.assertEqual(changes[0]["next_weight"], 3)
        self.assertEqual(candidate["generation"]["model"], "none")

        invalid = copy.deepcopy(profiles)
        invalid[0]["clues"][0]["weight"] = 11
        with self.assertRaisesRegex(ValueError, "必須介於 1 至 10"):
            rule_management._candidate_profile_document(
                current,
                invalid,
                reviewer="王醫師",
                reviewed_at=reviewed_at,
            )

    def test_disease_profile_governance_adds_and_removes_whitelisted_labels(self):
        current = rule_management._read_profile_source("chest")
        profiles = [
            {
                "id": profile["id"],
                "safety_rule_codes": list(profile["safety_rule_codes"]),
                "clues": [
                    {key: clue[key] for key in ("fact", "status", "direction", "weight")}
                    for clue in profile["clues"]
                ],
            }
            for profile in current["profiles"]
        ]
        target = profiles[0]
        existing_facts = {clue["fact"] for clue in target["clues"]}
        added_fact = next(fact for fact in rule_management.FACT_CODES if fact not in existing_facts)
        removed_fact = target["clues"].pop()["fact"]
        target["clues"].append(
            {
                "fact": added_fact,
                "status": "present",
                "direction": "support",
                "weight": 2,
            }
        )

        candidate, changes = rule_management._candidate_profile_document(
            current,
            profiles,
            reviewer="王醫師",
            reviewed_at=datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc),
        )

        changed_profile = candidate["profiles"][0]
        changed_facts = {clue["fact"] for clue in changed_profile["clues"]}
        self.assertIn(added_fact, changed_facts)
        self.assertNotIn(removed_fact, changed_facts)
        added = next(change for change in changes if change["action"] == "added")
        removed = next(change for change in changes if change["action"] == "removed")
        self.assertEqual(added["fact"], added_fact)
        self.assertEqual(removed["fact"], removed_fact)
        self.assertTrue(
            next(clue for clue in changed_profile["clues"] if clue["fact"] == added_fact)[
                "source_ids"
            ]
        )

        invalid = copy.deepcopy(profiles)
        invalid[0]["clues"][0]["fact"] = "not_a_clinical_fact"
        with self.assertRaisesRegex(ValueError, "不在白名單"):
            rule_management._candidate_profile_document(
                current,
                invalid,
                reviewer="王醫師",
                reviewed_at=datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc),
            )

    def test_disease_profile_governance_updates_safety_rule_links(self):
        current = rule_management._read_profile_source("chest")
        profiles = [
            {
                "id": profile["id"],
                "safety_rule_codes": list(profile["safety_rule_codes"]),
                "clues": [
                    {key: clue[key] for key in ("fact", "status", "direction", "weight")}
                    for clue in profile["clues"]
                ],
            }
            for profile in current["profiles"]
        ]
        target = next(profile for profile in profiles if profile["id"] == "acute_coronary_syndrome")
        removed_code = target["safety_rule_codes"].pop()

        candidate, changes = rule_management._candidate_profile_document(
            current,
            profiles,
            reviewer="王醫師",
            reviewed_at=datetime(2026, 8, 4, 9, 30, tzinfo=timezone.utc),
        )

        saved_target = next(
            profile
            for profile in candidate["profiles"]
            if profile["id"] == "acute_coronary_syndrome"
        )
        self.assertNotIn(removed_code, saved_target["safety_rule_codes"])
        safety_change = next(
            change for change in changes if change["action"] == "safety_triggers_updated"
        )
        self.assertIn(removed_code, safety_change["previous_rule_codes"])
        self.assertNotIn(removed_code, safety_change["next_rule_codes"])

    def test_successful_disease_profile_update_writes_audit_snapshot(self):
        current = rule_management._read_profile_source("chest")
        profiles = [
            {
                "id": profile["id"],
                "safety_rule_codes": list(profile["safety_rule_codes"]),
                "clues": [
                    {key: clue[key] for key in ("fact", "status", "direction", "weight")}
                    for clue in profile["clues"]
                ],
            }
            for profile in current["profiles"]
        ]
        profiles[0]["clues"][0]["weight"] = 2

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile_dir = root / "profiles"
            profile_dir.mkdir()
            profile_path = profile_dir / "chest.json"
            profile_path.write_text(
                json.dumps(current, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            audit_dir = root / "audit"
            with (
                patch.dict(
                    os.environ,
                    {"SAFETY_RULE_ADMIN_TOKEN": "correct-secret"},
                    clear=False,
                ),
                patch.object(rule_management, "PROFILE_DATA_DIR", profile_dir),
                patch.object(
                    rule_management,
                    "DISEASE_PROFILE_AUDIT_DIR",
                    audit_dir,
                ),
                patch.object(rule_management, "rule_center_payload", return_value={"saved": True}),
            ):
                result = rule_management.update_disease_profile(
                    route="chest",
                    admin_token="correct-secret",
                    expected_revision=rule_management._revision(current),
                    confirmation="更新疾病票數",
                    change_note="依急診科共識調整胸痛權重",
                    reviewer="王醫師",
                    actor_session_id="doctor-session",
                    profiles=profiles,
                )

            saved = json.loads(profile_path.read_text(encoding="utf-8"))
            audit_files = list(audit_dir.glob("*.json"))
            audit = json.loads(audit_files[0].read_text(encoding="utf-8"))
            self.assertEqual(result, {"saved": True})
            self.assertEqual(saved["profiles"][0]["clues"][0]["weight"], 2)
            self.assertEqual(saved["profiles"][0]["reviewer"], "王醫師")
            self.assertEqual(len(audit_files), 1)
            self.assertEqual(audit["changes"][0]["next_weight"], 2)
            self.assertEqual(audit["actor_session_id"], "doctor-session")


if __name__ == "__main__":
    unittest.main()
