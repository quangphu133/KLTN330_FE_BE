"""Small Python client for the remote BuzzASR job API."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import requests


class AsrApiError(RuntimeError):
    """Raised when the remote ASR API returns an error response."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(f"ASR API {status_code} {code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message


def _headers(api_key: str) -> dict[str, str]:
    if not api_key:
        raise ValueError("api_key must not be empty")
    return {"Authorization": f"Bearer {api_key}"}


def _json_response(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as error:
        raise AsrApiError(response.status_code, "invalid_response", response.text[:500]) from error
    if not response.ok:
        error = payload.get("error", {})
        raise AsrApiError(
            response.status_code,
            str(error.get("code", "request_failed")),
            str(error.get("message", "The ASR API request failed.")),
        )
    return payload


def submit_audio(
    base_url: str,
    audio_path: str | Path,
    api_key: str,
    *,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """Upload one audio file and return the queued job payload.

    This function never retries the POST automatically, so a network timeout
    cannot create an unknown duplicate job.
    """

    path = Path(audio_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("rb") as audio_file:
        response = requests.post(
            f"{base_url.rstrip('/')}/jobs",
            headers=_headers(api_key),
            files={"file": (path.name, audio_file)},
            timeout=timeout_seconds,
        )
    return _json_response(response)


def get_job(
    base_url: str,
    job_id: str,
    api_key: str,
    *,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Return the current status for a job."""

    response = requests.get(
        f"{base_url.rstrip('/')}/jobs/{job_id}",
        headers=_headers(api_key),
        timeout=timeout_seconds,
    )
    return _json_response(response)


def wait_for_result(
    base_url: str,
    job_id: str,
    api_key: str,
    *,
    poll_seconds: float = 2.0,
    max_wait_seconds: float = 30 * 60,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Poll a job and return its completed transcript JSON.

    A timeout leaves the job on the server; callers can retain ``job_id`` and
    call this function again later.
    """

    if poll_seconds <= 0 or max_wait_seconds <= 0:
        raise ValueError("poll_seconds and max_wait_seconds must be positive")
    started = time.monotonic()
    while True:
        status = get_job(base_url, job_id, api_key, timeout_seconds=timeout_seconds)
        if status["status"] == "completed":
            response = requests.get(
                f"{base_url.rstrip('/')}/jobs/{job_id}/result",
                headers=_headers(api_key),
                timeout=timeout_seconds,
            )
            return _json_response(response)
        if status["status"] == "failed":
            error = status.get("error", {})
            raise AsrApiError(
                409,
                str(error.get("code", "transcription_failed")),
                str(error.get("message", "The ASR job failed.")),
            )
        if time.monotonic() - started >= max_wait_seconds:
            raise TimeoutError(f"ASR job did not finish within {max_wait_seconds:g} seconds: {job_id}")
        time.sleep(poll_seconds)
