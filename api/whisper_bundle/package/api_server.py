"""Remote Whisper large-v3 API server for a single CUDA worker."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import json
import os
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import av
from aiohttp import web

try:
    from .asr import MODEL_ALIASES, transcribe_audio, warm_up_model
except ImportError:  # Supports direct execution from this package directory.
    from asr import MODEL_ALIASES, transcribe_audio, warm_up_model


STATUSES = {"queued", "running", "completed", "failed"}
ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_text(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat()


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value)


@dataclass(frozen=True)
class Settings:
    api_key: str
    host: str
    port: int
    data_dir: Path
    max_file_bytes: int
    max_audio_seconds: int
    max_pending_jobs: int
    retention_days: int
    model: str = "large-v3"
    device: str = "cuda"
    compute_type: str = "float16"

    @classmethod
    def from_environment(cls) -> "Settings":
        api_key = os.environ.get("ASR_API_KEY", "")
        if not api_key:
            raise RuntimeError("ASR_API_KEY is required")
        project_root = Path(__file__).resolve().parents[2]
        data_dir = Path(
            os.environ.get("ASR_DATA_DIR", str(project_root / "asr_service_data"))
        ).expanduser()
        return cls(
            api_key=api_key,
            host=os.environ.get("ASR_HOST", "127.0.0.1"),
            port=int(os.environ.get("ASR_PORT", "8000")),
            data_dir=data_dir,
            max_file_bytes=int(os.environ.get("ASR_MAX_FILE_BYTES", str(100 * 1024 * 1024))),
            max_audio_seconds=int(os.environ.get("ASR_MAX_AUDIO_SECONDS", "1800")),
            max_pending_jobs=int(os.environ.get("ASR_MAX_PENDING_JOBS", "10")),
            retention_days=int(os.environ.get("ASR_RETENTION_DAYS", "7")),
        )


class JobStore:
    """Small SQLite store used by the single API process."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "jobs.sqlite3"
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    original_filename TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    audio_path TEXT NOT NULL,
                    result_path TEXT NOT NULL,
                    error_code TEXT,
                    error_message TEXT
                )
                """
            )

    def recover_running(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = 'failed', finished_at = ?,
                    error_code = 'server_restarted',
                    error_message = 'The server restarted while this job was running.'
                WHERE status = 'running'
                """,
                (utc_text(),),
            )

    def create_job(self, job_id: str, filename: str, audio_path: Path, result_path: Path) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs
                (job_id, original_filename, status, created_at, audio_path, result_path)
                VALUES (?, ?, 'queued', ?, ?, ?)
                """,
                (job_id, filename, utc_text(), str(audio_path), str(result_path)),
            )

    def count_pending(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM jobs WHERE status IN ('queued', 'running')"
            ).fetchone()
        return int(row["count"])

    def get(self, job_id: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()

    def queued_jobs(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT job_id FROM jobs WHERE status = 'queued' ORDER BY created_at"
            ).fetchall()
        return [str(row["job_id"]) for row in rows]

    def mark_running(self, job_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET status = 'running', started_at = ? WHERE job_id = ?",
                (utc_text(), job_id),
            )

    def mark_completed(self, job_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET status = 'completed', finished_at = ? WHERE job_id = ?",
                (utc_text(), job_id),
            )

    def mark_failed(self, job_id: str, code: str, message: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = 'failed', finished_at = ?, error_code = ?, error_message = ?
                WHERE job_id = ?
                """,
                (utc_text(), code, message, job_id),
            )

    def expired_jobs(self, cutoff: datetime) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return connection.execute(
                """
                SELECT * FROM jobs
                WHERE status IN ('completed', 'failed') AND finished_at < ?
                """,
                (utc_text(cutoff),),
            ).fetchall()

    def delete(self, job_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))


SETTINGS_KEY = web.AppKey("settings", Settings)
STORE_KEY = web.AppKey("store", JobStore)
QUEUE_KEY = web.AppKey("queue", asyncio.Queue)
STATE_KEY = web.AppKey("state", dict)


