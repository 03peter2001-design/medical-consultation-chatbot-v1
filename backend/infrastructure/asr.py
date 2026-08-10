"""Speech transcription backed by the local Breeze-ASR model."""

from __future__ import annotations

import gc
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from threading import Lock
from time import perf_counter
from typing import Any

import numpy as np

DEFAULT_MODEL_ID = "MediaTek-Research/Breeze-ASR-26"
SAMPLE_RATE = 16_000


class AudioDecodeError(ValueError):
    """Raised when an uploaded recording cannot be decoded safely."""


class ASRUnavailableError(RuntimeError):
    """Raised when the configured speech model cannot be loaded."""


def decode_audio(
    audio_bytes: bytes,
    *,
    max_seconds: int,
    ffmpeg_binary: str = "ffmpeg",
) -> np.ndarray:
    """Convert a browser recording to 16 kHz mono float32 PCM with ffmpeg."""

    if not audio_bytes:
        raise AudioDecodeError("錄音內容是空的")
    if not shutil.which(ffmpeg_binary):
        raise ASRUnavailableError("伺服器尚未安裝 ffmpeg，無法解碼錄音")

    # Decode at most one extra second. This bounds memory use while still
    # allowing us to reject, rather than silently truncate, overlong audio.
    command = [
        ffmpeg_binary,
        "-v",
        "error",
        "-nostdin",
        "-i",
        "pipe:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-t",
        str(max_seconds + 1),
        "-f",
        "s16le",
        "pipe:1",
    ]
    try:
        result = subprocess.run(
            command,
            input=audio_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=max(20, min(90, max_seconds + 15)),
        )
    except subprocess.TimeoutExpired as error:
        raise AudioDecodeError("錄音解碼逾時，請縮短錄音後重試") from error

    if result.returncode != 0 or not result.stdout:
        raise AudioDecodeError("無法讀取錄音格式，請重新錄音")

    pcm = np.frombuffer(result.stdout, dtype="<i2")
    duration = pcm.size / SAMPLE_RATE
    if duration > max_seconds + 0.05:
        raise AudioDecodeError(f"錄音時間過長（上限 {max_seconds} 秒）")
    return pcm.astype(np.float32) / 32768.0


