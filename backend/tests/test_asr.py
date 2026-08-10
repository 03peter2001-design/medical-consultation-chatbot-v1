import io
import shutil
import unittest
import wave

import numpy as np

from infrastructure.asr import AudioDecodeError, SpeechTranscriber, decode_audio


class _FakeCuda:
    def __init__(self, available: bool):
        self._available = available
        self.synchronize_calls = 0
        self.empty_cache_calls = 0

    def is_available(self):
        return self._available

    def synchronize(self):
        self.synchronize_calls += 1

    def empty_cache(self):
        self.empty_cache_calls += 1


class _FakeTorch:
    float16 = "float16"
    float32 = "float32"

    def __init__(self, *, cuda_available: bool):
        self.cuda = _FakeCuda(cuda_available)


class SpeechTranscriberTests(unittest.TestCase):
    def test_breeze_pipeline_is_lazy_and_reused_on_cpu(self):
        pipeline_calls = []
        inference_calls = []

        def pipeline_factory(**kwargs):
            pipeline_calls.append(kwargs)

            def run(samples):
                inference_calls.append(samples)
                return {"text": "  我胸口很悶  "}

            return run

        service = SpeechTranscriber(
            env={"ASR_PROVIDER": "breeze", "BREEZE_ASR_DEVICE": "auto"},
            pipeline_factory=pipeline_factory,
            torch_module=_FakeTorch(cuda_available=False),
            audio_decoder=lambda _audio, **_kwargs: np.ones(160, dtype=np.float32),
        )
        self.assertFalse(service.loaded)

        first = service.transcribe(
            audio_bytes=b"audio",
            filename="audio.webm",
            mime_type="audio/webm",
            prompt="prompt",
        )
        second = service.transcribe(
            audio_bytes=b"audio",
            filename="audio.webm",
            mime_type="audio/webm",
            prompt="prompt",
        )

        self.assertEqual(first["text"], "我胸口很悶")
        self.assertEqual(first["provider"], "breeze")
        self.assertEqual(first["model"], "MediaTek-Research/Breeze-ASR-26")
        self.assertGreaterEqual(first["latency_seconds"], 0)
        self.assertEqual(len(pipeline_calls), 1)
        self.assertEqual(len(inference_calls), 2)
        self.assertEqual(pipeline_calls[0]["device"], -1)
        self.assertEqual(pipeline_calls[0]["dtype"], "float32")
        self.assertTrue(service.loaded)
        self.assertEqual(service.status()["device"], "cpu")
        self.assertEqual(second["text"], first["text"])

    def test_cuda_uses_device_zero_and_float16(self):
        pipeline_calls = []

        def pipeline_factory(**kwargs):
            pipeline_calls.append(kwargs)
            return lambda _samples: {"text": "test"}

        service = SpeechTranscriber(
            env={"ASR_PROVIDER": "breeze", "BREEZE_ASR_DEVICE": "cuda"},
            pipeline_factory=pipeline_factory,
            torch_module=_FakeTorch(cuda_available=True),
            audio_decoder=lambda _audio, **_kwargs: np.ones(10, dtype=np.float32),
        )
        service.transcribe(
            audio_bytes=b"audio",
            filename="audio.webm",
            mime_type="audio/webm",
            prompt="prompt",
        )

        self.assertEqual(pipeline_calls[0]["device"], 0)
        self.assertEqual(pipeline_calls[0]["dtype"], "float16")
        self.assertEqual(service.status()["device"], "cuda:0")

    def test_cuda_pipeline_can_be_released_after_each_transcription(self):
        pipeline_calls = []
        fake_torch = _FakeTorch(cuda_available=True)

        def pipeline_factory(**kwargs):
            pipeline_calls.append(kwargs)
            return lambda _samples: {"text": "test"}

        service = SpeechTranscriber(
            env={
                "ASR_PROVIDER": "breeze",
                "BREEZE_ASR_DEVICE": "cuda",
                "BREEZE_ASR_RELEASE_GPU_AFTER_TRANSCRIBE": "true",
            },
            pipeline_factory=pipeline_factory,
            torch_module=fake_torch,
            audio_decoder=lambda _audio, **_kwargs: np.ones(10, dtype=np.float32),
        )
        for _ in range(2):
            service.transcribe(
                audio_bytes=b"audio",
                filename="audio.webm",
                mime_type="audio/webm",
                prompt="prompt",
            )
            self.assertFalse(service.loaded)
            self.assertEqual(service.status()["device"], "not-loaded")

        self.assertEqual(len(pipeline_calls), 2)
        self.assertEqual(fake_torch.cuda.synchronize_calls, 2)
        self.assertEqual(fake_torch.cuda.empty_cache_calls, 2)

    def test_llm_provider_remains_an_explicit_fallback(self):
        class FakeLlm:
            model = "cloud-model"

            def transcribe(self, **_kwargs):
                return "雲端辨識"

        service = SpeechTranscriber(
            env={"ASR_PROVIDER": "llm"},
            llm_client=FakeLlm(),
        )
        result = service.transcribe(
            audio_bytes=b"audio",
            filename="audio.webm",
            mime_type="audio/webm",
            prompt="prompt",
        )

        self.assertEqual(result["text"], "雲端辨識")
        self.assertEqual(service.status()["device"], "remote")

    def test_silence_is_rejected_before_loading_the_model(self):
        service = SpeechTranscriber(
            env={"ASR_PROVIDER": "breeze"},
            pipeline_factory=lambda **_kwargs: self.fail("靜音不應載入模型"),
            torch_module=_FakeTorch(cuda_available=False),
            audio_decoder=lambda _audio, **_kwargs: np.zeros(160, dtype=np.float32),
        )

        with self.assertRaisesRegex(AudioDecodeError, "未偵測到足夠"):
            service.transcribe(
                audio_bytes=b"audio",
                filename="audio.webm",
                mime_type="audio/webm",
                prompt="prompt",
            )
        self.assertFalse(service.loaded)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required for audio decoding")
class AudioDecodeTests(unittest.TestCase):
    @staticmethod
    def _wav_bytes(seconds: float) -> bytes:
        output = io.BytesIO()
        with wave.open(output, "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(8_000)
            samples = np.zeros(round(8_000 * seconds), dtype="<i2")
            target.writeframes(samples.tobytes())
        return output.getvalue()

    def test_decodes_and_resamples_audio_for_breeze(self):
        samples = decode_audio(self._wav_bytes(0.25), max_seconds=2)
        self.assertEqual(samples.dtype, np.float32)
        self.assertAlmostEqual(samples.size / 16_000, 0.25, places=2)

    def test_rejects_audio_over_the_duration_limit(self):
        with self.assertRaisesRegex(AudioDecodeError, "錄音時間過長"):
            decode_audio(self._wav_bytes(2), max_seconds=1)


if __name__ == "__main__":
    unittest.main()
