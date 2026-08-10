import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.config import Settings
from app.engine import AvatarEngine, clean_speech_text, normalize_language


class AvatarEngineTests(unittest.TestCase):
    def test_default_minnan_instruction_matches_cosyvoice_control_phrase(self):
        self.assertEqual(
            Settings().minnan_instruction,
            "You are a helpful assistant. 请用闽南话表达。<|endofprompt|>",
        )

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

    def test_warmup_loads_and_retains_both_avatar_models(self):
        class FakeEngine(AvatarEngine):
            def _assert_runtime(self):
                return None

            def _ensure_models(self):
                return None

            def _load_cosyvoice(self):
                self._cosyvoice = "speech-model"
                return self._cosyvoice

            def _load_muse(self):
                self._muse = "animation-model"
                return self._muse

            def health(self):
                return {
                    "speech_loaded": self._cosyvoice is not None,
                    "animation_loaded": self._muse is not None,
                }

        with tempfile.TemporaryDirectory() as directory:
            engine = FakeEngine(Settings(data_dir=Path(directory)))
            status = engine.warmup()

        self.assertTrue(status["speech_loaded"])
        self.assertTrue(status["animation_loaded"])
        self.assertEqual(engine._cosyvoice, "speech-model")
        self.assertEqual(engine._muse, "animation-model")

    def test_render_publishes_only_completed_video(self):
        synthesize_calls = []

        class FakeEngine(AvatarEngine):
            def _assert_runtime(self):
                return None

            def _ensure_models(self):
                return None

            def _synthesize(self, text, target, instruction):
                synthesize_calls.append((text, instruction))
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
            self.assertEqual(synthesize_calls, [("您好", settings.instruction)])

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

            def _synthesize(self, text, target, instruction):
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

            def _synthesize(self, text, target, instruction):
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
            InferenceSession=lambda *args, **kwargs: (
                calls.append((args, kwargs)) or "cpu-session"
            ),
        )
        voice = SimpleNamespace(frontend=SimpleNamespace())
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(model_dir=Path(directory))
            with patch.dict("sys.modules", {"onnxruntime": fake_onnxruntime}):
                AvatarEngine(settings)._use_cpu_speech_tokenizer(voice)

        self.assertEqual(voice.frontend.speech_tokenizer_session, "cpu-session")
        self.assertEqual(calls[0][1]["providers"], ["CPUExecutionProvider"])
        self.assertTrue(str(calls[0][0][0]).endswith("speech_tokenizer_v3.onnx"))

    def test_language_selects_instruction_and_separate_cache_key(self):
        synthesis_calls = []

        class FakeEngine(AvatarEngine):
            def _assert_runtime(self):
                return None

            def _ensure_models(self):
                return None

            def _synthesize(self, text, target, instruction):
                synthesis_calls.append((text, instruction))
                target.write_bytes(b"wav")

            def _animate(self, wav_path, target):
                target.write_bytes(b"complete-mp4")

        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                data_dir=Path(directory),
                instruction="國語 instruction",
                minnan_instruction="閩南語 instruction",
            )
            engine = FakeEngine(settings)
            mandarin, _, _ = engine.render("請問哪裡不舒服？", "mandarin")
            minnan, _, _ = engine.render("請問哪裡不舒服？", "minnan")

        self.assertNotEqual(mandarin.name, minnan.name)
        self.assertEqual(
            synthesis_calls,
            [
                ("請問哪裡不舒服？", "國語 instruction"),
                ("請問哪裡不舒服？", "閩南語 instruction"),
            ],
        )
        self.assertEqual(normalize_language(" MINNAN "), "minnan")
        with self.assertRaisesRegex(RuntimeError, "不支援"):
            normalize_language("english")

    def test_blend_feathers_before_every_face_crop_edge(self):
        import cv2
        import numpy as np

        frame = np.full((300, 400, 3), 200, dtype=np.uint8)
        generated_face = np.zeros((256, 256, 3), dtype=np.uint8)
        bbox = (100, 50, 300, 250)
        blended = AvatarEngine._blend(frame, generated_face, bbox, cv2, np)

        self.assertTrue(np.all(blended[50, 100:300] == 200))
        self.assertTrue(np.all(blended[249, 100:300] == 200))
        self.assertTrue(np.all(blended[50:250, 100] == 200))
        self.assertTrue(np.all(blended[50:250, 299] == 200))
        self.assertLess(int(blended[178, 200, 0]), 20)


if __name__ == "__main__":
    unittest.main()
