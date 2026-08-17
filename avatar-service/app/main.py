from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .engine import ANIMATION_MODEL, SPEECH_MODEL, AvatarEngine, AvatarEngineError

app = FastAPI(
    title="Local medical consultation avatar",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
engine = AvatarEngine()


class SynthesisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1200)
    language: Literal["mandarin", "minnan"] = "mandarin"
    animation_enabled: bool | None = None


class WarmupRequest(BaseModel):
    animation_enabled: bool | None = None


@app.get("/health")
def health():
    return engine.health()


@app.post("/v1/warmup")
async def warmup(payload: WarmupRequest | None = None):
    try:
        animation_enabled = payload.animation_enabled if payload else None
        return await run_in_threadpool(engine.warmup, animation_enabled)
    except AvatarEngineError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        print(f"[Avatar] warmup failed: {type(error).__name__}: {error}")
        raise HTTPException(status_code=500, detail="本地 Avatar 模型預載失敗") from error


@app.post("/v1/synthesize")
async def synthesize(payload: SynthesisRequest):
    try:
        video_path, cache_hit, animation_model = await run_in_threadpool(
            engine.render,
            payload.text,
            payload.language,
            payload.animation_enabled,
        )
    except AvatarEngineError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        print(f"[Avatar] render failed: {type(error).__name__}: {error}")
        raise HTTPException(status_code=500, detail="本地 Avatar 產生失敗") from error
    return FileResponse(
        video_path,
        media_type="video/mp4",
        headers={
            "Cache-Control": "private, max-age=3600",
            "X-Speech-Model": SPEECH_MODEL,
            "X-Animation-Model": animation_model or ANIMATION_MODEL,
            "X-Avatar-Cache": "hit" if cache_hit else "miss",
        },
    )
