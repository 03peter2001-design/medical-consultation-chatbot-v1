from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(os.getenv("AVATAR_DATA_DIR", "/data"))
    model_dir: Path = Path(os.getenv("AVATAR_MODEL_DIR", "/models/avatar"))
    image_path: Path = Path(os.getenv("AVATAR_IMAGE_PATH", "/app/assets/doctor.png"))
    prompt_wav: Path = Path(
        os.getenv("COSYVOICE_PROMPT_WAV", "/app/assets/voice-prompt.wav")
    )
    cosyvoice_repo: str = os.getenv(
        "COSYVOICE_MODEL",
        "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
    )
    instruction: str = os.getenv(
        "COSYVOICE_INSTRUCTION",
        "You are a helpful assistant. 請使用平穩、親切、清晰的華語，以專業醫療人員的語氣說話。<|endofprompt|>",
    )
    face_bbox: str = os.getenv("MUSETALK_FACE_BBOX", "585,140,915,520")
    fps: int = max(10, min(30, int(os.getenv("MUSETALK_FPS", "25"))))
    batch_size: int = max(1, int(os.getenv("MUSETALK_BATCH_SIZE", "8")))
    output_width: int = max(320, int(os.getenv("AVATAR_OUTPUT_WIDTH", "768")))
    require_cuda: bool = _flag("AVATAR_REQUIRE_CUDA", True)
    static_fallback: bool = _flag("AVATAR_STATIC_FALLBACK", True)
    release_gpu_after_render: bool = _flag(
        "AVATAR_RELEASE_GPU_AFTER_RENDER",
        True,
    )
    cache_max_files: int = max(10, int(os.getenv("AVATAR_CACHE_MAX_FILES", "200")))

    @property
    def cosyvoice_dir(self) -> Path:
        return self.model_dir / "cosyvoice3"

    @property
    def musetalk_dir(self) -> Path:
        return self.model_dir / "musetalk"

    @property
    def vae_dir(self) -> Path:
        return self.model_dir / "sd-vae"

    @property
    def whisper_dir(self) -> Path:
        return self.model_dir / "whisper"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "videos"
