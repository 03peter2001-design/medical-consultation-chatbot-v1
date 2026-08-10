import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.config import Settings
from app.engine import AvatarEngine, clean_speech_text


class AvatarEngineTests(unittest.TestCase):
    def test_cleans_question_metadata_before_speech(self):
        text = "請問疼痛多久？（請擇一）\nA. 一小時\n選項：一小時、兩小時"
        self.assertEqual(clean_speech_text(text), "請問疼痛多久？")

    def test_bbox_is_scaled_for_the_smaller_output_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(data_dir=Path(directory), face_bbox="100,50,300,250")
            engine = AvatarEngine(settings)
            self.assertEqual(engine._parse_bbox(400, 300, 0.5), (50, 25, 150, 125))

    def test_invalid_bbox_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(data_dir=Path(directory), face_bbox="bad")
            engine = AvatarEngine(settings)
            with self.assertRaisesRegex(RuntimeError, "格式錯誤"):
                engine._parse_bbox(400, 300, 1.0)

    def test_partial_checkpoint_download_is_not_reported_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory)
            settings = Settings(model_dir=model_dir)
            engine = AvatarEngine(settings)
            settings.cosyvoice_dir.mkdir(parents=True)
            (settings.cosyvoice_dir / "cosyvoice3.yaml").touch()
            self.assertFalse(engine._models_downloaded())

    def test_render_publishes_only_completed_video(self):
        synthesize_calls = []

        class FakeEngine(AvatarEngine):
            def _assert_runtime(self):
                return None

            def _ensure_models(self):
                return None

            def _synthesize(self, text, target):
                synthesize_calls.append(text)
                target.write_bytes(b"wav")

            def _animate(self, wav_path, target):
                target.write_bytes(b"complete-mp4")

        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(data_dir=Path(directory), cache_max_files=10)
            engine = FakeEngine(settings)
            output, cache_hit, animation_model = engine.render("您好")
            self.assertEqual(output.read_bytes(), b"complete-mp4")
            self.assertFalse(cache_hit)
            self.assertEqual(animation_model, "TMElyralab/MuseTalk 1.5")
            cached_output, cache_hit, _ = engine.render("您好")
            self.assertEqual(cached_output, output)
            self.assertTrue(cache_hit)
            self.assertEqual(synthesize_calls, ["您好"])

    def test_render_releases_speech_before_animation_and_all_models_afterward(self):
        cuda_calls = []
        fake_torch = SimpleNamespace(
            cuda=SimpleNamespace(
                is_available=lambda: True,
                synchronize=lambda: cuda_calls.append("synchronize"),
                empty_cache=lambda: cuda_calls.append("empty_cache"),
            )
        )

        class FakeEngine(AvatarEngine):
            def _assert_runtime(self):
                return None

            def _ensure_models(self):
                return None

            def _synthesize(self, text, target):
                self._cosyvoice = object()
                target.write_bytes(b"wav")

            def _animate(self, wav_path, target):
                self.testcase.assertIsNone(self._cosyvoice)
                self._muse = object()
                target.write_bytes(b"complete-mp4")

        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                data_dir=Path(directory),
                cache_max_files=10,
                release_gpu_after_render=True,
            )
            engine = FakeEngine(settings)
            engine.testcase = self
            with patch.dict("sys.modules", {"torch": fake_torch}):
                engine.render("顯存釋放測試")

        self.assertIsNone(engine._cosyvoice)
        self.assertIsNone(engine._muse)
        self.assertEqual(cuda_calls.count("empty_cache"), 2)

    def test_model_retention_can_be_enabled_for_lower_reload_latency(self):
        class FakeEngine(AvatarEngine):
            def _assert_runtime(self):
                return None

            def _ensure_models(self):
                return None

            def _synthesize(self, text, target):
                self._cosyvoice = "speech-model"
                target.write_bytes(b"wav")

            def _animate(self, wav_path, target):
                self._muse = "animation-model"
                target.write_bytes(b"complete-mp4")

        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                data_dir=Path(directory),
                cache_max_files=10,
                release_gpu_after_render=False,
            )
            engine = FakeEngine(settings)
            engine.render("保留模型測試")

        self.assertEqual(engine._cosyvoice, "speech-model")
        self.assertEqual(engine._muse, "animation-model")

    def test_cosyvoice_speech_tokenizer_is_forced_to_cpu(self):
        calls = []
        options = SimpleNamespace()
        fake_onnxruntime = SimpleNamespace(
            SessionOptions=lambda: options,
            GraphOptimizationLevel=SimpleNamespace(ORT_ENABLE_ALL="all"),
            InferenceSession=lambda *args, **kwargs: calls.append((args, kwargs))
            or "cpu-session",
        )
        voice = SimpleNamespace(frontend=SimpleNamespace())
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(model_dir=Path(directory))
            with patch.dict("sys.modules", {"onnxruntime": fake_onnxruntime}):
                AvatarEngine(settings)._use_cpu_speech_tokenizer(voice)

        self.assertEqual(voice.frontend.speech_tokenizer_session, "cpu-session")
        self.assertEqual(calls[0][1]["providers"], ["CPUExecutionProvider"])
        self.assertTrue(str(calls[0][0][0]).endswith("speech_tokenizer_v3.onnx"))


if __name__ == "__main__":
    unittest.main()
