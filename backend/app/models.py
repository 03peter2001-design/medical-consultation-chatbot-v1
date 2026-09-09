"""Pydantic request models used by the HTTP API contract."""

import re
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, validator

from domain.body_pain_regions import validate_pain_location_ids

FHIR_ID_PATTERN = re.compile(r"[A-Za-z0-9\-.]{1,64}")
PHYSICIAN_SUMMARY_SECTION_KEYS = frozenset(
    {
        "Chief Complaint",
        "Present Illness",
        "Past History",
        "Drug History",
        "Allergy History",
        "Personal History",
        "Family History",
    }
)


def normalize_fhir_issuer(value: str) -> str:
    """Validate and normalize a configured SMART/FHIR issuer without network I/O."""

    normalized = str(value or "").strip()
    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("FHIR issuer 必須是無帳密、query 或 fragment 的 HTTP(S) URL")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("FHIR issuer port 格式不正確") from error
    host = parsed.hostname.casefold()
    if ":" in host:
        host = f"[{host}]"
    netloc = f"{host}:{port}" if port is not None else host
    return urlunsplit((parsed.scheme.casefold(), netloc, parsed.path.rstrip("/"), "", ""))


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
    clinical_codings: list[ClinicalCoding] = Field(default_factory=list, max_length=200)
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


class FhirPatientContext(BaseModel):
    """FHIR launch references accepted only by the explicit sandbox ingress."""

    patient_id: str = Field(min_length=1, max_length=64)
    encounter_id: str | None = Field(default=None, max_length=64)
    source: Literal["smart", "direct"]

    @field_validator("patient_id", "encounter_id")
    @classmethod
    def validate_fhir_id(cls, value):
        if value is None:
            return None
        normalized = value.strip()
        if not FHIR_ID_PATTERN.fullmatch(normalized):
            raise ValueError("FHIR resource id 格式不正確")
        return normalized


class LauncherInvitationCreateRequest(BaseModel):
    """Synthetic SMART launcher context accepted only by the local doctor route."""

    model_config = ConfigDict(extra="forbid")

    issuer: str = Field(min_length=1, max_length=2048)
    patient_id: str = Field(min_length=1, max_length=64)
    encounter_id: str | None = Field(default=None, max_length=64)
    prefill: PatientPrefill

    @field_validator("patient_id", "encounter_id")
    @classmethod
    def validate_fhir_id(cls, value):
        if value is None:
            return None
        normalized = value.strip()
        if not FHIR_ID_PATTERN.fullmatch(normalized):
            raise ValueError("FHIR resource id 格式不正確")
        return normalized

    @field_validator("issuer")
    @classmethod
    def validate_issuer(cls, value):
        return normalize_fhir_issuer(value)


class PhysicianSummarySection(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    label: str = Field(default="", max_length=100)
    value: str = Field(min_length=1, max_length=12_000)
    confirmed: Literal[True]

    @field_validator("key", "value")
    @classmethod
    def trim_required_summary_section(cls, value):
        normalized = value.strip()
        if not normalized:
            raise ValueError("醫師摘要欄位不可為空")
        return normalized

    @field_validator("label")
    @classmethod
    def trim_summary_label(cls, value):
        return value.strip()


class FhirCompositionCreateRequest(BaseModel):
    expected_updated_at: str = Field(min_length=1, max_length=64)
    sections: list[PhysicianSummarySection] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def exact_summary_sections(self):
        keys = [section.key for section in self.sections]
        if len(keys) != len(set(keys)):
            raise ValueError("醫師摘要欄位不可重複")
        if set(keys) != PHYSICIAN_SUMMARY_SECTION_KEYS:
            raise ValueError("醫師摘要必須包含完整七個欄位")
        self.expected_updated_at = self.expected_updated_at.strip()
        if not self.expected_updated_at:
            raise ValueError("病例版本資訊不可為空")
        return self


class InvitationPrefill(BaseModel):
    """Minimum patient context accepted only from the authenticated UCC server."""

    name: str | None = None
    gender: str | None = None
    birth_date: str | None = None
    blood_type: str | None = None
    allergies: str | None = None
    current_medications: str | None = None
    medical_history: str | None = None
    surgical_history: str | None = None

    @field_validator(
        "allergies",
        "current_medications",
        "medical_history",
        "surgical_history",
        mode="before",
    )
    @classmethod
    def normalize_history_value(cls, value):
        if value is None or isinstance(value, str):
            return value
        if isinstance(value, list):
            if len(value) > 100:
                raise ValueError("history list contains too many entries")
            normalized: list[str] = []
            for item in value:
                if not isinstance(item, str):
                    raise ValueError("history list entries must be strings")
                item = item.strip()
                if item:
                    normalized.append(item)
            return "; ".join(normalized) or None
        raise ValueError("history value must be a string or list of strings")

    @validator("*")
    def trim_invitation_value(cls, value):
        return value.strip()[:2000] if isinstance(value, str) and value.strip() else None

    def as_patient_prefill(self) -> dict[str, str]:
        aliases = {
            "allergies": "allergy",
            "current_medications": "current_meds",
            "medical_history": "chronic",
            "surgical_history": "surgery",
        }
        return {
            aliases.get(key, key): value
            for key, value in self.model_dump(exclude_none=True).items()
        }


class InvitationCreateRequest(BaseModel):
    institution_id: str = Field(min_length=1, max_length=100)
    patient_sno: str = Field(min_length=1, max_length=100)
    reg_sno: str = Field(min_length=1, max_length=100)
    prefill: InvitationPrefill = Field(default_factory=InvitationPrefill)

    @field_validator("institution_id", "patient_sno", "reg_sno", mode="before")
    @classmethod
    def normalize_reference(cls, value):
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise ValueError("reference must be a string or integer")
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("reference must not be empty")
        return normalized


class InvitationExchangeRequest(BaseModel):
    token: str = Field(min_length=32, max_length=512)

    @validator("token")
    def trim_token(cls, value):
        return value.strip()


class ChatRequest(BaseModel):
    message: str = ""
    session_id: str
    action: Literal["answer", "back"] = "answer"
    pain_location_ids: list[str] = Field(default_factory=list)
    patient_prefill: PatientPrefill | None = None
    fhir_context: FhirPatientContext | None = None
    language: Literal["mandarin", "minnan"] | None = None

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
