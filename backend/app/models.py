"""Pydantic request models used by the HTTP API."""

from pydantic import BaseModel, Field, validator

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
    queue_number: str

    @validator("session_id")
    def session_id_not_empty(cls, value):
        if not value.strip():
            raise ValueError("session_id 不可為空")
        return value.strip()[:64]

    @validator("queue_number")
    def queue_number_format(cls, value):
        normalized = value.strip()
        if not normalized:
            raise ValueError("問診編號不可為空")
        return normalized[:16]


class SafetyRuleUpdateRequest(BaseModel):
    session_id: str
    expected_revision: str
    confirmation: str
    change_note: str
    safety_groups: list[dict]

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


class SafetyRuleAssistantRequest(BaseModel):
    message: str
    selected_labels: list[str]
    safety_groups: list[dict]
    history: list[dict] = Field(default_factory=list)

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
