"""Read-only metadata from the official local TW Core FHIR package.

This module never infers a terminology code from free text. It only confirms
that an incoming FHIR Coding uses a system referenced by TW Core.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

REFERENCE_DIR = Path(__file__).resolve().parents[1] / "terminology" / "twcore-1.0.0"
MANIFEST_PATH = REFERENCE_DIR / "package.json"
REFERENCE_VALUESETS = (
    REFERENCE_DIR / "ValueSet-condition-code-sct-tw.json",
    REFERENCE_DIR / "ValueSet-loinc-observation-code.json",
    REFERENCE_DIR / "ValueSet-vital-signs-tw.json",
)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def _compose_systems(value_set: dict[str, Any]) -> set[str]:
    return {
        include["system"]
        for include in value_set.get("compose", {}).get("include", [])
        if isinstance(include, dict) and include.get("system")
    }


@lru_cache(maxsize=1)
def terminology_reference() -> dict[str, Any]:
    manifest = _read_json(MANIFEST_PATH)
    systems: set[str] = set()
    for path in REFERENCE_VALUESETS:
        systems.update(_compose_systems(_read_json(path)))

    return {
        "package": manifest["name"],
        "version": manifest["version"],
        "canonical": manifest["canonical"],
        "fhir_versions": manifest.get("fhirVersions", []),
        "supported_systems": sorted(systems),
    }


def supported_coding_system(system: str) -> bool:
    return system in terminology_reference()["supported_systems"]


def filter_supported_codings(
    codings: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    """Keep source FHIR codings; do not create a text-to-code mapping."""
    if not codings:
        return []

    result: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for coding in codings:
        system = str(coding.get("system", "")).strip()
        code = str(coding.get("code", "")).strip()
        field = str(coding.get("field", "")).strip()
        if not system or not code or not supported_coding_system(system):
            continue
        key = (system, code, field)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "field": field[:64],
                "system": system,
                "code": code[:64],
                "display": str(coding.get("display", "")).strip()[:200],
                "source": "fhir",
            }
        )
    return result
