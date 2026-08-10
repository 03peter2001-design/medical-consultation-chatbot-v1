from __future__ import annotations

import gc
import hashlib
import os
import re
import subprocess
import tempfile
from pathlib import Path
from threading import Lock

from .config import Settings

SPEECH_MODEL = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
ANIMATION_MODEL = "TMElyralab/MuseTalk 1.5"
SUPPORTED_LANGUAGES = frozenset({"mandarin", "minnan"})


class AvatarEngineError(RuntimeError):
    pass


def clean_speech_text(text: str) -> str:
    cleaned = re.sub(r"【.*?】", "", text)
    cleaned = re.sub(r"[（(][^）)]*[）)]", "", cleaned)
    cleaned = re.sub(r"^[a-zA-Z]\.\s?.*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^選項[：:].*$", "", cleaned, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_language(language: str) -> str:
    normalized = language.strip().lower()
    if normalized not in SUPPORTED_LANGUAGES:
        raise AvatarEngineError("不支援的 Avatar 語言")
    return normalized


class AvatarEngine:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self._lock = Lock()
        self._cosyvoice = None
        self._muse = None
        self._device = "unknown"

    def health(self) -> dict[str, object]:
        try:
            import torch

            cuda = torch.cuda.is_available()
            self._device = "cuda:0" if cuda else "cpu"
        except Exception:
            cuda = False
            self._device = "unavailable"
        ready = cuda or not self.settings.require_cuda
        return {
            "status": "ok" if ready else "degraded",
            "speech_model": SPEECH_MODEL,
            "animation_model": ANIMATION_MODEL,
            "device": self._device,
            "models_downloaded": self._models_downloaded(),
            "speech_loaded": self._cosyvoice is not None,
            "animation_loaded": self._muse is not None,
            "keep_models_loaded": not self.settings.release_gpu_after_render,
        }

    def warmup(self) -> dict[str, object]:
        """Load every Avatar model once and retain it for subsequent renders."""
        with self._lock:
            try:
                self._assert_runtime()
                self._ensure_models()
                self._load_cosyvoice()
                self._load_muse()
            except Exception:
                self._release_models()
                raise
        return self.health()

    def render(
        self,
        raw_text: str,
        language: str = "mandarin",
    ) -> tuple[Path, bool, str]:
        text = clean_speech_text(raw_text)
        if not text:
            raise AvatarEngineError("沒有可朗讀的文字")
        language = normalize_language(language)
        instruction = (
            self.settings.minnan_instruction
            if language == "minnan"
            else self.settings.instruction
        )
        digest = hashlib.sha256(
            f"v3\0{language}\0{instruction}\0{text}".encode("utf-8")
        ).hexdigest()
        output = self.settings.output_dir / f"{digest}.mp4"
        if output.is_file() and output.stat().st_size > 0:
            return output, True, ANIMATION_MODEL

        with self._lock:
            if output.is_file() and output.stat().st_size > 0:
                return output, True, ANIMATION_MODEL
            self._assert_runtime()
            self._ensure_models()
            self.settings.output_dir.mkdir(parents=True, exist_ok=True)
            try:
                with tempfile.TemporaryDirectory(dir=self.settings.data_dir) as temp_dir:
                    wav_path = Path(temp_dir) / "speech.wav"
                    rendered_path = Path(temp_dir) / "avatar.mp4"
                    self._synthesize(text, wav_path, instruction)
                    if self.settings.release_gpu_after_render:
                        # The WAV is on CPU/disk now, so CosyVoice can be
                        # released before MuseTalk claims its own GPU memory.
                        self._release_models(speech=True, animation=False)
                    animation_model = ANIMATION_MODEL
                    try:
                        self._animate(wav_path, rendered_path)
                    except Exception as error:
                        if not self.settings.static_fallback:
                            raise
                        animation_model = "static-image fallback"
                        self._render_static(wav_path, rendered_path)
                        print(
                            f"[Avatar] MuseTalk fallback: "
                            f"{type(error).__name__}: {error}"
                        )
                    if not rendered_path.is_file() or rendered_path.stat().st_size == 0:
                        raise AvatarEngineError("Avatar 影片輸出為空")
                    os.replace(rendered_path, output)
            finally:
                if self.settings.release_gpu_after_render:
                    self._release_models()
            self._trim_cache()
        return output, False, animation_model

    def _release_models(self, *, speech: bool = True, animation: bool = True) -> None:
        """Drop model references and return unused allocator blocks to CUDA.

        render() owns the engine lock while calling this method, so no other
        Avatar request can be using these process-local model objects.
        """
        if speech:
            self._cosyvoice = None
        if animation:
            self._muse = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
        except Exception as error:
            # Cleanup must not turn an otherwise valid MP4 into an API error.
            print(f"[Avatar] CUDA cache release failed: {type(error).__name__}: {error}")

    def _assert_runtime(self) -> None:
        if not self.settings.image_path.is_file():
            raise AvatarEngineError("找不到 Avatar 基準圖")
        if not self.settings.prompt_wav.is_file():
            raise AvatarEngineError("找不到 CosyVoice 參考語音")
        if self.settings.require_cuda:
            import torch

            if not torch.cuda.is_available():
                raise AvatarEngineError("NVIDIA CUDA 尚未可用")

    def _models_downloaded(self) -> bool:
        return all(
            (
                self._cosyvoice_downloaded(),
                self._musetalk_downloaded(),
                self._vae_downloaded(),
                self._whisper_downloaded(),
            )
        )

    def _cosyvoice_downloaded(self) -> bool:
        required = (
            "cosyvoice3.yaml",
            "llm.pt",
            "flow.pt",
            "hift.pt",
            "campplus.onnx",
            "speech_tokenizer_v3.onnx",
            "CosyVoice-BlankEN/config.json",
            "CosyVoice-BlankEN/model.safetensors",
            "CosyVoice-BlankEN/tokenizer_config.json",
        )
        return all((self.settings.cosyvoice_dir / name).is_file() for name in required)

    def _musetalk_downloaded(self) -> bool:
        checkpoint_dir = self.settings.musetalk_dir / "musetalkV15"
        return all(
            (checkpoint_dir / name).is_file()
            for name in ("musetalk.json", "unet.pth")
        )

    def _vae_downloaded(self) -> bool:
        return all(
            (self.settings.vae_dir / name).is_file()
            for name in ("config.json", "diffusion_pytorch_model.bin")
        )

    def _whisper_downloaded(self) -> bool:
        has_weights = any(
            (self.settings.whisper_dir / name).is_file()
            for name in ("model.safetensors", "pytorch_model.bin")
        )
        return has_weights and all(
            (self.settings.whisper_dir / name).is_file()
            for name in ("config.json", "preprocessor_config.json")
        )

    def _ensure_models(self) -> None:
        if self._models_downloaded():
            return
        from huggingface_hub import snapshot_download

        self.settings.model_dir.mkdir(parents=True, exist_ok=True)
        if not self._cosyvoice_downloaded():
            snapshot_download(
                repo_id=self.settings.cosyvoice_repo,
                local_dir=self.settings.cosyvoice_dir,
            )
        if not self._musetalk_downloaded():
            snapshot_download(
                repo_id="TMElyralab/MuseTalk",
                local_dir=self.settings.musetalk_dir,
                allow_patterns=["musetalkV15/*"],
            )
        if not self._vae_downloaded():
            snapshot_download(
                repo_id="stabilityai/sd-vae-ft-mse",
                local_dir=self.settings.vae_dir,
                allow_patterns=["config.json", "diffusion_pytorch_model.bin"],
            )
        if not self._whisper_downloaded():
            snapshot_download(
                repo_id="openai/whisper-tiny",
                local_dir=self.settings.whisper_dir,
                allow_patterns=[
                    "config.json",
                    "pytorch_model.bin",
                    "model.safetensors",
                    "preprocessor_config.json",
                ],
            )

    def _load_cosyvoice(self):
        if self._cosyvoice is None:
            import torch
            from cosyvoice.cli.cosyvoice import AutoModel

            voice = AutoModel(
                model_dir=str(self.settings.cosyvoice_dir),
                fp16=torch.cuda.is_available(),
            )
            self._use_cpu_speech_tokenizer(voice)
            self._cosyvoice = voice
        return self._cosyvoice

    def _use_cpu_speech_tokenizer(self, voice) -> None:
        """Keep only the small prompt tokenizer ONNX graph off the GPU.

        ONNX Runtime's CUDA provider can reject its bundled PTX on Blackwell
        cards (for example the RTX 5060 Ti). CosyVoice's neural TTS model stays
        on CUDA; this CPU session only extracts tokens from the short reference
        WAV and has negligible impact on end-to-end latency.
        """
        import onnxruntime

        options = onnxruntime.SessionOptions()
        options.graph_optimization_level = (
            onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
        )
        options.intra_op_num_threads = 1
        voice.frontend.speech_tokenizer_session = onnxruntime.InferenceSession(
            str(self.settings.cosyvoice_dir / "speech_tokenizer_v3.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )

    def _synthesize(self, text: str, target: Path, instruction: str) -> None:
        import soundfile
        import torch

        voice = self._load_cosyvoice()
        chunks = [
            item["tts_speech"].detach().cpu()
            for item in voice.inference_instruct2(
                text,
                instruction,
                str(self.settings.prompt_wav),
                stream=False,
            )
        ]
        if not chunks:
            raise AvatarEngineError("CosyVoice 沒有產生語音")
        speech = torch.cat(chunks, dim=1).squeeze(0).numpy()
        soundfile.write(str(target), speech, voice.sample_rate, subtype="PCM_16")

    def _parse_bbox(self, width: int, height: int, scale: float) -> tuple[int, int, int, int]:
        try:
            values = [int(item.strip()) for item in self.settings.face_bbox.split(",")]
        except ValueError as error:
            raise AvatarEngineError("MUSETALK_FACE_BBOX 格式錯誤") from error
        if len(values) != 4:
            raise AvatarEngineError("MUSETALK_FACE_BBOX 必須有四個整數")
        x1, y1, x2, y2 = (round(value * scale) for value in values)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(width, x2), min(height, y2)
        if x2 <= x1 or y2 <= y1:
            raise AvatarEngineError("MUSETALK_FACE_BBOX 超出基準圖")
        return x1, y1, x2, y2

    def _load_muse(self):
        if self._muse is not None:
            return self._muse
        import torch
        from musetalk.utils.audio_processor import AudioProcessor
        from musetalk.utils.utils import load_all_model
        from transformers import WhisperModel

        device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        dtype = torch.float16 if device.type == "cuda" else torch.float32
        vae, unet, positional = load_all_model(
            unet_model_path=str(self.settings.musetalk_dir / "musetalkV15" / "unet.pth"),
            vae_type=str(self.settings.vae_dir),
            unet_config=str(
                self.settings.musetalk_dir / "musetalkV15" / "musetalk.json"
            ),
            device=device,
        )
        positional = positional.to(device=device, dtype=dtype).eval()
        vae.vae = vae.vae.to(device=device, dtype=dtype).eval()
        unet.model = unet.model.to(device=device, dtype=dtype).eval()
        audio = AudioProcessor(feature_extractor_path=str(self.settings.whisper_dir))
        whisper = WhisperModel.from_pretrained(str(self.settings.whisper_dir))
        whisper = whisper.to(device=device, dtype=dtype).eval()
        whisper.requires_grad_(False)
        vae.vae.requires_grad_(False)
        unet.model.requires_grad_(False)
        self._muse = (torch, device, dtype, vae, unet, positional, audio, whisper)
        return self._muse

    def _animate(self, wav_path: Path, target: Path) -> None:
        import cv2
        import numpy as np

        torch, device, dtype, vae, unet, positional, audio, whisper = self._load_muse()
        frame = cv2.imread(str(self.settings.image_path))
        if frame is None:
            raise AvatarEngineError("無法讀取 Avatar 基準圖")
        original_height, original_width = frame.shape[:2]
        scale = min(1.0, self.settings.output_width / original_width)
        width = round(original_width * scale / 2) * 2
        height = round(original_height * scale / 2) * 2
        frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
        x1, y1, x2, y2 = self._parse_bbox(width, height, scale)
        crop = cv2.resize(
            frame[y1:y2, x1:x2],
            (256, 256),
            interpolation=cv2.INTER_LANCZOS4,
        )
        with torch.inference_mode():
            latent = vae.get_latents_for_unet(crop)
            features, audio_length = audio.get_audio_feature(
                wav_path,
                weight_dtype=dtype,
            )
            try:
                chunks = audio.get_whisper_chunk(
                    features,
                    device,
                    dtype,
                    whisper,
                    audio_length,
                    fps=self.settings.fps,
                ).cpu()
            except SystemExit as error:
                # MuseTalk 1.5 exits the whole process on a malformed final
                # audio window. Keep the API alive and let render() use its
                # configured static fallback instead.
                raise AvatarEngineError("MuseTalk 語音特徵長度異常") from error
        if len(chunks) == 0:
            raise AvatarEngineError("MuseTalk 沒有取得語音特徵")

        silent_video = target.with_suffix(".silent.mp4")
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pixel_format", "bgr24",
            "-video_size", f"{width}x{height}",
            "-framerate", str(self.settings.fps), "-i", "-",
            "-an", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "20", "-pix_fmt", "yuv420p", str(silent_video),
        ]
        encoder = subprocess.Popen(command, stdin=subprocess.PIPE)
        try:
            with torch.inference_mode():
                timestep = torch.tensor([0], device=device)
                for start in range(0, len(chunks), self.settings.batch_size):
                    audio_batch = chunks[start : start + self.settings.batch_size].to(
                        device=device,
                        dtype=dtype,
                    )
                    latent_batch = latent.expand(len(audio_batch), -1, -1, -1).to(
                        device=device,
                        dtype=unet.model.dtype,
                    )
                    encoded_audio = positional(audio_batch)
                    predicted = unet.model(
                        latent_batch,
                        timestep,
                        encoder_hidden_states=encoded_audio,
                    ).sample.to(device=device, dtype=vae.vae.dtype)
                    for face in vae.decode_latents(predicted):
                        composed = self._blend(
                            frame,
                            face,
                            (x1, y1, x2, y2),
                            cv2,
                            np,
                        )
                        assert encoder.stdin is not None
                        encoder.stdin.write(composed.tobytes())
            assert encoder.stdin is not None
            encoder.stdin.close()
            if encoder.wait() != 0:
                raise AvatarEngineError("ffmpeg 影片編碼失敗")
            self._mux_audio(silent_video, wav_path, target)
        finally:
            if encoder.poll() is None:
                encoder.kill()
            silent_video.unlink(missing_ok=True)

    @staticmethod
    def _blend(frame, face, bbox, cv2, np):
        x1, y1, x2, y2 = bbox
        face = cv2.resize(face.astype(np.uint8), (x2 - x1, y2 - y1))
        height, width = face.shape[:2]
        # MuseTalk returns a square reconstruction of the face crop. Blending
        # that whole rectangle creates a visible seam across the doctor's neck
        # and coat. Restrict replacement to a feathered lower-face oval whose
        # alpha reaches zero well before every crop edge; hair, cheek outline,
        # jaw edge, neck, and clothing therefore stay on the source portrait.
        mask = np.zeros((height, width), dtype=np.uint8)
        center = (width // 2, round(height * 0.64))
        axes = (
            max(1, round(width * 0.36)),
            max(1, round(height * 0.23)),
        )
        cv2.ellipse(mask, center, axes, 0, 0, 360, 255, -1)
        kernel = max(11, (round(min(width, height) * 0.1) // 2) * 2 + 1)
        alpha = cv2.GaussianBlur(mask, (kernel, kernel), 0).astype(np.float32)
        alpha = (alpha / 255.0)[..., None]
        output = frame.copy()
        base = output[y1:y2, x1:x2].astype(np.float32)
        output[y1:y2, x1:x2] = (face * alpha + base * (1 - alpha)).astype(np.uint8)
        return output

    def _mux_audio(self, video: Path, audio: Path, target: Path) -> None:
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(video), "-i", str(audio), "-c:v", "copy",
                "-c:a", "aac", "-b:a", "128k", "-shortest", str(target),
            ],
            check=True,
        )

    def _render_static(self, wav_path: Path, target: Path) -> None:
        import soundfile

        duration = soundfile.info(str(wav_path)).duration
        if duration <= 0:
            raise AvatarEngineError("CosyVoice 語音輸出為空")
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-loop", "1", "-i", str(self.settings.image_path),
                "-i", str(wav_path), "-vf", f"scale={self.settings.output_width}:-2",
                "-c:v", "libx264", "-tune", "stillimage", "-c:a", "aac",
                "-b:a", "128k", "-pix_fmt", "yuv420p", "-t", f"{duration:.3f}",
                "-shortest", str(target),
            ],
            check=True,
        )

    def _trim_cache(self) -> None:
        files = sorted(
            self.settings.output_dir.glob("*.mp4"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for stale in files[self.settings.cache_max_files :]:
            stale.unlink(missing_ok=True)
