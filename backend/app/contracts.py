"""Response and error schemas exposed through the versioned OpenAPI contract."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models import ClinicalCoding, SafetyRuleGroup


class ValidationIssue(BaseModel):
    type: str | None = None
    loc: list[str | int] = Field(default_factory=list)
    msg: str
    input: Any | None = None
    ctx: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    """FastAPI HTTP and validation error envelope."""

    detail: str | list[ValidationIssue]


ERROR_DESCRIPTIONS = {
    400: "The request cannot be processed in its current state.",
    401: "Authentication is required or has expired.",
    403: "The caller is not authorized for this operation.",
    404: "The requested consultation does not exist.",
    409: "The submitted revision conflicts with the current revision.",
    413: "The uploaded audio exceeds the accepted size limit.",
    422: "Request validation or domain validation failed.",
    500: "An internal dependency or model operation failed.",
    503: "A required configured service is unavailable.",
}


def error_responses(
    *status_codes: int,
    descriptions: dict[int, str] | None = None,
) -> dict[int | str, dict[str, Any]]:
    """Build consistent OpenAPI error declarations without changing runtime JSON."""

    descriptions = descriptions or {}
    return {
        status_code: {
            "model": ErrorResponse,
            "description": descriptions.get(
                status_code,
                ERROR_DESCRIPTIONS[status_code],
            ),
        }
        for status_code in status_codes
    }


class RagQueryTranslationStatus(BaseModel):
    enabled: bool
    provider: str
    query_mode: str
    model: str


class HealthResponse(BaseModel):
    status: Literal["ok"]
    interview_engine: Literal["amie", "legacy"]
    llm_provider: str
    llm_model: str
    sessions: int = Field(ge=0)
    doctor_sessions: int = Field(ge=0)
    stored_consultations: int = Field(ge=0)
    consultation_database: str
    rag_enabled: bool
    rag_index_version: str
    rag_collections: list[str]
    rag_legacy_available: bool
    rag_query_translation: RagQueryTranslationStatus


class TranscriptionResponse(BaseModel):
    text: str


class InvitationResponse(BaseModel):
    invite_id: str
    public_url: str
    expires_at: str
    status: Literal["active"]


class InvitationExchangeResponse(BaseModel):
    status: Literal["ok"]
    expires_at: str


class PatientSessionResponse(BaseModel):
    status: Literal["active"]
    expires_at: str
    interview_session_id: str
    consultation_id: str | None = None
    completed: bool = False


class ProgressResponse(BaseModel):
    current: int = Field(ge=0)
    total: int = Field(ge=1)
    percent: int = Field(ge=0, le=100)


class TriageResponse(BaseModel):
    level: Literal["routine", "urgent"]
    message: str
    possible_conditions: list[str] = Field(default_factory=list)


class QuestionnaireMetadata(BaseModel):
    section: str
    label: str
    route: str | None = None
    route_label: str


class PatientChatResponse(BaseModel):
    reply: str
    session_id: str
    completed: bool
    user_display: str | None = None
    step: int
    queue_number: str | None = None
    triage: TriageResponse
    question_input: dict[str, Any] | None = None
    questionnaire: QuestionnaireMetadata | None = None
    progress: ProgressResponse
    amie_debug: dict[str, Any] | None = None


class EvidenceSource(BaseModel):
    title: str
    source: str = ""
    url: str = ""
    route: str = ""


class DoctorChatResponse(BaseModel):
    reply: str
    session_id: str
    sources: list[EvidenceSource]
    patient_loaded: str | None = None
    patient_loaded_consultation_id: str | None = None
    mode: Literal["chat", "structured_note"]


class StatusResponse(BaseModel):
    status: Literal["ok"]


class SessionClearedResponse(StatusResponse):
    cleared: str


class ConsultationDeletedResponse(BaseModel):
    status: Literal["deleted"]
    consultation_id: str
    consultation_date: str
    registration_number: str
    queue_number: str


class ConsultationSummary(BaseModel):
    consultation_id: str
    consultation_date: str
    registration_number: str
    queue_number: str
    patient_name: str
    type: str
    reason: str
    gender: str
    age: str
    triage_level: Literal["routine", "urgent"]
    workflow_status: str
    has_structured_note: bool
    created_at: str


class ConsultationListResponse(BaseModel):
    items: list[ConsultationSummary]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class LoadPatientResponse(BaseModel):
    consultation_id: str
    consultation_date: str
    registration_number: str
    queue_number: str
    type: str
    reason: str
    patient_data: dict[str, Any]
    clinical_codings: list[ClinicalCoding]
    terminology_reference: dict[str, Any]
    summary: str
    report: str
    structured_note: str | None = None
    structured_sources: list[EvidenceSource]
    pain_locations: list[dict[str, Any]]
    amie_state: dict[str, Any]
    disease_assessment: dict[str, Any]
    legacy_differential_hypotheses: list[Any]
    amie_trace: list[dict[str, Any]]
    chief_assessment: dict[str, Any] | None = None
    triage_level: Literal["routine", "urgent"]
    workflow_status: str
    summary_error: str
    rag_enabled: bool
    created_at: str


class SnomedConcept(BaseModel):
    system: str
    code: str
    display: str


class SnomedSearchResponse(BaseModel):
    query: str
    mode: Literal["code", "text"]
    source: str | None = None
    release_date: str | None = None
    total: int = Field(ge=0)
    items: list[SnomedConcept]
    limit: int = Field(ge=1, le=50)
    offset: int = Field(ge=0)
    has_more: bool


class RuleAuthorizationResponse(BaseModel):
    authorized: Literal[True]


class RuleFlowStep(BaseModel):
    step: int = Field(ge=1)
    name: str
    description: str


class FactCatalogItem(BaseModel):
    code: str
    description: str
    is_safety: bool
    conditional_safety_rule_count: int = Field(ge=0)
    categories: list[str]


class RuleCenterResponse(BaseModel):
    schema_version: int = Field(ge=1)
    revision: str
    edit_enabled: bool
    confirmation_text: str
    fact_confirmation_text: str
    disease_confirmation_text: str
    max_clue_weight: int = Field(ge=1)
    flow: list[RuleFlowStep]
    routes: list[dict[str, Any]]
    fact_count: int = Field(ge=0)
    fact_codes: list[str]
    fact_catalog: list[FactCatalogItem]
    safety_groups: list[SafetyRuleGroup]


class RuleAssistantResponse(BaseModel):
    reply: str
    safety_groups: list[SafetyRuleGroup]
    saved: Literal[False]
