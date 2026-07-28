"""Pydantic request models used by the HTTP API."""

from pydantic import BaseModel, Field, validator

from domain.body_pain_regions import validate_pain_location_ids


class ClinicalCoding(BaseModel):
    field: str
    system: str
    code: str
    display: str = ""
    source: str = "fhir"

    @validator("field", "system", "code", "display", "source")
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
