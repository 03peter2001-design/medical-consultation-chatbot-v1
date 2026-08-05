"""Pydantic request models used by the HTTP API contract."""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator, validator

from domain.body_pain_regions import validate_pain_location_ids


class ClinicalCoding(BaseModel):
    field: str
    system: str
    code: str
    display: str = ""
    text: str = ""
    source: str = "fhir"

    @validator("field", "system", "code", "display", "text", "source")
    def trim_coding_value(cls, value):
        return value.strip()[:200]


class PatientPrefill(BaseModel):
    source: str = "fhir"
    clinical_codings: list[ClinicalCoding] = Field(default_factory=list)
    name: str | None = None
    gender: str | None = None
    birth_date: str | None = None
    blood_type: str | None = None
    smoke: str | None = None
    chronic: str | None = None
    past_meds: str | None = None
    current_meds: str | None = None
    allergy: str | None = None
    cardio: str | None = None
    neuro: str | None = None
    abdomen_hx: str | None = None
    surgery: str | None = None

    @validator(
        "name",
        "gender",
        "birth_date",
        "blood_type",
        "smoke",
        "chronic",
        "past_meds",
        "current_meds",
        "allergy",
        "cardio",
        "neuro",
        "abdomen_hx",
        "surgery",
    )
    def trim_prefill_value(cls, value):
        return value.strip()[:500] if value else None


class ChatRequest(BaseModel):
    message: str = ""
    session_id: str
    pain_location_ids: list[str] = Field(default_factory=list)
    patient_prefill: PatientPrefill | None = None

    @validator("session_id")
    def session_id_not_empty(cls, value):
        if not value.strip():
            raise ValueError("session_id 不可為空")
        return value.strip()[:64]

    @validator("message")
    def message_length(cls, value):
        return value.strip()[:500]

    @validator("pain_location_ids")
    def pain_location_ids_valid(cls, value):
        return validate_pain_location_ids(value)


class DoctorChatRequest(BaseModel):
    message: str = ""
    session_id: str
    mode: str = "chat"

    @validator("session_id")
    def session_id_not_empty(cls, value):
        if not value.strip():
            raise ValueError("session_id 不可為空")
        return value.strip()[:64]

    @validator("message")
    def message_length(cls, value):
        return value.strip()[:1000]

    @validator("mode")
    def mode_valid(cls, value):
        normalized = (value or "chat").strip().lower()
        return normalized if normalized in ("chat", "structured_note") else "chat"


class LoadPatientRequest(BaseModel):
    session_id: str
    consultation_id: str | None = None
    consultation_date: str | None = None
    registration_number: str | None = None
    queue_number: str | None = None

    @validator("session_id")
    def session_id_not_empty(cls, value):
        if not value.strip():
            raise ValueError("session_id 不可為空")
        return value.strip()[:64]

    @validator(
        "consultation_id",
        "consultation_date",
        "registration_number",
        "queue_number",
    )
    def trim_consultation_reference(cls, value):
        return value.strip()[:32] if value else None

    @model_validator(mode="after")
    def consultation_reference_present(self):
        if self.consultation_id:
            return self
        if self.registration_number or self.queue_number:
            return self
        raise ValueError("請提供 consultation_id 或掛號編號")


class SafetyRuleUpdateRequest(BaseModel):
    session_id: str
    expected_revision: str
    confirmation: str
    change_note: str
    safety_groups: list["SafetyRuleGroup"]

    @validator("session_id")
    def rule_session_id_not_empty(cls, value):
        normalized = value.strip()
        if not normalized:
            raise ValueError("session_id 不可為空")
        return normalized[:64]

    @validator("expected_revision")
    def revision_format(cls, value):
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(
            character not in "0123456789abcdef" for character in normalized
        ):
            raise ValueError("expected_revision 格式不正確")
        return normalized

    @validator("confirmation", "change_note")
    def trim_rule_update_text(cls, value):
        return value.strip()[:500]


class FactLabelUpdateRequest(BaseModel):
    session_id: str
    expected_revision: str
    confirmation: str
    change_note: str
    fact_labels: list["FactLabelUpdate"]

    @validator("session_id")
    def fact_session_id_not_empty(cls, value):
        normalized = value.strip()
        if not normalized:
            raise ValueError("session_id 不可為空")
        return normalized[:64]

    @validator("expected_revision")
    def fact_revision_format(cls, value):
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(
            character not in "0123456789abcdef" for character in normalized
        ):
            raise ValueError("expected_revision 格式不正確")
        return normalized

    @validator("confirmation", "change_note")
    def trim_fact_update_text(cls, value):
        return value.strip()[:500]


class DiseaseProfileUpdateRequest(BaseModel):
    session_id: str
    expected_revision: str
    confirmation: str
    change_note: str
    reviewer: str
    profiles: list["DiseaseProfileUpdate"]

    @validator("session_id")
    def profile_session_id_not_empty(cls, value):
        normalized = value.strip()
        if not normalized:
            raise ValueError("session_id 不可為空")
        return normalized[:64]

    @validator("expected_revision")
    def profile_revision_format(cls, value):
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(
            character not in "0123456789abcdef" for character in normalized
        ):
            raise ValueError("expected_revision 格式不正確")
        return normalized

    @validator("confirmation", "change_note", "reviewer")
    def trim_profile_update_text(cls, value):
        return value.strip()[:500]


class SafetyRuleAssistantRequest(BaseModel):
    message: str
    selected_labels: list[str]
    safety_groups: list["SafetyRuleGroup"]
    history: list["AssistantHistoryItem"] = Field(default_factory=list)

    @validator("message")
    def assistant_message_length(cls, value):
        normalized = value.strip()
        if not normalized:
            raise ValueError("message 不可為空")
        return normalized[:1000]

    @validator("selected_labels")
    def selected_rule_count(cls, value):
        normalized = [item.strip()[:80] for item in value if isinstance(item, str) and item.strip()]
        if not 1 <= len(normalized) <= 5:
            raise ValueError("每次請勾選 1 至 5 個 Safety 標籤")
        return normalized


class AssistantHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1000)


class SafetyRuleItem(BaseModel):
    """Editable Safety rule shape shared by rule reads and writes."""

    code: str
    kind: Literal["phrase", "combination", "structured"]
    scope: Literal["universal", "route", "combination", "structured"]
    route: str = ""
    level: str = "urgent"
    terms: list[str] | None = None
    all_term_groups: list[dict[str, list[str]]] | None = None
    when: dict[str, Any] | None = None


class SafetyRuleGroup(BaseModel):
    original_label: str
    label: str
    possible_conditions: list[str]
    rules: list[SafetyRuleItem]
    categories: list[str] = Field(default_factory=list)
    applicable_routes: list[str] = Field(default_factory=list)


class FactLabelUpdate(BaseModel):
    code: str
    description: str = Field(min_length=1, max_length=300)
    is_safety: bool


class DiseaseClueUpdate(BaseModel):
    fact: str
    status: Literal["present", "absent"]
    direction: Literal["support", "oppose"]
    weight: int = Field(ge=1)


class DiseaseProfileUpdate(BaseModel):
    id: str
    clues: list[DiseaseClueUpdate]
    safety_rule_codes: list[str]


# Resolve the forward references while keeping the public request classes near
# the top of this module, where existing imports expect to find them.
SafetyRuleUpdateRequest.model_rebuild()
FactLabelUpdateRequest.model_rebuild()
DiseaseProfileUpdateRequest.model_rebuild()
SafetyRuleAssistantRequest.model_rebuild()