def _json_error(code: str, message: str, status: int) -> web.Response:
    return web.json_response({"error": {"code": code, "message": message}}, status=status)


def _authorized(request: web.Request) -> bool:
    expected = request.app[SETTINGS_KEY].api_key
    return request.headers.get("Authorization") == f"Bearer {expected}"


def _require_auth(request: web.Request) -> web.Response | None:
    if not _authorized(request):
        return _json_error("unauthorized", "A valid Bearer token is required.", 401)
    return None


def _job_urls(request: web.Request, job_id: str) -> tuple[str, str]:
    base = f"{request.scheme}://{request.host}"
    return f"{base}/jobs/{job_id}", f"{base}/jobs/{job_id}/result"


def _job_payload(request: web.Request, row: sqlite3.Row) -> dict[str, Any]:
    status_url, result_url = _job_urls(request, str(row["job_id"]))
    payload: dict[str, Any] = {
        "job_id": row["job_id"],
        "filename": row["original_filename"],
        "status": row["status"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "status_url": status_url,
    }
    if row["status"] == "completed":
        payload["result_url"] = result_url
    if row["status"] == "failed":
        payload["error"] = {
            "code": row["error_code"],
            "message": row["error_message"],
        }
    return payload


def _probe_audio(path: Path, maximum_seconds: int) -> None:
    try:
        with av.open(path) as container:
            duration = None if container.duration is None else container.duration / av.time_base
            if duration is not None and duration > maximum_seconds:
                raise ValueError(f"Audio duration exceeds {maximum_seconds} seconds")
            if duration is not None and duration <= 0:
                raise ValueError("Audio has no duration")
            stream = next((item for item in container.streams if item.type == "audio"), None)
            channels = 0 if stream is None else int(stream.codec_context.channels or 0)
            if channels not in {1, 2}:
                raise ValueError("Audio must contain one or two channels")
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(f"Audio cannot be decoded: {error}") from error


def _safe_result(result: dict[str, Any], original_filename: str) -> dict[str, Any]:
    cleaned = dict(result)
    cleaned["source"] = Path(original_filename).name
    cleaned.pop("model_path", None)
    cleaned["files"] = None
    return cleaned


async def _run_job(app: web.Application, job_id: str) -> None:
    settings: Settings = app[SETTINGS_KEY]
    store: JobStore = app[STORE_KEY]
    row = store.get(job_id)
    if row is None or row["status"] != "queued":
        return
    store.mark_running(job_id)
    row = store.get(job_id)
    audio_path = Path(row["audio_path"])
    result_path = Path(row["result_path"])
    try:
        result = await asyncio.to_thread(
            transcribe_audio,
            audio_path,
            model=settings.model,
            device="cuda",
            compute_type="float16",
            language="vi",
            beam_size=5,
            output_dir=None,
        )
        safe_result = _safe_result(result, row["original_filename"])
        result_path.write_text(
            json.dumps(safe_result, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        store.mark_completed(job_id)
    except Exception as error:
        store.mark_failed(job_id, "transcription_failed", str(error))


async def _worker(app: web.Application) -> None:
    queue: asyncio.Queue[str | None] = app[QUEUE_KEY]
    while True:
        job_id = await queue.get()
        try:
            if job_id is None:
                return
            await _run_job(app, job_id)
        finally:
            queue.task_done()


async def _cleanup_loop(app: web.Application) -> None:
    while True:
        await asyncio.sleep(3600)
        _cleanup_expired(app)


def _cleanup_expired(app: web.Application) -> None:
    store: JobStore = app[STORE_KEY]
    cutoff = utc_now() - timedelta(days=app[SETTINGS_KEY].retention_days)
    for row in store.expired_jobs(cutoff):
        job_dir = Path(row["audio_path"]).parent
        shutil.rmtree(job_dir, ignore_errors=True)
        store.delete(str(row["job_id"]))


async def _startup(app: web.Application) -> None:
    settings: Settings = app[SETTINGS_KEY]
    store: JobStore = app[STORE_KEY]
    store.recover_running()
    _cleanup_expired(app)
    await asyncio.to_thread(
        warm_up_model,
        model=settings.model,
        device=settings.device,
        compute_type=settings.compute_type,
    )
    for job_id in store.queued_jobs():
        app[QUEUE_KEY].put_nowait(job_id)
    app[STATE_KEY]["worker_task"] = asyncio.create_task(_worker(app))
    app[STATE_KEY]["cleanup_task"] = asyncio.create_task(_cleanup_loop(app))
    app[STATE_KEY]["ready"] = True


async def _cleanup(app: web.Application) -> None:
    app[STATE_KEY]["ready"] = False
    for key in ("cleanup_task", "worker_task"):
        task = app[STATE_KEY].get(key)
        if task is not None:
            task.cancel()
    worker = app[STATE_KEY].get("worker_task")
    if worker is not None:
        await asyncio.gather(worker, return_exceptions=True)


async def health(request: web.Request) -> web.Response:
    unauthorized = _require_auth(request)
    if unauthorized:
        return unauthorized
    store: JobStore = request.app[STORE_KEY]
    settings: Settings = request.app[SETTINGS_KEY]
    return web.json_response(
        {
            "ready": bool(request.app[STATE_KEY]["ready"]),
            "model": settings.model,
            "model_source_revision": MODEL_ALIASES[settings.model]["source_revision"],
            "device": settings.device,
            "compute_type": settings.compute_type,
            "diarization_enabled": False,
            "diarization_model": None,
            "diarization_device": settings.device,
            "diarization_python_configured": False,
            "queued_jobs": store.count_pending(),
        }
    )


async def create_job(request: web.Request) -> web.Response:
    unauthorized = _require_auth(request)
    if unauthorized:
        return unauthorized
    settings: Settings = request.app[SETTINGS_KEY]
    store: JobStore = request.app[STORE_KEY]
    if not request.app[STATE_KEY]["ready"]:
        return _json_error("not_ready", "The ASR model is not ready.", 503)
    if store.count_pending() >= settings.max_pending_jobs:
        return _json_error("queue_full", "The ASR queue is full.", 429)
    if not request.content_type.startswith("multipart/"):
        return _json_error("invalid_request", "Send the audio as multipart field 'file'.", 400)

    reader = await request.multipart()
    file_part = None
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "file" and file_part is None:
            file_part = part
            break
    if file_part is None or not file_part.filename:
        return _json_error("invalid_request", "Multipart field 'file' is required.", 400)
    extension = Path(file_part.filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        return _json_error("unsupported_format", "Supported formats: WAV, MP3, M4A, FLAC, OGG.", 415)

    job_id = uuid.uuid4().hex
    job_dir = settings.data_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    audio_path = job_dir / f"input{extension}"
    result_path = job_dir / "result.json"
    written = 0
    try:
        with audio_path.open("wb") as output:
            while True:
                chunk = await file_part.read_chunk(size=1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > settings.max_file_bytes:
                    raise web.HTTPRequestEntityTooLarge(max_size=settings.max_file_bytes, actual_size=written)
                output.write(chunk)
        _probe_audio(audio_path, settings.max_audio_seconds)
        store.create_job(job_id, Path(file_part.filename).name, audio_path, result_path)
        request.app[QUEUE_KEY].put_nowait(job_id)
    except web.HTTPRequestEntityTooLarge:
        shutil.rmtree(job_dir, ignore_errors=True)
        return _json_error("file_too_large", "The audio file exceeds the configured limit.", 413)
    except ValueError as error:
        shutil.rmtree(job_dir, ignore_errors=True)
        return _json_error("invalid_audio", str(error), 400)
    except asyncio.QueueFull:
        shutil.rmtree(job_dir, ignore_errors=True)
        store.delete(job_id)
        return _json_error("queue_full", "The ASR queue is full.", 429)
    except Exception as error:
        shutil.rmtree(job_dir, ignore_errors=True)
        store.delete(job_id)
        return _json_error("upload_failed", str(error), 500)

    status_url, result_url = _job_urls(request, job_id)
    return web.json_response(
        {"job_id": job_id, "status": "queued", "status_url": status_url, "result_url": result_url},
        status=202,
    )


async def get_job(request: web.Request) -> web.Response:
    unauthorized = _require_auth(request)
    if unauthorized:
        return unauthorized
    row = request.app[STORE_KEY].get(request.match_info["job_id"])
    if row is None:
        return _json_error("not_found", "Job was not found or has expired.", 404)
    return web.json_response(_job_payload(request, row))


def _load_completed_result(
    request: web.Request,
) -> tuple[dict[str, Any] | None, web.Response | None]:
    unauthorized = _require_auth(request)
    if unauthorized:
        return None, unauthorized
    row = request.app[STORE_KEY].get(request.match_info["job_id"])
    if row is None:
        return None, _json_error("not_found", "Job was not found or has expired.", 404)
    if row["status"] != "completed":
        if row["status"] == "failed":
            return None, _json_error(
                str(row["error_code"]), str(row["error_message"]), 409
            )
        return None, _json_error("not_ready", "The job is not completed.", 409)
    result_path = Path(row["result_path"])
    if not result_path.is_file():
        return None, _json_error(
            "result_missing", "The completed result is unavailable.", 500
        )
    return json.loads(result_path.read_text(encoding="utf-8")), None


async def get_result(request: web.Request) -> web.Response:
    result, error = _load_completed_result(request)
    if error:
        return error
    return web.json_response(result)


def _format_timestamp(seconds: float) -> str:
    milliseconds = max(0, int(round(float(seconds) * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds_part, milliseconds_part = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds_part:02d},{milliseconds_part:03d}"


async def get_text_result(request: web.Request) -> web.Response:
    result, error = _load_completed_result(request)
    if error:
        return error
    lines = [
        f"[{_format_timestamp(segment['start']).replace(',', '.')} -> "
        f"{_format_timestamp(segment['end']).replace(',', '.')}] {segment['text']}"
        for segment in result["segments"]
    ]
    body = "\n".join(lines)
    return _text_file_response(request, body, "txt")


async def get_srt_result(request: web.Request) -> web.Response:
    result, error = _load_completed_result(request)
    if error:
        return error
    blocks = [
        f"{index}\n{_format_timestamp(segment['start'])} --> "
        f"{_format_timestamp(segment['end'])}\n{segment['text']}"
        for index, segment in enumerate(result["segments"], start=1)
    ]
    body = "\n\n".join(blocks)
    return _text_file_response(request, body, "srt")


def _text_file_response(request: web.Request, body: str, extension: str) -> web.Response:
    headers = {}
    if request.query.get("download") == "1":
        job_id = request.match_info["job_id"]
        headers["Content-Disposition"] = f'attachment; filename="{job_id}.{extension}"'
    return web.Response(
        text=body,
        content_type="text/plain",
        charset="utf-8",
        headers=headers,
    )


def create_app(settings: Settings | None = None) -> web.Application:
    resolved_settings = settings or Settings.from_environment()
    app = web.Application(client_max_size=resolved_settings.max_file_bytes + 1024 * 1024)
    app[SETTINGS_KEY] = resolved_settings
    app[STORE_KEY] = JobStore(resolved_settings.data_dir)
    app[QUEUE_KEY] = asyncio.Queue(maxsize=resolved_settings.max_pending_jobs)
    app[STATE_KEY] = {"ready": False}
    app.router.add_get("/health", health, name="health")
    app.router.add_post("/jobs", create_job, name="create-job")
    app.router.add_get("/jobs/{job_id}", get_job, name="job-status")
    app.router.add_get("/jobs/{job_id}/result", get_result, name="job-result")
    app.router.add_get("/jobs/{job_id}/txt", get_text_result, name="job-text-result")
    app.router.add_get("/jobs/{job_id}/srt", get_srt_result, name="job-srt-result")
    app.on_startup.append(_startup)
    app.on_cleanup.append(_cleanup)
    return app


def main() -> None:
    settings = Settings.from_environment()
    print(f"Starting Whisper ASR API on {settings.host}:{settings.port}")
    web.run_app(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
