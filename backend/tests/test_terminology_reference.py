import unittest

from domain.terminology_reference import (
    filter_supported_codings,
    terminology_reference,
)


class TerminologyReferenceTests(unittest.TestCase):
    def test_reads_official_twcore_manifest_and_systems(self):
        reference = terminology_reference()

        self.assertEqual(reference["package"], "tw.gov.mohw.twcore")
        self.assertEqual(reference["version"], "1.0.0")
        self.assertEqual(reference["fhir_versions"], ["4.0.1"])
        self.assertIn(
            "http://snomed.info/sct",
            reference["supported_systems"],
        )
        self.assertIn(
            "http://loinc.org",
            reference["supported_systems"],
        )

    def test_preserves_only_source_codings_supported_by_twcore(self):
        result = filter_supported_codings(
            [
                {
                    "field": "chronic",
                    "system": "http://snomed.info/sct",
                    "code": "38341003",
                    "display": "Hypertensive disorder",
                    "text": "高血壓",
                },
                {
                    "field": "blood_type",
                    "system": "http://loinc.org",
                    "code": "882-1",
                    "display": "ABO and Rh group [Type] in Blood",
                },
                {
                    "field": "chronic",
                    "system": "https://example.test/local-codes",
                    "code": "made-up",
                },
            ]
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["code"], "38341003")
        self.assertEqual(result[0]["text"], "高血壓")
        self.assertEqual(result[1]["code"], "882-1")
        self.assertTrue(all(coding["source"] == "fhir" for coding in result))

    def test_fhir_prefill_keeps_codings_out_of_questionnaire_fields(self):
        from app.models import ChatRequest
        from app.routes.patient import _prefilled_patient_data

        request = ChatRequest(
            session_id="terminology-test",
            patient_prefill={
                "source": "fhir",
                "name": "測試病人",
                "chronic": "高血壓",
                "clinical_codings": [
                    {
                        "field": "chronic",
                        "system": "http://snomed.info/sct",
                        "code": "38341003",
                        "display": "Hypertensive disorder",
                    }
                ],
            },
        )

        data, prefilled_fields = _prefilled_patient_data(request)

        self.assertEqual(data["chronic"], "高血壓")
        self.assertEqual(
            data["_clinical_codings"][0]["code"],
            "38341003",
        )
        self.assertNotIn("clinical_codings", prefilled_fields)


if __name__ == "__main__":
    unittest.main()
