from __future__ import annotations

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


@app.get("/health")
def health():
    return engine.health()


@app.post("/v1/synthesize")
async def synthesize(payload: SynthesisRequest):
    try:
        video_path, cache_hit, animation_model = await run_in_threadpool(
            engine.render,
            payload.text,
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
