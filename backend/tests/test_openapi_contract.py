import asyncio
import json
import unittest
from pathlib import Path

from fastapi import BackgroundTasks

from app import runtime
from app.contracts import (
    ConsultationListResponse,
    HealthResponse,
    LoadPatientResponse,
    PatientChatResponse,
    RuleCenterResponse,
    SessionClearedResponse,
    StatusResponse,
)
from app.factory import API_V1_PREFIX, app
from app.models import ChatRequest, LoadPatientRequest
from app.routes.doctor import (
    doctor_reset,
    get_rule_center,
    list_consultations,
    load_patient,
    unload_patient,
)
from app.routes.patient import chat
from app.routes.system import health
from scripts.export_openapi import DEFAULT_OUTPUT, rendered_openapi

EXPECTED_OPERATIONS = {
    ("GET", "/v1/health"),
    ("POST", "/v1/transcribe"),
    ("POST", "/v1/chat"),
    ("GET", "/v1/doctor/rules"),
    ("GET", "/v1/doctor/terminology/snomed"),
    ("POST", "/v1/doctor/rules/authorize"),
    ("POST", "/v1/doctor/rules/assistant"),
    ("PUT", "/v1/doctor/rules/safety"),
    ("PUT", "/v1/doctor/rules/fact-labels"),
    ("PUT", "/v1/doctor/rules/disease-profiles/{route}"),
    ("GET", "/v1/doctor/consultations"),
    ("DELETE", "/v1/doctor/consultations/{queue_number}"),
    ("POST", "/v1/doctor/load_patient"),
    ("DELETE", "/v1/doctor/patient/{session_id}"),
    ("POST", "/v1/doctor/chat"),
    ("DELETE", "/v1/doctor/session/{session_id}"),
}


class OpenApiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = app.openapi()

    def test_only_versioned_routes_are_published(self):
        self.assertEqual(API_V1_PREFIX, "/v1")
        operations = {
            (method.upper(), path)
            for path, methods in self.schema["paths"].items()
            for method in methods
        }
        self.assertEqual(operations, EXPECTED_OPERATIONS)
        self.assertTrue(all(path.startswith("/v1/") for _, path in operations))

    def test_every_operation_has_a_typed_success_response(self):
        operation_ids = []
        for methods in self.schema["paths"].values():
            for operation in methods.values():
                operation_ids.append(operation["operationId"])
                self.assertTrue(operation.get("summary"))
                self.assertTrue(operation.get("tags"))
                response = operation["responses"]["200"]
                schema = response["content"]["application/json"]["schema"]
                self.assertTrue(schema.get("$ref"), operation["operationId"])
        self.assertEqual(len(operation_ids), len(set(operation_ids)))

    def test_legacy_aliases_remain_runtime_only(self):
        self.assertNotIn("/health", self.schema["paths"])
        compatibility_routers = [
            route
            for route in app.routes
            if getattr(getattr(route, "include_context", None), "include_in_schema", True) is False
        ]
        self.assertEqual(len(compatibility_routers), 3)

    def test_representative_responses_satisfy_the_published_models(self):
        HealthResponse.model_validate(health())
        RuleCenterResponse.model_validate(get_rule_center())
        ConsultationListResponse.model_validate(
            list_consultations(search="", limit=1, offset=0),
        )
        LoadPatientResponse.model_validate(
            load_patient(
                LoadPatientRequest(session_id="contract-test", queue_number="00000"),
            )
        )
        PatientChatResponse.model_validate(
            asyncio.run(
                chat(
                    ChatRequest(session_id="contract-patient", message=""),
                    BackgroundTasks(),
                )
            )
        )
        StatusResponse.model_validate(unload_patient("contract-test"))
        SessionClearedResponse.model_validate(doctor_reset("contract-test"))
        runtime.sessions.pop("contract-patient", None)

    def test_committed_contract_matches_application(self):
        self.assertEqual(DEFAULT_OUTPUT, Path(__file__).resolve().parents[2] / "docs/openapi.json")
        self.assertTrue(DEFAULT_OUTPUT.is_file())
        committed = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
        generated = json.loads(rendered_openapi())
        self.assertEqual(committed, generated)


if __name__ == "__main__":
    unittest.main()
