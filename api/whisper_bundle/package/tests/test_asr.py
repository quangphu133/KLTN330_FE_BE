from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from whisper_bundle.package import asr


class FakeWhisperModel:
    created = 0
    calls: list[tuple[np.ndarray, dict]] = []
    active = 0
    max_active = 0
    empty = False
    state_lock = threading.Lock()

    def __init__(self, path: str, *, device: str, compute_type: str) -> None:
        type(self).created += 1
        self.path = path
        self.device = device
        self.compute_type = compute_type

    def transcribe(self, audio: np.ndarray, **kwargs):
        type(self).calls.append((audio.copy(), kwargs.copy()))
        marker = float(audio[0])

        def generate():
            with type(self).state_lock:
                type(self).active += 1
                type(self).max_active = max(type(self).max_active, type(self).active)
            try:
                time.sleep(0.01)
                if type(self).empty:
                    return
                label = "left" if marker < 0.15 else "right"
                yield SimpleNamespace(
                    id=0,
                    start=0.0,
                    end=1.0,
                    text=label,
                    avg_logprob=-0.1,
                    no_speech_prob=0.0,
                    words=[SimpleNamespace(word=label, start=0.1, end=0.8, probability=0.9)],
                )
            finally:
                with type(self).state_lock:
                    type(self).active -= 1

        return generate(), SimpleNamespace(
            duration=1.0,
            duration_after_vad=1.0,
            language="vi",
            language_probability=1.0,
        )


class AsrFunctionTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeWhisperModel.created = 0
        FakeWhisperModel.calls = []
        FakeWhisperModel.active = 0
        FakeWhisperModel.max_active = 0
        FakeWhisperModel.empty = False
        self.patch_model = patch.object(asr, "WhisperModel", FakeWhisperModel)
        self.patch_model.start()
        self.patch_decode = patch.object(
            asr,
            "_decode_audio",
            return_value=(np.full((1, 16000), 0.1, dtype=np.float32), 16000, 1.0),
        )
        self.patch_decode.start()
        self.patch_resolve = patch.object(
            asr,
            "resolve_model",
            return_value=("large-v3", "local-model", "Systran/faster-whisper-large-v3@pinned"),
        )
        self.patch_resolve.start()
        asr._reset_model_cache_for_tests()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.audio = Path(self.temp_dir.name) / "call.wav"
        self.audio.write_bytes(b"mocked audio")

    def tearDown(self) -> None:
        asr._reset_model_cache_for_tests()
        self.patch_resolve.stop()
        self.patch_decode.stop()
        self.patch_model.stop()
        self.temp_dir.cleanup()

    def test_reuses_one_model_for_mono_and_disables_vad(self) -> None:
        first = asr.transcribe_audio(self.audio)
        second = asr.transcribe_audio(self.audio)

        self.assertEqual(FakeWhisperModel.created, 1)
        self.assertGreater(first["model_load_seconds"], 0)
        self.assertEqual(second["model_load_seconds"], 0.0)
        self.assertEqual(first["text"], "left")
        self.assertIsNone(first["files"])
        self.assertEqual(first["word_timestamp_count"], 1)
        self.assertEqual(first["segments"][0]["channel"], 0)
        self.assertEqual(first["segments"][0]["words"][0]["id"], 0)
        self.assertFalse(first["channel_quality"]["auto_role_eligible"])
        self.assertIn("mono_audio", first["channel_quality"]["reasons"])
        self.assertTrue(all(call[1]["vad_filter"] is False for call in FakeWhisperModel.calls))

    def test_stereo_transcribes_sequentially_merges_and_assigns_stable_ids(self) -> None:
        stereo = np.stack(
            [
                0.1 + np.sin(np.linspace(0, 100, 16000)) * 0.2,
                0.2 + np.sin(np.linspace(0, 137, 16000)) * 0.2,
            ]
        ).astype(np.float32)
        with patch.object(asr, "_decode_audio", return_value=(stereo, 44100, 1.0)):
            result = asr.transcribe_audio(self.audio)

        self.assertEqual(FakeWhisperModel.created, 1)
        self.assertEqual(len(FakeWhisperModel.calls), 2)
        self.assertEqual(FakeWhisperModel.max_active, 1)
        self.assertEqual([item["channel"] for item in result["segments"]], [0, 1])
        self.assertEqual([item["id"] for item in result["segments"]], [0, 1])
        self.assertEqual(
            [item["words"][0]["id"] for item in result["segments"]], [0, 1]
        )
        self.assertEqual(result["text"], "left right")
        self.assertEqual(
            result["audio_metadata"],
            {"num_channels": 2, "sample_rate": 44100, "duration_seconds": 1.0},
        )
        self.assertTrue(result["channel_quality"]["auto_role_eligible"])

    def test_empty_channel_transcript_blocks_role_eligibility(self) -> None:
        stereo = np.stack(
            [
                0.1 + np.sin(np.linspace(0, 100, 16000)) * 0.2,
                0.2 + np.sin(np.linspace(0, 137, 16000)) * 0.2,
            ]
        ).astype(np.float32)
        FakeWhisperModel.empty = True
        with patch.object(asr, "_decode_audio", return_value=(stereo, 44100, 1.0)):
            result = asr.transcribe_audio(self.audio)
        self.assertFalse(result["channel_quality"]["auto_role_eligible"])
        self.assertIn("channel_0_transcript_empty", result["channel_quality"]["reasons"])
        self.assertEqual(result["segments"], [])

    def test_quality_detects_silent_and_gain_normalized_duplicate_channels(self) -> None:
        silent = np.zeros((2, 16000), dtype=np.float32)
        silent_quality = asr._channel_quality(silent, ["", ""])
        self.assertIsNone(silent_quality["correlation"])
        self.assertIn("channel_0_silent_or_near_constant", silent_quality["reasons"])

        signal = np.linspace(-1.0, 1.0, 16000, dtype=np.float32)
        duplicate_quality = asr._channel_quality(
            np.stack([signal, signal * 0.2]), ["left", "right"]
        )
        self.assertGreaterEqual(abs(duplicate_quality["correlation"]), 0.995)
        self.assertIn("channels_near_duplicate", duplicate_quality["reasons"])
        self.assertFalse(duplicate_quality["auto_role_eligible"])

    def test_pyav_decoder_preserves_stereo_channels_and_full_duration(self) -> None:
        self.patch_decode.stop()
        path = Path(self.temp_dir.name) / "controlled-stereo.wav"
        count = 44100
        time_axis = np.arange(count, dtype=np.float64) / 44100
        left = (np.sin(time_axis * 2 * np.pi * 440) * 12000).astype("<i2")
        right = (np.sin(time_axis * 2 * np.pi * 660) * 8000).astype("<i2")
        interleaved = np.column_stack([left, right]).ravel().tobytes()
        with wave.open(str(path), "wb") as output:
            output.setnchannels(2)
            output.setsampwidth(2)
            output.setframerate(44100)
            output.writeframes(interleaved)

        channels, original_rate, duration = asr._decode_audio(path)
        self.assertEqual(channels.shape[0], 2)
        self.assertEqual(original_rate, 44100)
        self.assertAlmostEqual(duration, 1.0, places=3)
        self.assertAlmostEqual(channels.shape[1] / 16000, 1.0, places=3)
        self.assertGreater(float(np.std(channels[0] - channels[1])), 0.1)

    def test_decoder_rejects_three_channel_audio(self) -> None:
        self.patch_decode.stop()
        path = Path(self.temp_dir.name) / "three-channel.wav"
        with wave.open(str(path), "wb") as output:
            output.setnchannels(3)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(b"\x00\x00" * 3 * 16000)
        with self.assertRaisesRegex(ValueError, "one or two channels"):
            asr._decode_audio(path)

    def test_concurrent_calls_are_serialized(self) -> None:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: asr.transcribe_audio(self.audio), range(2)))
        self.assertEqual(len(results), 2)
        self.assertEqual(FakeWhisperModel.max_active, 1)

    def test_json_output_is_finite_and_missing_input_is_rejected(self) -> None:
        output_dir = Path(self.temp_dir.name) / "output"
        result = asr.transcribe_audio(self.audio, output_dir=output_dir)
        saved = json.loads(Path(result["files"]["json"]).read_text(encoding="utf-8"))
        self.assertEqual(set(result["files"]), {"json", "txt", "srt"})
        self.assertEqual(saved["model"], "large-v3")
        self.assertEqual(saved["segments"][0]["words"][0]["id"], 0)
        json.dumps(saved, allow_nan=False)
        with self.assertRaises(FileNotFoundError):
            asr.transcribe_audio(Path(self.temp_dir.name) / "missing.wav")

    def test_only_large_v3_is_supported(self) -> None:
        self.patch_resolve.stop()
        with self.assertRaises(ValueError):
            asr.resolve_model("buzzasr")


if __name__ == "__main__":
    unittest.main()
