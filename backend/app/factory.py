"""FastAPI application factory and router composition."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.doctor import router as doctor_router
from app.routes.patient import router as patient_router
from app.routes.system import router as system_router
from app.services.seed_data import seed_test_patient


def create_app() -> FastAPI:
    seed_test_patient()
    app = FastAPI(title="AI 預問診系統", version="2.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(system_router)
    app.include_router(patient_router)
    app.include_router(doctor_router)
    return app


app = create_app()
