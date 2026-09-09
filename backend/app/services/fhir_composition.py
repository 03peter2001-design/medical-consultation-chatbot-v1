"""Build the clinician-reviewed TW Core Composition write payload."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any

from app.models import PhysicianSummarySection

TW_CORE_COMPOSITION_PROFILE = (
    "https://twcore.mohw.gov.tw/ig/twcore/StructureDefinition/Composition-twcore"
)
DEFAULT_COMPOSITION_IDENTIFIER_SYSTEM = "https://medical-consultation.local/fhir/consultations"
DEFAULT_CLINICIAN_IDENTIFIER_SYSTEM = "https://medical-consultation.local/fhir/clinicians"


def _narrative(value: str) -> dict[str, str]:
    escaped_value = escape(value, quote=True).replace("\n", "<br/>")
    return {
        "status": "additional",
        "div": f'<div xmlns="http://www.w3.org/1999/xhtml"><p>{escaped_value}</p></div>',
    }


def build_tw_core_composition(
    *,
    consultation_id: str,
    patient_id: str,
    encounter_id: str | None,
    sections: list[PhysicianSummarySection],
    author_reference: str | None,
    author_identifier: str | None,
    author_display: str,
    identifier_system: str = DEFAULT_COMPOSITION_IDENTIFIER_SYSTEM,
    clinician_identifier_system: str = DEFAULT_CLINICIAN_IDENTIFIER_SYSTEM,
    authored_at: datetime | None = None,
) -> dict[str, Any]:
    """Create one preliminary document resource from confirmed summary sections."""

    if not author_reference and not author_identifier:
        raise ValueError("FHIR Composition 缺少可驗證的醫師作者")
    if author_reference:
        author: dict[str, Any] = {
            "reference": author_reference,
            "display": author_display,
        }
    else:
        author = {
            "identifier": {
                "system": clinician_identifier_system,
                "value": author_identifier,
            },
            "display": author_display,
        }

    timestamp = authored_at or datetime.now(timezone.utc)
    composition: dict[str, Any] = {
        "resourceType": "Composition",
        "meta": {"profile": [TW_CORE_COMPOSITION_PROFILE]},
        "identifier": {
            "system": identifier_system,
            "value": consultation_id,
        },
        # Confirmation in this UI is a clinical review step, not an institutional
        # electronic signature. Keep the document preliminary until such a workflow exists.
        "status": "preliminary",
        "type": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "11503-0",
                    "display": "Medical records",
                }
            ]
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "date": timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "author": [author],
        "title": "AI pre-consultation clinician-reviewed summary",
        "section": [
            {
                "title": section.key,
                "text": _narrative(section.value),
            }
            for section in sections
        ],
    }
    if encounter_id:
        composition["encounter"] = {"reference": f"Encounter/{encounter_id}"}
    return composition
