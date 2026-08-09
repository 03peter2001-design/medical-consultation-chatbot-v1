"""Stable public error envelopes that keep internal exceptions server-side."""

from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

LOGGER = logging.getLogger("medical_consultation.errors")


def _correlation_id() -> str:
    return secrets.token_hex(12)


def _payload(detail: Any, error_code: str, correlation_id: str) -> dict[str, Any]:
    return {
        "detail": detail,
        "error_code": error_code,
        "correlation_id": correlation_id,
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        correlation_id = _correlation_id()
        # Pydantic's default error objects include the rejected input. Patient
        # answers and FHIR content must never be reflected merely to explain a
        # schema failure.
        issues = [
            {
                "type": issue.get("type"),
                "loc": list(issue.get("loc") or []),
                "msg": issue.get("msg") or "Invalid request value",
            }
            for issue in error.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_payload(issues, "REQUEST_VALIDATION_FAILED", correlation_id),
            headers={
                "X-Correlation-ID": correlation_id,
                "X-Error-Code": "REQUEST_VALIDATION_FAILED",
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        _request: Request,
        error: StarletteHTTPException,
    ) -> JSONResponse:
        correlation_id = _correlation_id()
        error_code = f"HTTP_{error.status_code}"
        headers = dict(error.headers or {})
        headers.update(
            {
                "X-Correlation-ID": correlation_id,
                "X-Error-Code": error_code,
            }
        )
        return JSONResponse(
            status_code=error.status_code,
            content=_payload(error.detail, error_code, correlation_id),
            headers=headers,
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, error: Exception) -> JSONResponse:
        correlation_id = _correlation_id()
        LOGGER.error(
            "unhandled request error path=%s correlation_id=%s error_type=%s",
            request.url.path,
            correlation_id,
            type(error).__name__,
        )
        return JSONResponse(
            status_code=500,
            content=_payload(
                "服務暫時無法處理要求，請稍後重試",
                "INTERNAL_SERVER_ERROR",
                correlation_id,
            ),
            headers={
                "X-Correlation-ID": correlation_id,
                "X-Error-Code": "INTERNAL_SERVER_ERROR",
            },
        )
