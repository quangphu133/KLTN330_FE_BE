from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

from whisper_bundle.package import api_server


def write_test_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * 16000)


class ApiServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings = api_server.Settings(
            api_key="test-secret",
            host="127.0.0.1",
            port=8000,
            data_dir=Path(self.temp_dir.name),
            max_file_bytes=1024 * 1024,
            max_audio_seconds=60,
            max_pending_jobs=2,
            retention_days=7,
        )

        def fake_transcribe(audio_path, **kwargs):
            del audio_path, kwargs
            return {
                "source": "internal.wav",
                "model": "large-v3",
                "model_path": "internal-path",
                "model_metadata": {"repository": "Systran/faster-whisper-large-v3", "revision": "pinned"},
                "device": "cuda",
                "compute_type": "float16",
                "language_requested": "vi",
                "language_detected": "vi",
                "language_probability": 1.0,
                "duration_seconds": 1.0,
                "duration_after_vad_seconds": 1.0,
                "model_load_seconds": 0.0,
                "inference_seconds": 0.01,
                "processing_seconds": 0.01,
                "real_time_factor": 0.01,
                "word_timestamp_count": 1,
                "word_without_timestamp_count": 0,
                "text": "xin chào",
                "segments": [{
                    "id": 0,
                    "start": 0.0,
                    "end": 1.0,
                    "text": "xin chào",
                    "avg_logprob": -0.1,
                    "no_speech_prob": 0.0,
                    "channel": 0,
                    "words": [{"id": 0, "word": "xin chào", "start": 0.0, "end": 1.0, "probability": 0.99}],
                }],
                "audio_metadata": {"num_channels": 1, "sample_rate": 16000, "duration_seconds": 1.0},
                "channel_quality": {"auto_role_eligible": False, "reasons": ["mono_audio"], "correlation": None},
                "diarization": {"status": "disabled", "model": None, "device": "cuda"},
                "files": None,
            }

        self.warm_patch = patch.object(api_server, "warm_up_model", return_value=0.01)
        self.transcribe_patch = patch.object(api_server, "transcribe_audio", side_effect=fake_transcribe)
        self.warm_patch.start()
        self.transcribe_mock = self.transcribe_patch.start()
        self.server = TestServer(api_server.create_app(self.settings))
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        await self.server.close()
        self.warm_patch.stop()
        self.transcribe_patch.stop()
        self.temp_dir.cleanup()

    async def test_requires_authentication(self) -> None:
        response = await self.client.get("/health")
        self.assertEqual(response.status, 401)
        response = await self.client.get("/jobs/missing/txt")
        self.assertEqual(response.status, 401)

    async def test_text_and_srt_require_completed_job(self) -> None:
        job_id = "queued-job"
        self.server.app[api_server.STORE_KEY].create_job(
            job_id,
            "call.wav",
            Path(self.temp_dir.name) / "call.wav",
            Path(self.temp_dir.name) / "result.json",
        )
        headers = {"Authorization": "Bearer test-secret"}

        text_response = await self.client.get(
            f"/jobs/{job_id}/txt", headers=headers
        )
        srt_response = await self.client.get(
            f"/jobs/{job_id}/srt", headers=headers
        )

        self.assertEqual(text_response.status, 409)
        self.assertEqual(srt_response.status, 409)

    async def test_submit_poll_and_result(self) -> None:
        audio_path = Path(self.temp_dir.name) / "call.wav"
        write_test_wav(audio_path)
        headers = {"Authorization": "Bearer test-secret"}
        form = FormData()
        form.add_field("file", audio_path.read_bytes(), filename=audio_path.name, content_type="audio/wav")
        response = await self.client.post(
            "/jobs",
            headers=headers,
            data=form,
        )
        self.assertEqual(response.status, 202)
        queued = await response.json()
        self.assertIn("job_id", queued)

        result = None
        for _ in range(30):
            status_response = await self.client.get(
                f"/jobs/{queued['job_id']}", headers=headers
            )
            status = await status_response.json()
            if status["status"] == "completed":
                result_response = await self.client.get(
                    f"/jobs/{queued['job_id']}/result", headers=headers
                )
                result = await result_response.json()
                break
            await asyncio.sleep(0.01)
        self.assertIsNotNone(result)
        self.assertEqual(result["text"], "xin chào")
        self.assertNotIn("model_path", result)
        self.assertEqual(result["source"], audio_path.name)
        self.assertEqual(result["model"], "large-v3")
        self.assertEqual(result["audio_metadata"]["num_channels"], 1)
        self.assertEqual(result["diarization"]["status"], "disabled")
        self.transcribe_mock.assert_called_once()
        self.assertEqual(self.transcribe_mock.call_args.kwargs["model"], "large-v3")

        text_response = await self.client.get(
            f"/jobs/{queued['job_id']}/txt", headers=headers
        )
        self.assertEqual(text_response.status, 200)
        self.assertEqual(
            await text_response.text(),
            "[00:00:00.000 -> 00:00:01.000] xin chào",
        )

        srt_response = await self.client.get(
            f"/jobs/{queued['job_id']}/srt", headers=headers
        )
        self.assertEqual(srt_response.status, 200)
        self.assertEqual(
            await srt_response.text(),
            "1\n00:00:00,000 --> 00:00:01,000\nxin chào",
        )

        download_response = await self.client.get(
            f"/jobs/{queued['job_id']}/srt?download=1", headers=headers
        )
        self.assertEqual(download_response.status, 200)
        self.assertIn(
            f'filename="{queued["job_id"]}.srt"',
            download_response.headers["Content-Disposition"],
        )

        missing_response = await self.client.get(
            "/jobs/missing/txt", headers=headers
        )
        self.assertEqual(missing_response.status, 404)

        job = self.server.app[api_server.STORE_KEY].get(queued["job_id"])
        Path(job["result_path"]).unlink()
        unavailable_response = await self.client.get(
            f"/jobs/{queued['job_id']}/srt", headers=headers
        )
        self.assertEqual(unavailable_response.status, 500)

    async def test_empty_transcript_returns_empty_text_and_srt(self) -> None:
        audio_path = Path(self.temp_dir.name) / "silent.wav"
        write_test_wav(audio_path)
        headers = {"Authorization": "Bearer test-secret"}
        form = FormData()
        form.add_field(
            "file", audio_path.read_bytes(), filename=audio_path.name, content_type="audio/wav"
        )
        response = await self.client.post("/jobs", headers=headers, data=form)
        queued = await response.json()

        for _ in range(30):
            status_response = await self.client.get(
                f"/jobs/{queued['job_id']}", headers=headers
            )
            status = await status_response.json()
            if status["status"] == "completed":
                break
            await asyncio.sleep(0.01)
        self.assertEqual(status["status"], "completed")

        job = self.server.app[api_server.STORE_KEY].get(queued["job_id"])
        result_path = Path(job["result_path"])
        result = await self.client.get(
            f"/jobs/{queued['job_id']}/result", headers=headers
        )
        result_data = await result.json()
        result_data["segments"] = []
        result_path.write_text(
            json.dumps(result_data), encoding="utf-8"
        )

        text_response = await self.client.get(
            f"/jobs/{queued['job_id']}/txt", headers=headers
        )
        srt_response = await self.client.get(
            f"/jobs/{queued['job_id']}/srt", headers=headers
        )
        self.assertEqual(await text_response.text(), "")
        self.assertEqual(await srt_response.text(), "")

    async def test_health_reports_large_v3_and_diarization_disabled(self) -> None:
        response = await self.client.get(
            "/health", headers={"Authorization": "Bearer test-secret"}
        )
        payload = await response.json()
        self.assertEqual(payload["model"], "large-v3")
        self.assertEqual(
            payload["model_source_revision"],
            "Systran/faster-whisper-large-v3@edaa852ec7e145841d8ffdb056a99866b5f0a478",
        )
        self.assertFalse(payload["diarization_enabled"])
        self.assertIsNone(payload["diarization_model"])

    async def test_upload_rejects_audio_with_more_than_two_channels(self) -> None:
        audio_path = Path(self.temp_dir.name) / "multi.wav"
        with wave.open(str(audio_path), "wb") as audio:
            audio.setnchannels(3)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\x00\x00" * 3 * 16000)
        form = FormData()
        form.add_field("file", audio_path.read_bytes(), filename=audio_path.name, content_type="audio/wav")
        response = await self.client.post(
            "/jobs",
            headers={"Authorization": "Bearer test-secret"},
            data=form,
        )
        self.assertEqual(response.status, 400)
        payload = await response.json()
        self.assertEqual(payload["error"]["code"], "invalid_audio")


if __name__ == "__main__":
    unittest.main()
