"""Narrow FHIR R4 client for verified reads and conditional Composition create."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable


class FhirClientError(RuntimeError):
    """A sanitized FHIR transport or response failure."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class FhirWriteResult:
    resource_id: str
    version_id: str
    created: bool


class FhirClient:
    def __init__(
        self,
        base_url: str,
        *,
        bearer_token: str = "",
        timeout_seconds: float = 10.0,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ):
        normalized = base_url.strip().rstrip("/")
        parsed = urllib.parse.urlparse(normalized)
        if normalized and parsed.scheme not in {"http", "https"}:
            raise ValueError("FHIR write URL must use HTTP or HTTPS")
        self.base_url = normalized
        self.bearer_token = bearer_token.strip()
        self.timeout_seconds = timeout_seconds
        self._opener = opener

    @classmethod
    def from_environment(cls) -> "FhirClient":
        enabled = os.getenv("FHIR_WRITE_ENABLED", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        base_url = os.getenv("FHIR_WRITE_BASE_URL", "").strip() if enabled else ""
        try:
            timeout_seconds = float(os.getenv("FHIR_WRITE_TIMEOUT_SECONDS", "10"))
        except ValueError:
            timeout_seconds = 10.0
        return cls(
            base_url,
            bearer_token=os.getenv("FHIR_WRITE_BEARER_TOKEN", ""),
            timeout_seconds=max(1.0, min(timeout_seconds, 60.0)),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/fhir+json"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        return headers

    @staticmethod
    def _response_json(response) -> dict[str, Any]:
        try:
            payload = json.loads(response.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FhirClientError("FHIR server returned an invalid JSON response") from error
        if not isinstance(payload, dict):
            raise FhirClientError("FHIR server returned an invalid resource")
        return payload

    def _open(self, request: urllib.request.Request):
        if not self.enabled:
            raise FhirClientError("FHIR write integration is not configured")
        try:
            return self._opener(request, timeout=self.timeout_seconds)
        except urllib.error.HTTPError as error:
            # OperationOutcome can contain clinical text. Do not propagate it into
            # UI errors or logs; status is sufficient for controlled handling.
            raise FhirClientError(
                f"FHIR server rejected the request with HTTP {error.code}",
                status_code=error.code,
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise FhirClientError("FHIR server is unavailable") from error

    def read_resource(self, resource_type: str, resource_id: str) -> dict[str, Any]:
        path = "/".join(
            urllib.parse.quote(value, safe="") for value in (resource_type, resource_id)
        )
        request = urllib.request.Request(
            f"{self.base_url}/{path}",
            headers=self._headers(),
            method="GET",
        )
        with self._open(request) as response:
            payload = self._response_json(response)
        if payload.get("resourceType") != resource_type or payload.get("id") != resource_id:
            raise FhirClientError("FHIR server returned a mismatched resource")
        return payload

    def create_composition(self, composition: dict[str, Any]) -> FhirWriteResult:
        identifier = composition.get("identifier") or {}
        conditional_identifier = urllib.parse.quote(
            f"{identifier.get('system', '')}|{identifier.get('value', '')}",
            safe="",
        )
        headers = {
            **self._headers(),
            "Content-Type": "application/fhir+json",
            "Prefer": "return=representation",
            "If-None-Exist": f"identifier={conditional_identifier}",
        }
        request = urllib.request.Request(
            f"{self.base_url}/Composition",
            data=json.dumps(composition, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with self._open(request) as response:
            status = int(getattr(response, "status", response.getcode()))
            payload = self._response_json(response)
        if payload.get("resourceType") != "Composition" or not payload.get("id"):
            raise FhirClientError("FHIR server did not return the saved Composition")
        return FhirWriteResult(
            resource_id=str(payload["id"]),
            version_id=str(payload.get("meta", {}).get("versionId") or ""),
            created=status == 201,
        )
