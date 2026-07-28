"""ASGI entry point used by ``uvicorn main:app``."""

from app.factory import app

__all__ = ["app"]
