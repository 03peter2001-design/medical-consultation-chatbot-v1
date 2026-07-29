import json
import unittest

from amie.chief_complaint import (
    ChiefComplaintExtractor,
    build_fhir_risk_profile,
    preferred_route,
    prioritized_routes,
)
from amie.clinical_facts import facts_from_assessment
from amie.models import ChiefComplaintAssessment
from amie.safety import detect_structured_red_flags


class FakeLLM:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def generate_text(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return (
            json.dumps(self.response, ensure_ascii=False)
            if isinstance(self.response, dict)
            else self.response
        )


def headache_payload(**overrides):
    payload = {
        "primary_symptom": "headache",
        "primary_evidence": "頭痛",
        "symptom_domains": [{"route": "headache", "evidence": "頭痛"}],
        "onset": {"value": "unknown", "evidence": ""},
        "severity": {
            "value": "severe",
            "evidence": "頭痛到感覺快要裂開",
        },
        "is_new_or_changed": {"value": "unknown", "evidence": ""},
        "findings": [
            {
                "code": "vertigo",
                "status": "present",
                "evidence": "頭暈目眩",
            },
            {
                "code": "nausea",
                "status": "present",
                "evidence": "噁心想吐",
            },
            {
                "code": "blurred_vision",
                "status": "present",
                "evidence": "視線模糊",
            },
        ],
        "negated_findings": [],
        "route_candidates": [{"route": "headache", "evidence": "頭痛"}],
        "uncertain_fields": ["onset"],
    }
    payload.update(overrides)
    return payload


class ChiefComplaintExtractorTests(unittest.TestCase):
    def test_extracts_whitelist_symptom_and_separate_time_dimensions(self):
        complaint = "我突然一陣一陣頭痛，而且已經持續很久"
        payload = headache_payload(
            primary_symptom="unknown",
            primary_evidence="",
            primary_symptom_code="headache",
            symptoms=[
                {
                    "code": "headache",
                    "evidence": "頭痛",
                }
            ],
            symptom_domains=[],
            onset={"value": "sudden", "evidence": "突然"},
            course={"value": "episodic", "evidence": "一陣一陣"},
            duration={"value": "prolonged", "evidence": "持續很久"},
            severity={"value": "unknown", "evidence": ""},
            findings=[],
            route_candidates=[],
        )

        assessment, error = ChiefComplaintExtractor(FakeLLM(payload)).extract(complaint)
        facts = facts_from_assessment(
            assessment,
            turn=1,
            source="test",
        )

        self.assertEqual(error, "")
        self.assertEqual(assessment.primary_symptom, "headache")
        self.assertEqual(assessment.primary_symptom_code, "headache")
        self.assertEqual(assessment.course.value, "episodic")
        self.assertEqual(assessment.duration.value, "prolonged")
        self.assertEqual(
            {fact["code"] for fact in facts},
            {
                "symptom_headache",
                "onset_sudden",
                "course_episodic",
                "duration_prolonged",
            },
        )

    def test_rejects_unknown_symptom_code_but_keeps_grounded_legacy_route(self):
        complaint = "我頭痛"
        payload = headache_payload(
            primary_symptom_code="model_invented_symptom",
            symptoms=[
                {
                    "code": "model_invented_symptom",
                    "evidence": "頭痛",
                }
            ],
            findings=[],
        )

        assessment, error = ChiefComplaintExtractor(FakeLLM(payload)).extract(complaint)

        self.assertEqual(error, "")
        self.assertEqual(assessment.primary_symptom, "headache")
        self.assertEqual(assessment.primary_symptom_code, "unknown")
        self.assertEqual(assessment.symptoms, [])

    def test_extracts_grounded_structure_and_route(self):
        complaint = "我頭暈目眩，噁心想吐，頭痛到感覺快要裂開，視線模糊"
        llm = FakeLLM(headache_payload())
        assessment, error = ChiefComplaintExtractor(llm).extract(complaint)

        self.assertEqual(error, "")
        self.assertEqual(preferred_route(assessment), "headache")
        self.assertEqual(assessment.severity.value, "severe")
        self.assertEqual(
            {finding.code for finding in assessment.findings},
            {"vertigo", "nausea", "blurred_vision"},
        )
        self.assertEqual(len(llm.calls), 1)

    def test_typo_and_mixed_language_are_normalized_but_evidence_is_raw(self):
        complaint = "我很dizzy，想兔，投痛到真的受不了"
        payload = headache_payload(
            primary_evidence="投痛",
            severity={
                "value": "severe",
                "evidence": "投痛到真的受不了",
            },
            findings=[
                {
                    "code": "dizziness_unspecified",
                    "status": "present",
                    "evidence": "dizzy",
                },
                {
                    "code": "nausea",
                    "status": "present",
                    "evidence": "想兔",
                },
            ],
        )
        llm = FakeLLM(payload)
        assessment, error = ChiefComplaintExtractor(llm).extract(complaint)

        self.assertEqual(error, "")
        self.assertEqual(assessment.primary_symptom, "headache")
        self.assertEqual(assessment.severity.value, "severe")
        self.assertEqual(
            {finding.code for finding in assessment.findings},
            {"dizziness_unspecified", "nausea"},
        )
        prompt = llm.calls[0]["messages"][1]["content"]
        self.assertIn("dizziness_unspecified", prompt)
        self.assertIn("常見錯字、同音字、中英混用", prompt)

    def test_accepts_evidenced_object_route_for_typo_complaint(self):
        complaint = "我兇悶"
        payload = {
            "primary_symptom": "chest",
            "primary_evidence": "兇悶",
            "symptom_domains": [
                {
                    "route": "chest",
                    "evidence": "兇悶",
                }
            ],
            "onset": {"value": "unknown", "evidence": ""},
            "severity": {"value": "unknown", "evidence": ""},
            "is_new_or_changed": {"value": "unknown", "evidence": ""},
            "findings": [],
            "negated_findings": [],
            "route_candidates": [
                {
                    "route": "chest",
                    "evidence": "兇悶",
                }
            ],
            "uncertain_fields": [],
        }

        assessment, error = ChiefComplaintExtractor(FakeLLM(payload)).extract(complaint)

        self.assertEqual(error, "")
        self.assertEqual(assessment.symptom_domains, ["chest"])
        self.assertEqual(assessment.route_candidates, ["chest"])
        self.assertEqual(preferred_route(assessment), "chest")

    def test_accepts_multiple_evidenced_symptom_domains(self):
        complaint = "我頭痛，肚子痛"
        payload = {
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
            "onset": {"value": "unknown", "evidence": ""},
            "severity": {"value": "unknown", "evidence": ""},
            "is_new_or_changed": {"value": "unknown", "evidence": ""},
            "findings": [],
            "negated_findings": [],
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
            "uncertain_fields": [],
        }

        assessment, error = ChiefComplaintExtractor(FakeLLM(payload)).extract(complaint)

        self.assertEqual(error, "")
        self.assertEqual(
            assessment.symptom_domains,
            ["headache", "abdomen"],
        )
        self.assertEqual(
            assessment.route_candidates,
            ["headache", "abdomen"],
        )
        self.assertEqual(preferred_route(assessment), "headache")

    def test_prioritizes_more_severe_symptom_and_retains_secondary_route(self):
        complaint = "我頭痛有點痛，肚子痛到受不了而且突然發作"
        payload = headache_payload(
            primary_evidence="頭痛",
            severity={"value": "mild", "evidence": "頭痛有點痛"},
            findings=[],
            symptom_domains=[
                {"route": "headache", "evidence": "頭痛"},
                {"route": "abdomen", "evidence": "肚子痛"},
            ],
            route_candidates=[
                {"route": "headache", "evidence": "頭痛"},
                {"route": "abdomen", "evidence": "肚子痛"},
            ],
            symptom_assessments=[
                {
                    "route": "headache",
                    "evidence": "頭痛",
                    "severity": {"value": "mild", "evidence": "頭痛有點痛"},
                },
                {
                    "route": "abdomen",
                    "evidence": "肚子痛",
                    "onset": {"value": "sudden", "evidence": "突然發作"},
                    "severity": {"value": "severe", "evidence": "肚子痛到受不了"},
                },
            ],
        )

        assessment, error = ChiefComplaintExtractor(FakeLLM(payload)).extract(complaint)

        self.assertEqual(error, "")
        self.assertEqual(prioritized_routes(assessment), ["abdomen", "headache"])
        self.assertEqual(preferred_route(assessment), "abdomen")

    def test_discards_object_route_without_verbatim_evidence(self):
        complaint = "我頭痛"
        payload = headache_payload(
            symptom_domains=[
                {
                    "route": "abdomen",
                    "evidence": "肚子痛",
                }
            ],
            route_candidates=[
                {
                    "route": "abdomen",
                    "evidence": "肚子痛",
                }
            ],
        )

        assessment, error = ChiefComplaintExtractor(FakeLLM(payload)).extract(complaint)

        self.assertEqual(error, "")
        self.assertEqual(assessment.symptom_domains, [])
        self.assertEqual(assessment.route_candidates, ["headache"])

    def test_discards_model_finding_without_verbatim_evidence(self):
        complaint = "我頭痛而且視線模糊"
        payload = headache_payload(
            severity={"value": "severe", "evidence": "痛到昏倒"},
            findings=[
                {
                    "code": "focal_weakness",
                    "status": "present",
                    "evidence": "左手無力",
                },
                {
                    "code": "blurred_vision",
                    "status": "present",
                    "evidence": "視線模糊",
                },
            ],
        )
        assessment, _ = ChiefComplaintExtractor(FakeLLM(payload)).extract(complaint)

        self.assertEqual(assessment.severity.value, "unknown")
        self.assertEqual(
            [finding.code for finding in assessment.findings],
            ["blurred_vision"],
        )

    def test_rejects_present_finding_when_original_text_negates_it(self):
        complaint = "我有頭痛，但是沒有視線模糊"
        payload = headache_payload(
            severity={"value": "unknown", "evidence": ""},
            findings=[
                {
                    "code": "blurred_vision",
                    "status": "present",
                    "evidence": "視線模糊",
                }
            ],
            negated_findings=[
                {
                    "code": "blurred_vision",
                    "status": "absent",
                    "evidence": "沒有視線模糊",
                }
            ],
        )
        assessment, _ = ChiefComplaintExtractor(FakeLLM(payload)).extract(complaint)

        self.assertEqual(assessment.findings, [])
        self.assertEqual(
            assessment.negated_findings[0].code,
            "blurred_vision",
        )

    def test_model_failure_returns_fallback_signal(self):
        assessment, error = ChiefComplaintExtractor(
            FakeLLM(RuntimeError("provider unavailable"))
        ).extract("頭痛")

        self.assertIsNone(assessment)
        self.assertIn("RuntimeError", error)


class StructuredSafetyTests(unittest.TestCase):
    def test_headache_blurred_vision_is_urgent_without_severe_pain(self):
        assessment = ChiefComplaintAssessment.model_validate(
            headache_payload(
                severity={"value": "unknown", "evidence": ""},
                findings=[
                    {
                        "code": "blurred_vision",
                        "status": "present",
                        "evidence": "看東西很模糊",
                    }
                ],
            )
        )

        flags = detect_structured_red_flags(assessment, {})

        self.assertTrue(any(flag["code"] == "semantic_headache_visual_change" for flag in flags))

    def test_semantic_monocular_visual_change_is_urgent_without_severe_pain(self):
        assessment = ChiefComplaintAssessment.model_validate(
            headache_payload(
                severity={"value": "unknown", "evidence": ""},
                findings=[
                    {
                        "code": "monocular_visual_change",
                        "status": "present",
                        "evidence": "右邊眼睛突然霧掉",
                    }
                ],
            )
        )

        flags = detect_structured_red_flags(assessment, {})

        self.assertTrue(any(flag["code"] == "semantic_monocular_visual_change" for flag in flags))

    def test_severe_headache_visual_combination_is_urgent(self):
        assessment = ChiefComplaintAssessment.model_validate(headache_payload())
        flags = detect_structured_red_flags(assessment, {})

        self.assertTrue(
            any(flag["code"] == "semantic_severe_headache_visual_change" for flag in flags)
        )

    def test_unlisted_paraphrases_trigger_through_semantic_structure(self):
        complaint = "我投痛到真的受不了，眼前霧成一片"
        payload = headache_payload(
            primary_evidence="投痛",
            severity={
                "value": "severe",
                "evidence": "投痛到真的受不了",
            },
            findings=[
                {
                    "code": "blurred_vision",
                    "status": "present",
                    "evidence": "眼前霧成一片",
                }
            ],
        )
        assessment, error = ChiefComplaintExtractor(FakeLLM(payload)).extract(complaint)
        flags = detect_structured_red_flags(assessment, {})

        self.assertEqual(error, "")
        self.assertTrue(
            any(flag["code"] == "semantic_severe_headache_visual_change" for flag in flags)
        )

    def test_local_route_can_anchor_structured_safety(self):
        payload = headache_payload(
            primary_symptom="unknown",
            primary_evidence="",
            route_candidates=[],
        )
        assessment = ChiefComplaintAssessment.model_validate(payload)
        flags = detect_structured_red_flags(
            assessment,
            {},
            route_hint="headache",
        )

        self.assertTrue(
            any(flag["code"] == "semantic_severe_headache_visual_change" for flag in flags)
        )

    def test_fhir_risk_profile_is_structured_not_raw_history(self):
        profile = build_fhir_risk_profile(
            {
                "current_meds": "目前服用 Apixaban",
                "chronic": "高血壓、乳癌治療中",
                "name": "不應進入風險資料",
            }
        )

        self.assertTrue(profile["antithrombotic_use"]["present"])
        self.assertTrue(profile["malignancy_history"]["present"])
        self.assertNotIn("不應進入", str(profile))

    def test_new_headache_combines_with_fhir_malignancy_risk(self):
        payload = headache_payload(
            is_new_or_changed={
                "value": "true",
                "evidence": "第一次出現",
            }
        )
        assessment = ChiefComplaintAssessment.model_validate(payload)
        profile = build_fhir_risk_profile({"chronic": "乳癌治療中"})
        flags = detect_structured_red_flags(assessment, profile)

        self.assertTrue(any(flag["code"] == "semantic_malignancy_history" for flag in flags))


if __name__ == "__main__":
    unittest.main()
