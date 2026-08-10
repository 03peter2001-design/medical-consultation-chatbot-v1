"""Interview-length instrumentation must measure without recording content.

Interview length is dominated by the shared basic/history sections rather than by
the funnel, so the split has to be observable in deployment before any pruning
work can be aimed correctly. These tests pin both the arithmetic and the privacy
boundary: the summary carries counts, never answers.
"""

import unittest
from unittest.mock import patch

from app.services.amie_audit import (
    append_manual_amie_trace,
    interview_length_profile,
    save_amie_state,
)
from scripts.measure_interview_length import PROPOSED_BATCHES, run


def question(field, section, **extra):
    return {"field": field, "section": section, "prompt": f"{field}?", **extra}


QUESTIONNAIRE = [
    question("reason", "chief"),
    question("name", "basic"),
    question("gender", "basic"),
    question("smoke", "history"),
    question("chronic", "history"),
    question("start_type", "disease"),
    question("tender", "disease"),
    question("relieve", "disease"),
]


def session_with(*, prefilled=(), answered=(), turns=0):
    return {
        "questionnaire": list(QUESTIONNAIRE),
        "prefilled_fields": list(prefilled),
        "turn_count": turns,
        "transcript": [
            {"question": {"field": field, "prompt": f"{field}?"}, "answer": "測試"}
            for field in answered
        ],
        "data": {},
    }


class InterviewLengthProfileTests(unittest.TestCase):
    def test_counts_split_across_prefilled_asked_and_unasked(self):
        profile = interview_length_profile(
            session_with(
                prefilled=("name", "gender", "smoke"),
                answered=("reason", "chronic", "start_type", "tender"),
                turns=5,
            )
        )
        # ``reason`` is excluded: it opens every interview and can be neither
        # prefilled nor skipped.
        self.assertEqual(profile["questions_total"], 7)
        self.assertEqual(profile["prefilled"], 3)
        self.assertEqual(profile["asked"], 3)
        self.assertEqual(profile["unasked"], 1)
        self.assertEqual(profile["turns"], 5)
        self.assertAlmostEqual(profile["prefill_coverage"], 3 / 7, places=4)

    def test_section_split_is_reported_separately(self):
        profile = interview_length_profile(
            session_with(
                prefilled=("name", "gender", "smoke", "chronic"),
                answered=("reason", "start_type", "tender", "relieve"),
            )
        )
        self.assertEqual(
            profile["by_section"],
            {
                "basic": {"total": 2, "asked": 0, "prefilled": 2},
                "history": {"total": 2, "asked": 0, "prefilled": 2},
                "disease": {"total": 3, "asked": 3, "prefilled": 0},
            },
        )

    def test_a_prefilled_field_is_never_double_counted_as_asked(self):
        profile = interview_length_profile(session_with(prefilled=("name",), answered=("name",)))
        self.assertEqual(profile["prefilled"], 1)
        self.assertEqual(profile["asked"], 0)

    def test_empty_session_does_not_divide_by_zero(self):
        profile = interview_length_profile({})
        self.assertEqual(profile["questions_total"], 0)
        self.assertEqual(profile["prefill_coverage"], 0.0)
        self.assertEqual(profile["by_section"], {})

    def test_profile_carries_no_answer_text(self):
        """The summary is operational telemetry, so it must stay free of content."""
        session = session_with(
            prefilled=("name",),
            answered=("reason", "chronic", "start_type"),
        )
        session["transcript"][1]["answer"] = "我有肝硬化"
        rendered = repr(interview_length_profile(session))
        self.assertNotIn("肝硬化", rendered)
        self.assertNotIn("測試", rendered)


class ProfileWiringTests(unittest.TestCase):
    """The profile must be current after the turn it describes."""

    class _Result:
        triage_level = "routine"
        decision: dict = {}
        differential_hypotheses: list = []
        disease_assessment: dict = {}
        clinical_facts: list = []
        knowledge_gaps: list = []
        evidence_timeline: list = []
        rag_sources: list = []
        red_flags: list = []
        model_error = ""

    def test_manual_trace_path_still_updates_the_profile(self):
        """Route-guard and safety handoffs never call ``save_amie_state``."""
        session = session_with(prefilled=("name",), answered=(), turns=1)
        session["amie_state"] = {}
        append_manual_amie_trace(
            session,
            current_question=QUESTIONNAIRE[5],
            answer="突然發作",
            action="handoff",
            reason="測試",
        )
        self.assertEqual(session["amie_state"]["interview_length"]["asked"], 1)

    def test_appending_a_trace_counts_the_turn_it_just_recorded(self):
        session = session_with(prefilled=(), answered=(), turns=1)
        save_amie_state(session, self._Result())
        # save_amie_state runs before the trace append, so it cannot yet see it.
        self.assertEqual(session["amie_state"]["interview_length"]["asked"], 0)
        append_manual_amie_trace(
            session,
            current_question=QUESTIONNAIRE[6],
            answer="沒有",
            action="ask",
            reason="測試",
        )
        self.assertEqual(session["amie_state"]["interview_length"]["asked"], 1)
        self.assertEqual(session["data"]["_amie"]["interview_length"]["asked"], 1)


class BatchMeasurementValidityTests(unittest.TestCase):
    def test_every_answer_on_a_proposed_page_produces_its_structured_facts(self):
        # The live planner asks ``aggravate`` before ``tender`` on this synthetic
        # traversal. Grouping them makes tender a non-current answer and catches
        # simulators that merely put the extra value in ``data`` without running
        # its semantic mapping.
        proposal = {**PROPOSED_BATCHES, "chest": (("aggravate", "tender"),)}
        with patch.dict(PROPOSED_BATCHES, proposal, clear=True):
            result = run("chest", prefilled=(), batched=True)

        self.assertIn("aggravate", result["fields"])
        self.assertIn("tender", result["fields"])
        self.assertIn("pleuritic_pain", result["clinical_fact_codes"])
        self.assertIn("reproducible_tenderness", result["clinical_fact_codes"])


if __name__ == "__main__":
    unittest.main()
