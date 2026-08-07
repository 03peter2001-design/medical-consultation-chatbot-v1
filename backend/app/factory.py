"""FastAPI application factory and router composition."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.doctor import router as doctor_router
from app.routes.invitations import router as invitation_router
from app.routes.patient import router as patient_router
from app.routes.system import router as system_router
from app.services.seed_data import seed_test_patient

API_V1_PREFIX = "/v1"

OPENAPI_TAGS = [
    {
        "name": "system",
        "description": "Service health and speech transcription.",
    },
    {
        "name": "patient",
        "description": "Patient-facing pre-consultation workflow.",
    },
    {
        "name": "doctor",
        "description": "Physician consultation, terminology, and governance operations.",
    },
]


def create_app() -> FastAPI:
    seed_test_patient()
    app = FastAPI(
        title="AI 預問診系統 API",
        version="1.0.0",
        description=(
            "Versioned contract for the patient pre-consultation and physician "
            "workspace. Use `/v1` routes for new integrations; unversioned routes "
            "remain temporarily available as a compatibility layer."
        ),
        openapi_tags=OPENAPI_TAGS,
    )
    allowed_origins = [
        origin.strip()
        for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ]
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
            expose_headers=[
                "X-Speech-Model",
                "X-Animation-Model",
                "X-Avatar-Cache",
            ],
        )
    app.include_router(system_router, prefix=API_V1_PREFIX)
    app.include_router(patient_router, prefix=API_V1_PREFIX)
    app.include_router(doctor_router, prefix=API_V1_PREFIX)
    app.include_router(invitation_router, prefix=API_V1_PREFIX)

    # Keep existing clients working during the v1 migration. These aliases are
    # intentionally excluded from OpenAPI so the published contract has one
    # canonical path for every operation.
    aliases_enabled = os.getenv("ENABLE_UNVERSIONED_ALIASES", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if aliases_enabled:
        app.include_router(system_router, include_in_schema=False)
        app.include_router(patient_router, include_in_schema=False)
        app.include_router(doctor_router, include_in_schema=False)
    return app


app = create_app()
