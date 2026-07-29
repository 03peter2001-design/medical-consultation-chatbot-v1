import json
import unittest

from amie.engine import AMIEEngine
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


def decision(**overrides):
    payload = {
        "action": "ask",
        "next_field": "associated",
        "extracted_facts": {},
        "negated_findings": [],
        "differential_hypotheses": [],
        "knowledge_gaps": [],
        "needs_retrieval": False,
        "retrieval_query": "",
        "acknowledgement": "了解，我再確認一點。",
        "audit_reason": "優先確認伴隨症狀。",
    }
    payload.update(overrides)
    return payload


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

    def test_model_can_extract_multiple_facts_and_choose_dynamic_question(self):
        llm = FakeLLM(
            decision(
                extracted_facts={
                    "onset": "30分鐘前",
                    "aggravate": "走路時加重",
                },
                differential_hypotheses=[
                    {
                        "condition": "心血管相關胸痛",
                        "coding": {
                            "system": "http://snomed.info/sct",
                            "code": "29857009",
                            "display": "Chest pain",
                        },
                        "supporting_evidence": ["活動時胸悶"],
                        "opposing_evidence": [],
                    }
                ],
            )
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
        self.assertEqual(result.next_question["field"], "associated")
        self.assertEqual(result.data["onset_num"], "30")
        self.assertEqual(result.data["onset_unit"], "分鐘前")
        self.assertEqual(result.data["aggravate"], "走路時加重")
        self.assertEqual(len(result.evidence_timeline), 1)
        self.assertEqual(
            result.differential_hypotheses[0]["coding"],
            {
                "system": "http://snomed.info/sct",
                "code": "29857009",
                "display": "Chest pain",
                "source": "ai-suggested",
            },
        )
        self.assertEqual(result.decision["next_field"], "associated")
        self.assertEqual(
            result.decision["audit_reason"],
            "優先確認伴隨症狀。",
        )

    def test_typo_route_object_continues_instead_of_handoff(self):
        llm = FakeLLM(
            decision(next_field="associated"),
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

        self.assertEqual(result.action, "ask")
        self.assertNotEqual(result.action, "handoff")
        self.assertEqual(result.model_error, "")

    def test_multiple_route_objects_continue_instead_of_handoff(self):
        llm = FakeLLM(
            decision(next_field="associated"),
            semantic_response={
                "primary_symptom": "headache",
                "primary_evidence": "頭痛",
                "symptom_domains": [
                    {
                        "domain": "headache",
                        "evidence": "頭痛",
                    },
                    {
                        "domain": "abdomen",
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
        self.assertEqual(llm.calls, [])

    def test_semantic_safety_runs_before_planning_on_each_clinical_turn(self):
        llm = FakeLLM(
            semantic_response={
                "primary_symptom": "headache",
                "primary_evidence": "投痛",
                "symptom_domains": ["headache"],
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
                "route_candidates": ["headache"],
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
        self.assertEqual(
            result.red_flags[0]["code"],
            "semantic_severe_headache_visual_change",
        )
        self.assertEqual(len(llm.calls), 1)

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
        self.assertEqual(
            result.red_flags[0]["code"],
            "semantic_severe_headache_visual_change",
        )
        self.assertEqual(llm.calls, [])

    def test_standard_option_skips_extractor_but_planner_still_runs(self):
        llm = FakeLLM(decision(next_field="associated"))
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
        self.assertEqual(result.next_question["field"], "associated")
        self.assertEqual(len(llm.calls), 1)
        self.assertIn(
            "狀態感知問診規劃代理人",
            llm.calls[0]["messages"][0]["content"],
        )

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
        self.assertEqual(llm.calls, [])

    def test_invalid_model_output_falls_back_to_approved_question_bank(self):
        llm = FakeLLM("not-json")
        result = AMIEEngine(llm).run_turn(
            route="chest",
            answer="胸口不舒服",
            current_field="reason",
            data=self.base_data,
            questionnaire=self.questionnaire,
            prefilled_fields=self.prefilled,
        )

        self.assertEqual(result.action, "ask")
        self.assertIn(
            result.next_question["field"],
            {item["field"] for item in self.questionnaire},
        )
        self.assertTrue(result.model_error)

    def test_rag_is_conditional_and_mx_agent_can_refine_question(self):
        calls = []

        def retriever(query, **kwargs):
            calls.append((query, kwargs))
            return (
                "胸痛合併呼吸症狀需要釐清急性危險病因。",
                [{"title": "Chest Pain", "url": "https://example.test"}],
            )

        llm = FakeLLM(
            decision(
                next_field="quality",
                needs_retrieval=True,
                retrieval_query="chest pain red flags",
            ),
            decision(
                next_field="associated",
                needs_retrieval=False,
                audit_reason="依檢索內容優先確認呼吸與昏厥症狀。",
            ),
        )
        result = AMIEEngine(llm, retriever=retriever).run_turn(
            route="chest",
            answer="胸口不舒服",
            current_field="reason",
            data=self.base_data,
            questionnaire=self.questionnaire,
            prefilled_fields=self.prefilled,
        )

        self.assertEqual(result.next_question["field"], "associated")
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.rag_sources[0]["title"], "Chest Pain")
        self.assertEqual(len(llm.calls), 3)


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
