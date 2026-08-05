import copy
import json
import unittest
from unittest.mock import patch

from amie.clinical_facts import FACT_CODES
from amie.engine import AMIEEngine
from amie.rule_config import load_safety_rules
from amie.safety import detect_red_flags
from domain.questionnaires import build_questionnaire


class FakeLLM:
    def __init__(self, *responses, semantic_response=None):
        self.responses = list(responses)
        self.semantic_response = semantic_response
        self.calls = []

    def generate_text(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        is_semantic = "主訴資訊抽取器" in messages[0]["content"]
        if is_semantic:
            response = self.semantic_response or {
                "primary_symptom": "unknown",
                "primary_evidence": "",
                "symptom_domains": [],
                "onset": {"value": "unknown", "evidence": ""},
                "severity": {"value": "unknown", "evidence": ""},
                "is_new_or_changed": {
                    "value": "unknown",
                    "evidence": "",
                },
                "findings": [],
                "negated_findings": [],
                "route_candidates": [],
                "uncertain_fields": [],
            }
        else:
            if not self.responses:
                raise RuntimeError("unexpected model call")
            response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return json.dumps(response, ensure_ascii=False) if isinstance(response, dict) else response


class AMIEEngineTests(unittest.TestCase):
    def setUp(self):
        self.questionnaire = build_questionnaire("chest")
        self.prefilled = {
            "name",
            "gender",
            "birth_date",
            "blood_type",
        }
        self.base_data = {
            "type": "chest",
            "reason": "走路時胸口悶，三十分鐘前開始",
            "name": "測試病人",
            "gender": "男",
            "birth_date": "1980-01-01",
            "age": "46",
            "blood_type": "A型",
        }

    def test_model_only_extracts_facts_and_program_scores_and_selects(self):
        llm = FakeLLM(
            semantic_response={
                "primary_symptom": "chest",
                "primary_evidence": "胸口悶",
                "symptom_domains": [
                    {
                        "route": "chest",
                        "evidence": "胸口悶",
                    }
                ],
                "onset": {"value": "unknown", "evidence": ""},
                "severity": {"value": "unknown", "evidence": ""},
                "is_new_or_changed": {"value": "unknown", "evidence": ""},
                "findings": [
                    {
                        "code": "chest_pressure",
                        "status": "present",
                        "evidence": "胸口悶",
                    },
                    {
                        "code": "exertional_trigger",
                        "status": "present",
                        "evidence": "走路時",
                    },
                ],
                "negated_findings": [],
                "route_candidates": [
                    {
                        "route": "chest",
                        "evidence": "胸口悶",
                    }
                ],
                "symptom_assessments": [],
                "uncertain_fields": [],
            }
        )
        result = AMIEEngine(llm).run_turn(
            route="chest",
            answer=self.base_data["reason"],
            current_field="reason",
            data=self.base_data,
            questionnaire=self.questionnaire,
            prefilled_fields=self.prefilled,
        )

        self.assertEqual(result.action, "ask")
        self.assertEqual(result.next_question["field"], "start_type")
        self.assertEqual(len(result.evidence_timeline), 1)
        self.assertEqual(result.differential_hypotheses, [])
        self.assertEqual(
            result.disease_assessment["top"][0]["id"],
            "acute_coronary_syndrome",
        )
        self.assertEqual(result.disease_assessment["top"][0]["net_votes"], 2)
        self.assertEqual(result.decision["scoring_method"], "unit_vote_v1")
        self.assertEqual(len(llm.calls), 1)

    def test_chief_extraction_is_reused_instead_of_calling_the_llm_twice(self):
        extraction = {
            "primary_symptom": "chest",
            "primary_evidence": "胸口悶",
            "symptom_domains": [{"route": "chest", "evidence": "胸口悶"}],
            "onset": {"value": "unknown", "evidence": ""},
            "severity": {"value": "unknown", "evidence": ""},
            "is_new_or_changed": {"value": "unknown", "evidence": ""},
            "findings": [
                {
                    "code": "chest_pressure",
                    "status": "present",
                    "evidence": "胸口悶",
                }
            ],
            "negated_findings": [],
            "route_candidates": [{"route": "chest", "evidence": "胸口悶"}],
            "symptom_assessments": [],
            "uncertain_fields": [],
        }
        llm = FakeLLM()
        result = AMIEEngine(llm).run_turn(
            route="chest",
            answer="胸口悶",
            current_field="reason",
            data={
                **self.base_data,
                "reason": "胸口悶",
                "_chief_assessment": {"extraction": extraction},
            },
            questionnaire=self.questionnaire,
            prefilled_fields=self.prefilled,
        )

        self.assertEqual(result.action, "ask")
        self.assertEqual(result.disease_assessment["top"][0]["id"], "acute_coronary_syndrome")
        self.assertEqual(llm.calls, [])

    def test_chief_vomiting_is_not_repeated_in_abdominal_followup(self):
        extraction = {
            "primary_symptom": "abdomen",
            "primary_evidence": "肚子痛",
            "symptom_domains": [{"route": "abdomen", "evidence": "肚子痛"}],
            "onset": {"value": "unknown", "evidence": ""},
            "severity": {"value": "unknown", "evidence": ""},
            "is_new_or_changed": {"value": "unknown", "evidence": ""},
            "findings": [
                {
                    "code": "vomiting",
                    "status": "present",
                    "evidence": "嘔吐",
                }
            ],
            "negated_findings": [],
            "route_candidates": [{"route": "abdomen", "evidence": "肚子痛"}],
            "symptom_assessments": [],
            "uncertain_fields": [],
        }
        data = {
            **self.base_data,
            "type": "abdomen",
            "reason": "我肚子痛、嘔吐",
            "start_type": "逐漸出現",
            "severity": "中等，已影響活動",
            "_chief_assessment": {"extraction": extraction},
            "_clinical_facts": [
                {
                    "code": "vomiting",
                    "status": "present",
                    "evidence": "嘔吐",
                    "source": "chief_semantic_extraction",
                    "turn": 1,
                }
            ],
        }

        result = AMIEEngine(FakeLLM()).run_turn(
            route="abdomen",
            answer=data["reason"],
            current_field="reason",
            data=data,
            questionnaire=build_questionnaire("abdomen"),
            prefilled_fields=self.prefilled,
        )

        self.assertEqual(result.next_question["field"], "associated")
        self.assertNotIn("嘔吐", result.next_question["options"])
        self.assertNotIn(
            "vomiting",
            result.next_question["semantic_options"]["以上皆無"]["negated_findings"],
        )

    def test_semantic_output_with_extra_route_key_is_rejected(self):
        llm = FakeLLM(
            semantic_response={
                "primary_symptom": "chest",
                "primary_evidence": "兇悶",
                "symptom_domains": [
                    {
                        "domain": "chest",
                        "evidence": "兇悶",
                    }
                ],
                "route_candidates": [
                    {
                        "route": "chest",
                        "evidence": "兇悶",
                    }
                ],
            },
        )

        result = AMIEEngine(llm).run_turn(
            route="chest",
            answer="我兇悶",
            current_field="reason",
            data={
                **self.base_data,
                "reason": "我兇悶",
            },
            questionnaire=self.questionnaire,
            prefilled_fields=self.prefilled,
        )

        self.assertEqual(result.action, "handoff")
        self.assertIn("未允許欄位", result.model_error)

    def test_multiple_route_objects_continue_instead_of_handoff(self):
        llm = FakeLLM(
            semantic_response={
                "primary_symptom": "headache",
                "primary_evidence": "頭痛",
                "symptom_domains": [
                    {
                        "route": "headache",
                        "evidence": "頭痛",
                    },
                    {
                        "route": "abdomen",
                        "evidence": "肚子痛",
                    },
                ],
                "route_candidates": [
                    {
                        "route": "headache",
                        "evidence": "頭痛",
                    },
                    {
                        "route": "abdomen",
                        "evidence": "肚子痛",
                    },
                ],
            },
        )

        result = AMIEEngine(llm).run_turn(
            route="headache",
            answer="我頭痛，肚子痛",
            current_field="reason",
            data={
                **self.base_data,
                "type": "headache",
                "reason": "我頭痛，肚子痛",
            },
            questionnaire=build_questionnaire("headache"),
            prefilled_fields=self.prefilled,
        )

        self.assertEqual(result.action, "ask")
        self.assertNotEqual(result.action, "handoff")
        self.assertEqual(result.model_error, "")

    def test_multiple_route_questionnaire_requires_both_symptom_pipelines(self):
        questionnaire = build_questionnaire(["headache", "abdomen"])
        data = {
            "type": "headache",
            "types": ["headache", "abdomen"],
            "onset": "1天前",
            "start_type": "逐漸加重",
            "worst_ever": "否",
            "associated": "噁心",
            "risk_flags": "以上皆無",
            "current_meds": "沒有",
            "allergy": "沒有",
        }

        missing = AMIEEngine._required_missing(data, questionnaire)

        self.assertNotIn("onset", missing)
        self.assertIn("abdomen__onset", missing)
        self.assertIn("abdomen__location", missing)
        self.assertIn("abdomen__associated", missing)

    def test_basic_identity_answer_never_calls_external_model(self):
        llm = FakeLLM()
        result = AMIEEngine(llm).run_turn(
            route="chest",
            answer="王小明",
            current_field="name",
            data={
                "type": "chest",
                "reason": "胸口不舒服",
                "name": "王小明",
            },
            questionnaire=self.questionnaire,
        )

        self.assertEqual(result.next_question["field"], "gender")
        self.assertEqual(llm.calls, [])

    def test_red_flag_ends_urgent_interview_without_model_call(self):
        llm = FakeLLM()
        result = AMIEEngine(llm).run_turn(
            route="chest",
            answer="剛剛胸痛而且昏厥暈倒",
            current_field="reason",
            data={
                **self.base_data,
                "reason": "剛剛胸痛而且昏厥暈倒",
            },
            questionnaire=self.questionnaire,
            prefilled_fields=self.prefilled,
        )

        self.assertEqual(result.action, "complete")
        self.assertEqual(result.triage_level, "urgent")
        self.assertIsNone(result.next_question)
        self.assertTrue(result.red_flags)
        self.assertEqual(
            result.disease_assessment["status"],
            "safety_triggered",
        )
        self.assertEqual(
            result.disease_assessment["safety_triggered_conditions"][0]["profile_id"],
            "acute_coronary_syndrome",
        )
        self.assertEqual(llm.calls, [])

    def test_semantic_safety_runs_before_planning_on_each_clinical_turn(self):
        llm = FakeLLM(
            semantic_response={
                "primary_symptom": "headache",
                "primary_evidence": "投痛",
                "symptom_domains": [
                    {
                        "route": "headache",
                        "evidence": "投痛",
                    }
                ],
                "onset": {"value": "unknown", "evidence": ""},
                "severity": {
                    "value": "severe",
                    "evidence": "投痛到受不了",
                },
                "is_new_or_changed": {
                    "value": "unknown",
                    "evidence": "",
                },
                "findings": [
                    {
                        "code": "blurred_vision",
                        "status": "present",
                        "evidence": "眼前霧成一片",
                    }
                ],
                "negated_findings": [],
                "route_candidates": [
                    {
                        "route": "headache",
                        "evidence": "投痛",
                    }
                ],
                "symptom_assessments": [],
                "uncertain_fields": [],
            }
        )
        result = AMIEEngine(llm).run_turn(
            route="headache",
            answer="我投痛到受不了，眼前霧成一片",
            current_field="associated",
            data={
                **self.base_data,
                "type": "headache",
                "reason": "投痛",
            },
            questionnaire=build_questionnaire("headache"),
            prefilled_fields=self.prefilled,
        )

        self.assertEqual(result.action, "complete")
        self.assertEqual(result.triage_level, "urgent")
        self.assertTrue(
            {
                "semantic_headache_visual_change",
                "semantic_severe_headache_visual_change",
            }.issubset({flag["code"] for flag in result.red_flags})
        )
        self.assertTrue(
            {"蜘蛛膜下腔出血", "顱內出血"}.issubset(
                {item["name"] for item in result.disease_assessment["safety_triggered_conditions"]}
            )
        )
        self.assertEqual(len(llm.calls), 1)

    def test_doctor_selected_safety_fact_stops_the_interview(self):
        rules = copy.deepcopy(load_safety_rules())
        rules["safety_fact_codes"] = ["nausea"]
        llm = FakeLLM(
            semantic_response={
                "primary_symptom": "headache",
                "primary_evidence": "頭痛",
                "primary_symptom_code": "headache",
                "symptoms": [{"code": "headache", "evidence": "頭痛"}],
                "symptom_domains": [{"route": "headache", "evidence": "頭痛"}],
                "onset": {"value": "unknown", "evidence": ""},
                "severity": {"value": "unknown", "evidence": ""},
                "is_new_or_changed": {"value": "unknown", "evidence": ""},
                "findings": [
                    {
                        "code": "nausea",
                        "status": "present",
                        "evidence": "很噁心",
                    }
                ],
                "negated_findings": [],
                "route_candidates": [{"route": "headache", "evidence": "頭痛"}],
                "symptom_assessments": [],
                "uncertain_fields": [],
            }
        )

        with patch("amie.safety.load_safety_rules", return_value=rules):
            result = AMIEEngine(llm).run_turn(
                route="headache",
                answer="頭痛而且很噁心",
                current_field="associated",
                data={**self.base_data, "type": "headache", "reason": "頭痛"},
                questionnaire=build_questionnaire("headache"),
                prefilled_fields=self.prefilled,
            )

        self.assertEqual(result.action, "complete")
        self.assertEqual(result.triage_level, "urgent")
        self.assertIsNone(result.next_question)
        self.assertIn(
            "clinical_fact:nausea",
            {flag["code"] for flag in result.red_flags},
        )

    def test_standard_option_uses_json_semantics_without_extractor(self):
        llm = FakeLLM()
        data = {
            **self.base_data,
            "type": "headache",
            "reason": "頭痛得非常嚴重",
            "_chief_assessment": {
                "extraction": {
                    "primary_symptom": "headache",
                    "primary_evidence": "頭痛",
                    "severity": {
                        "value": "severe",
                        "evidence": "非常嚴重",
                    },
                    "findings": [],
                }
            },
        }
        result = AMIEEngine(llm).run_turn(
            route="headache",
            answer="視力模糊或複視",
            current_field="associated",
            data=data,
            questionnaire=build_questionnaire("headache"),
            prefilled_fields=self.prefilled,
        )

        self.assertEqual(result.triage_level, "urgent")
        self.assertTrue(
            {
                "semantic_headache_visual_change",
                "semantic_severe_headache_visual_change",
            }.issubset({flag["code"] for flag in result.red_flags})
        )
        self.assertEqual(llm.calls, [])

    def test_headache_standard_option_skips_extractor_and_uses_disease_vote(self):
        llm = FakeLLM()
        result = AMIEEngine(llm).run_turn(
            route="headache",
            answer="逐漸加重",
            current_field="start_type",
            data={
                **self.base_data,
                "type": "headache",
                "reason": "頭痛",
                "start_type": "逐漸加重",
            },
            questionnaire=build_questionnaire("headache"),
            prefilled_fields=self.prefilled,
        )

        self.assertEqual(result.action, "ask")
        self.assertEqual(result.next_question["field"], "worst_ever")
        self.assertEqual(result.disease_assessment["method"], "unit_vote_v1")
        self.assertIn(
            "onset_gradual",
            [fact["code"] for fact in result.clinical_facts],
        )
        self.assertEqual(llm.calls, [])

    def test_chest_severity_option_maps_directly_to_a_clinical_fact(self):
        llm = FakeLLM()
        result = AMIEEngine(llm).run_turn(
            route="chest",
            answer="中等",
            current_field="severity",
            data={**self.base_data, "severity": "中等"},
            questionnaire=self.questionnaire,
            prefilled_fields=self.prefilled,
        )

        self.assertIn(
            "severity_moderate",
            {fact["code"] for fact in result.clinical_facts},
        )
        self.assertEqual(llm.calls, [])

    def test_abdominal_episodic_option_maps_to_time_course_fact(self):
        llm = FakeLLM()
        result = AMIEEngine(llm).run_turn(
            route="abdomen",
            answer="陣痛",
            current_field="quality",
            data={
                **self.base_data,
                "type": "abdomen",
                "reason": "肚子痛",
                "quality": "陣痛",
            },
            questionnaire=build_questionnaire("abdomen"),
            prefilled_fields=self.prefilled,
        )

        fact_codes = {fact["code"] for fact in result.clinical_facts}
        self.assertIn("course_episodic", fact_codes)
        self.assertIn("colicky_abdominal_pain", fact_codes)
        self.assertEqual(llm.calls, [])

    def test_abdominal_peritoneal_option_triggers_safety_and_fixed_directions(
        self,
    ):
        llm = FakeLLM()
        result = AMIEEngine(llm).run_turn(
            route="abdomen",
            answer="腹部僵硬或按壓放開更痛",
            current_field="associated",
            data={
                **self.base_data,
                "type": "abdomen",
                "reason": "腹痛",
                "associated": "腹部僵硬或按壓放開更痛",
            },
            questionnaire=build_questionnaire("abdomen"),
            prefilled_fields=self.prefilled,
        )

        self.assertEqual(result.action, "complete")
        self.assertEqual(result.triage_level, "urgent")
        self.assertEqual(
            result.red_flags[0]["code"],
            "peritonism",
        )
        self.assertEqual(
            [
                item["profile_id"]
                for item in result.disease_assessment["safety_triggered_conditions"]
            ],
            ["perforation_or_peritonitis", "mesenteric_ischemia"],
        )
        self.assertEqual(llm.calls, [])

    def test_abdominal_pregnancy_bleeding_option_triggers_ectopic_direction(
        self,
    ):
        llm = FakeLLM()
        result = AMIEEngine(llm).run_turn(
            route="abdomen",
            answer="月經過期、陰道出血",
            current_field="associated",
            data={
                **self.base_data,
                "type": "abdomen",
                "reason": "下腹痛",
                "associated": "月經過期、陰道出血",
            },
            questionnaire=build_questionnaire("abdomen"),
            prefilled_fields=self.prefilled,
        )

        self.assertEqual(result.triage_level, "urgent")
        self.assertEqual(
            result.red_flags[0]["code"],
            "semantic_pregnancy_abdominal_bleeding",
        )
        self.assertEqual(
            result.disease_assessment["safety_triggered_conditions"][0]["profile_id"],
            "ruptured_ectopic_pregnancy",
        )
        self.assertEqual(llm.calls, [])

    def test_semantic_safety_failure_hands_off_instead_of_planning(self):
        llm = FakeLLM(semantic_response=RuntimeError("provider unavailable"))
        result = AMIEEngine(llm).run_turn(
            route="headache",
            answer="症狀變得很不舒服",
            current_field="associated",
            data={
                **self.base_data,
                "type": "headache",
                "reason": "頭痛",
            },
            questionnaire=build_questionnaire("headache"),
            prefilled_fields=self.prefilled,
        )

        self.assertEqual(result.action, "handoff")
        self.assertEqual(result.triage_level, "routine")
        self.assertIn("語意安全檢查", result.handoff_reason)
        self.assertEqual(len(llm.calls), 1)

    def test_existing_urgent_state_also_ends_without_model_call(self):
        llm = FakeLLM()
        previous_state = {
            "triage_level": "urgent",
            "red_flags": [
                {
                    "code": "chest_diaphoresis",
                    "label": "胸部不適合併冒冷汗",
                    "evidence": "冒冷汗",
                    "level": "urgent",
                }
            ],
        }
        result = AMIEEngine(llm).run_turn(
            route="chest",
            answer="胸口中央",
            current_field="location",
            data={**self.base_data, "location": "胸口中央"},
            questionnaire=self.questionnaire,
            prefilled_fields=self.prefilled,
            previous_state=previous_state,
        )

        self.assertEqual(result.triage_level, "urgent")
        self.assertEqual(result.action, "complete")
        self.assertEqual(
            result.disease_assessment["safety_triggered_conditions"][0]["profile_id"],
            "acute_coronary_syndrome",
        )
        self.assertEqual(llm.calls, [])

    def test_invalid_semantic_output_hands_off_before_scoring(self):
        llm = FakeLLM(semantic_response="not-json")
        result = AMIEEngine(llm).run_turn(
            route="chest",
            answer="胸口不舒服",
            current_field="reason",
            data=self.base_data,
            questionnaire=self.questionnaire,
            prefilled_fields=self.prefilled,
        )

        self.assertEqual(result.action, "handoff")
        self.assertTrue(result.model_error)

    def test_runtime_interview_never_calls_rag_or_planning_model(self):
        llm = FakeLLM(
            semantic_response={
                "primary_symptom": "chest",
                "primary_evidence": "胸口不舒服",
                "symptom_domains": [{"route": "chest", "evidence": "胸口不舒服"}],
                "onset": {"value": "unknown", "evidence": ""},
                "severity": {"value": "unknown", "evidence": ""},
                "is_new_or_changed": {"value": "unknown", "evidence": ""},
                "findings": [],
                "negated_findings": [],
                "route_candidates": [{"route": "chest", "evidence": "胸口不舒服"}],
                "symptom_assessments": [],
                "uncertain_fields": [],
            }
        )
        result = AMIEEngine(llm).run_turn(
            route="chest",
            answer="胸口不舒服",
            current_field="reason",
            data=self.base_data,
            questionnaire=self.questionnaire,
            prefilled_fields=self.prefilled,
        )

        self.assertEqual(result.next_question["field"], "start_type")
        self.assertEqual(result.rag_sources, [])
        self.assertEqual(len(llm.calls), 1)
        self.assertIn("主訴資訊抽取器", llm.calls[0]["messages"][0]["content"])

    def test_chest_completes_when_required_fields_and_top_five_coverage_reach_70_percent(
        self,
    ):
        facts = [
            {
                "code": code,
                "status": "present",
                "evidence": code,
                "source": "test",
                "turn": 1,
            }
            for code in FACT_CODES
        ]
        data = {
            **self.base_data,
            "onset": "1小時前",
            "location": "正中間",
            "severity": "中等",
            "quality": "感覺有重物壓迫",
            "aggravate": "耗費體力的活動",
            "associated": "以上皆無",
            "current_meds": "沒有",
            "allergy": "沒有",
            "_clinical_facts": facts,
        }

        result = AMIEEngine(FakeLLM()).run_turn(
            route="chest",
            answer="以上皆無",
            current_field="associated",
            data=data,
            questionnaire=self.questionnaire,
            prefilled_fields=self.prefilled,
        )

        self.assertEqual(result.action, "complete")
        self.assertTrue(all(item["coverage"] >= 0.7 for item in result.disease_assessment["top"]))

    def test_chest_completes_when_remaining_questions_cannot_change_votes(self):
        data = {
            **self.base_data,
            "onset": "1小時前",
            "start_type": "逐漸發作",
            "location": "正中間",
            "fixed": "痛點固定",
            "tender": "沒有",
            "severity": "中等",
            "quality": "感覺有重物壓迫",
            "aggravate": "耗費體力的活動",
            "relieve": "休息",
            "associated": "以上皆無",
            "current_meds": "沒有",
            "allergy": "沒有",
        }

        result = AMIEEngine(FakeLLM()).run_turn(
            route="chest",
            answer="以上皆無",
            current_field="associated",
            data=data,
            questionnaire=self.questionnaire,
            prefilled_fields=self.prefilled,
        )

        self.assertEqual(result.action, "complete")
        self.assertIn("不會改變", result.decision["audit_reason"])

    def test_turn_24_hands_off_when_completion_requirements_are_not_met(self):
        result = AMIEEngine(FakeLLM(), max_turns=24).run_turn(
            route="chest",
            answer="逐漸發作",
            current_field="start_type",
            data={**self.base_data, "start_type": "逐漸發作"},
            questionnaire=self.questionnaire,
            prefilled_fields=self.prefilled,
            turn_count=24,
        )

        self.assertEqual(result.action, "handoff")
        self.assertIn("輪數上限", result.handoff_reason)

    def test_unavailable_disease_table_hands_off_without_model_generated_candidates(
        self,
    ):
        with patch(
            "amie.engine.score_diseases",
            side_effect=ValueError("profile unavailable"),
        ):
            result = AMIEEngine(FakeLLM()).run_turn(
                route="chest",
                answer="逐漸發作",
                current_field="start_type",
                data={**self.base_data, "start_type": "逐漸發作"},
                questionnaire=self.questionnaire,
                prefilled_fields=self.prefilled,
            )

        self.assertEqual(result.action, "handoff")
        self.assertEqual(result.disease_assessment["status"], "unavailable")
        self.assertEqual(result.differential_hypotheses, [])
        self.assertIn("ValueError", result.model_error)


class SafetyRuleTests(unittest.TestCase):
    def test_universal_severe_chief_complaint_needs_no_route(self):
        flags = detect_red_flags(
            None,
            "我現在喘不過氣而且快要失去意識",
            {"reason": "我現在喘不過氣而且快要失去意識"},
        )
        codes = {flag["code"] for flag in flags}
        self.assertIn("severe_breathing", codes)
        self.assertIn("altered_consciousness", codes)

    def test_nearby_negation_does_not_trigger(self):
        flags = detect_red_flags(
            "chest",
            "胸口悶，但是沒有昏厥，也沒有冒冷汗",
            {"reason": "胸口悶"},
        )
        self.assertEqual(flags, [])

    def test_headache_neurologic_deficit_triggers(self):
        flags = detect_red_flags(
            "headache",
            "突然頭痛，接著單側肢體無力",
            {"reason": "頭痛"},
        )
        self.assertTrue(any(flag["code"] == "focal_neurologic_deficit" for flag in flags))

    def test_monocular_blurred_vision_triggers_before_semantic_extraction(self):
        complaint = "我頭痛，右眼突然看東西很模糊"
        flags = detect_red_flags(
            "headache",
            complaint,
            {"reason": complaint},
        )

        flag = next(
            item for item in flags if item["code"] == "acute_monocular_visual_change_combination"
        )
        self.assertEqual(flag["label"], "單眼視力模糊或喪失")
        self.assertEqual(flag["evidence"], "右眼、模糊")
        self.assertIn("視網膜動脈阻塞", flag["possible_conditions"])

    def test_negated_monocular_blurred_vision_does_not_trigger(self):
        complaint = "我頭痛，右眼看東西沒有模糊"

        self.assertEqual(
            detect_red_flags(
                "headache",
                complaint,
                {"reason": complaint},
            ),
            [],
        )

    def test_paraphrased_headache_combination_is_left_to_semantics(self):
        complaint = "我頭暈目眩，噁心想吐，頭痛到感覺快要裂開，視線模糊"
        flags = detect_red_flags(
            "headache",
            complaint,
            {"reason": complaint},
        )
        self.assertEqual(flags, [])

    def test_headache_with_nausea_alone_does_not_trigger(self):
        flags = detect_red_flags(
            "headache",
            "頭痛而且有點噁心想吐",
            {"reason": "頭痛而且有點噁心想吐"},
        )
        self.assertEqual(flags, [])


if __name__ == "__main__":
    unittest.main()
