from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from whisper_bundle.client.api_client import AsrApiError, submit_audio


class ClientTests(unittest.TestCase):
    def test_submit_audio_sends_multipart_and_returns_job(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "call.wav"
            audio.write_bytes(b"audio")
            response = Mock(ok=True, status_code=202)
            response.json.return_value = {"job_id": "abc", "status": "queued"}
            with patch("whisper_bundle.client.api_client.requests.post", return_value=response) as post:
                result = submit_audio("http://gpu:8000", audio, "secret")
            self.assertEqual(result["job_id"], "abc")
            self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": "Bearer secret"})
            self.assertEqual(post.call_args.kwargs["files"]["file"][0], "call.wav")

    def test_api_error_exposes_structured_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "call.wav"
            audio.write_bytes(b"audio")
            response = Mock(ok=False, status_code=429, text="queue")
            response.json.return_value = {
                "error": {"code": "queue_full", "message": "The ASR queue is full."}
            }
            with patch("whisper_bundle.client.api_client.requests.post", return_value=response):
                with self.assertRaises(AsrApiError) as context:
                    submit_audio("http://gpu:8000", audio, "secret")
        self.assertEqual(context.exception.code, "queue_full")
        self.assertEqual(context.exception.status_code, 429)


if __name__ == "__main__":
    unittest.main()