class SpeechTranscriber:
    """Lazy, process-local Breeze-ASR pipeline with an optional cloud fallback."""

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        llm_client: Any | None = None,
        pipeline_factory: Callable[..., Any] | None = None,
        torch_module: Any | None = None,
        audio_decoder: Callable[..., np.ndarray] = decode_audio,
    ) -> None:
        self._env = env if env is not None else os.environ
        self.provider = self._env.get("ASR_PROVIDER", "breeze").strip().lower()
        if self.provider not in {"breeze", "llm"}:
            raise RuntimeError("ASR_PROVIDER 僅支援 breeze 或 llm")

        self.model_id = self._env.get("BREEZE_ASR_MODEL", DEFAULT_MODEL_ID).strip()
        self.requested_device = self._env.get("BREEZE_ASR_DEVICE", "auto").strip().lower()
        if self.requested_device not in {"auto", "cpu", "cuda"}:
            raise RuntimeError("BREEZE_ASR_DEVICE 僅支援 auto、cpu 或 cuda")
        self.release_gpu_after_transcribe = self._env.get(
            "BREEZE_ASR_RELEASE_GPU_AFTER_TRANSCRIBE",
            "false",
        ).strip().lower() in {"1", "true", "yes", "on"}
        self.max_seconds = int(self._env.get("ASR_MAX_AUDIO_SECONDS", "120"))
        if not 1 <= self.max_seconds <= 600:
            raise RuntimeError("ASR_MAX_AUDIO_SECONDS 必須介於 1 到 600")
        self.min_rms = float(self._env.get("ASR_MIN_AUDIO_RMS", "0.001"))
        if not 0 <= self.min_rms <= 1:
            raise RuntimeError("ASR_MIN_AUDIO_RMS 必須介於 0 到 1")

        self._llm_client = llm_client
        self._pipeline_factory = pipeline_factory
        self._torch = torch_module
        self._audio_decoder = audio_decoder
        self._pipeline: Any | None = None
        self._actual_device = "not-loaded"
        self._load_lock = Lock()
        self._inference_lock = Lock()

    @property
    def loaded(self) -> bool:
        return self.provider == "llm" or self._pipeline is not None

    def status(self) -> dict[str, Any]:
        if self.provider == "llm":
            model = getattr(self._llm_client, "model", "configured-llm")
            device = "remote"
        else:
            model = self.model_id
            device = self._actual_device
        return {
            "provider": self.provider,
            "model": model,
            "device": device,
            "loaded": self.loaded,
        }

    def warmup(self) -> dict[str, Any]:
        """Load the configured local ASR pipeline before the first recording."""
        if self.provider == "breeze":
            self._load_breeze_pipeline()
        return self.status()

    def _load_breeze_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline
        with self._load_lock:
            if self._pipeline is not None:
                return self._pipeline
            try:
                torch = self._torch
                if torch is None:
                    import torch as imported_torch

                    torch = imported_torch
                pipeline_factory = self._pipeline_factory
                if pipeline_factory is None:
                    from transformers import pipeline

                    pipeline_factory = pipeline

                cuda_available = bool(torch.cuda.is_available())
                if self.requested_device == "cuda" and not cuda_available:
                    raise ASRUnavailableError("Breeze ASR 指定使用 CUDA，但目前無可用 GPU")
                use_cuda = self.requested_device == "cuda" or (
                    self.requested_device == "auto" and cuda_available
                )
                device = 0 if use_cuda else -1
                dtype = torch.float16 if use_cuda else torch.float32
                self._pipeline = pipeline_factory(
                    task="automatic-speech-recognition",
                    model=self.model_id,
                    device=device,
                    dtype=dtype,
                )
                self._actual_device = "cuda:0" if use_cuda else "cpu"
            except ASRUnavailableError:
                raise
            except Exception as error:
                raise ASRUnavailableError("Breeze ASR 模型載入失敗") from error
        return self._pipeline

    def _release_breeze_gpu(self) -> None:
        """Release a CUDA pipeline while the caller owns _inference_lock."""
        if self._actual_device != "cuda:0":
            return
        self._pipeline = None
        self._actual_device = "not-loaded"
        gc.collect()
        try:
            torch = self._torch
            if torch is None:
                import torch as imported_torch

                torch = imported_torch
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
        except Exception as error:
            # Cleanup should not discard an otherwise valid transcription.
            print(f"[ASR] CUDA cache release failed: {type(error).__name__}: {error}")

    def transcribe(
        self,
        *,
        audio_bytes: bytes,
        filename: str,
        mime_type: str,
        prompt: str,
    ) -> dict[str, Any]:
        started = perf_counter()
        if self.provider == "llm":
            if self._llm_client is None:
                raise ASRUnavailableError("未設定可用的雲端語音辨識服務")
            text = self._llm_client.transcribe(
                audio_bytes=audio_bytes,
                filename=filename,
                mime_type=mime_type,
                prompt=prompt,
            )
        else:
            samples = self._audio_decoder(audio_bytes, max_seconds=self.max_seconds)
            if samples.size == 0:
                raise AudioDecodeError("未偵測到語音內容，請重新錄音")
            rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
            if rms < self.min_rms:
                raise AudioDecodeError("未偵測到足夠的語音音量，請靠近麥克風重試")
            with self._inference_lock:
                asr_pipeline = self._load_breeze_pipeline()
                try:
                    result = asr_pipeline(samples)
                except Exception as error:
                    raise RuntimeError("Breeze ASR 語音推論失敗") from error
                finally:
                    # Drop the local reference before clearing the service
                    # reference so gc can actually reclaim model tensors.
                    asr_pipeline = None
                    if self.release_gpu_after_transcribe:
                        self._release_breeze_gpu()
            text = result.get("text", "") if isinstance(result, dict) else result

        return {
            "text": str(text or "").strip(),
            "provider": self.provider,
            "model": self.status()["model"],
            "latency_seconds": round(perf_counter() - started, 3),
        }
