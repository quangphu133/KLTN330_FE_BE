import sys
import uuid
import multiprocessing
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.core.security import create_access_token, decode_access_token, hash_password
from app.db.database import SessionLocal
from app.main import app
from app.models.asr_job import AsrJob
from app.models.call_record import CallRecord
from app.models.notification import CallNotification
from app.models.user import User
from app.models.violation import Violation
from app.schemas.ai_schema import AIModelResult
from app.schemas.mediafile_schema import WordRoleAssignment
from app.services.asr_service import _set_status, process_asr_result
from app.services.call_service import CallService
from app.services.notification_service import create_upload_notification
from app.services.speaker_attribution import build_stereo_attribution, configured_agent_channel


client = TestClient(app)


def _run_concurrent_asr_worker(job_db_id: int, start_barrier, audio_path: str):
    settings.UPLOAD_DIR = Path(audio_path).parent
    result = {
        "text": "Dạ em chào anh.",
        "duration_seconds": 1,
        "model": "large-v3",
        "diarization": {"status": "disabled"},
        "audio_metadata": {"num_channels": 1, "sample_rate": 16000, "duration_seconds": 1.0},
        "channel_quality": {"auto_role_eligible": False, "reasons": ["mono"], "correlation": None},
        "segments": [{"id": 0, "channel": 0, "start": 0.0, "end": 1.0, "text": "Dạ em chào anh.", "words": []}],
    }

    def wait_for_result(*args, **kwargs):
        start_barrier.wait(timeout=30)
        return result

    with patch("app.services.asr_service.wait_for_result", side_effect=wait_for_result):
        with SessionLocal() as db:
            process_asr_result(db, job_db_id)


def _run_delayed_asr_worker(job_db_id: int, result_ready, release_result, audio_path: str):
    settings.UPLOAD_DIR = Path(audio_path).parent
    result = {
        "text": "lừa đảo mày.",
        "duration_seconds": 1,
        "model": "large-v3",
        "diarization": {"status": "disabled"},
        "audio_metadata": {"num_channels": 1, "sample_rate": 16000, "duration_seconds": 1.0},
        "channel_quality": {"auto_role_eligible": False, "reasons": ["mono"], "correlation": None},
        "segments": [{"id": 0, "channel": 0, "start": 0.0, "end": 1.0, "text": "lừa đảo mày.", "words": []}],
    }

    def wait_for_result(*args, **kwargs):
        result_ready.set()
        if not release_result.wait(timeout=60):
            raise TimeoutError("test result was not released")
        raise TimeoutError("late worker timeout")

    with patch("app.services.asr_service.wait_for_result", side_effect=wait_for_result):
        with SessionLocal() as db:
            process_asr_result(db, job_db_id)


def _headers(role: str) -> dict:
    with SessionLocal() as db:
        user = User(
            email=f"{role}-{uuid.uuid4().hex}@example.com",
            password_hash=hash_password("backend-test-password"),
            full_name=f"Test {role}",
            role=role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token({"sub": str(user.id), "role": role})
    return {"Authorization": f"Bearer {token}"}


def _word(word_id: int, word: str, start: float) -> dict:
    return {"id": word_id, "word": word, "start": start, "end": start + 0.25, "probability": 0.98}


def _stereo_segments(channel_1_opening: str = "Tổng đài HUIT xin chào anh.", channel_0_opening: str = "Xin chào anh.") -> list:
    return [
        {"id": 0, "channel": 0, "text": channel_0_opening, "start": 0.0, "end": 1.0, "words": [_word(0, "Xin", 0.0)]},
        {"id": 1, "channel": 1, "text": channel_1_opening, "start": 0.0, "end": 1.0, "words": [_word(1, "Tổng", 0.0)]},
        {"id": 2, "channel": 0, "text": "Cảm ơn anh.", "start": 1.0, "end": 2.0, "words": [_word(2, "Cảm", 1.0)]},
        {"id": 3, "channel": 1, "text": "Cảm ơn anh.", "start": 1.0, "end": 2.0, "words": [_word(3, "Cảm", 1.0)]},
    ]


def _blank_channel_segments() -> list:
    segments = _stereo_segments(channel_0_opening="Tổng đài HUIT xin chào anh.")
    for segment in segments:
        if segment["channel"] == 1:
            segment["text"] = ""
    return segments


def test_stereo_opening_regex_confirms_unique_channel_and_overrides_default():
    result = build_stereo_attribution(
        _stereo_segments(),
        {"num_channels": 2},
        {"auto_role_eligible": True, "reasons": [], "correlation": 0.1},
        default_channel=0,
        auto_confirm=True,
        organizations=["HUIT", "VinID"],
    )

    assert result["status"] == "confirmed"
    assert result["source"] == "regex"
    assert result["agent_channel"] == 1
    assert result["suggested_agent_speaker_id"] == "CHANNEL_1"
    assert result["assignments"] == {"CHANNEL_0": "customer", "CHANNEL_1": "agent"}
    assert result["evidence"]["sentence"] == "Tổng đài HUIT xin chào anh."


@pytest.mark.parametrize(
    "segments,quality,expected_reason",
    [
        (_stereo_segments(channel_1_opening="Chào anh.", channel_0_opening="Xin chào chị."), {"auto_role_eligible": True, "reasons": []}, "no_unique_employee_opening"),
        (_stereo_segments(channel_1_opening="Tổng đài HUIT xin chào.", channel_0_opening="Em có thể hỗ trợ gì ạ?"), {"auto_role_eligible": True, "reasons": []}, "no_unique_employee_opening"),
        (_stereo_segments(channel_1_opening='"Tổng đài HUIT xin chào anh."', channel_0_opening="Khách nói: em có thể hỗ trợ gì?"), {"auto_role_eligible": True, "reasons": []}, "no_unique_employee_opening"),
        (_stereo_segments(channel_1_opening="Xin nghe.", channel_0_opening="Alo."), {"auto_role_eligible": True, "reasons": []}, "no_unique_employee_opening"),
        (_stereo_segments(), {"auto_role_eligible": False, "reasons": ["channel_correlation_high"]}, "stereo_quality_ineligible"),
        (_blank_channel_segments(), {"auto_role_eligible": True, "reasons": []}, "stereo_quality_ineligible"),
    ],
)
def test_stereo_ambiguous_or_suspicious_inputs_remain_pending(segments, quality, expected_reason):
    result = build_stereo_attribution(
        segments,
        {"num_channels": 2},
        quality,
        default_channel=1,
        auto_confirm=True,
        organizations=["HUIT", "VinID"],
    )

    assert result["status"] == "pending"
    assert result["source"] == "default_config"
    assert result["agent_speaker_id"] is None
    assert result["suggested_agent_speaker_id"] == "CHANNEL_1"
    assert result["reason"] == expected_reason


def test_stereo_regex_suggestion_stays_pending_when_auto_confirmation_is_disabled():
    result = build_stereo_attribution(
        _stereo_segments(),
        {"num_channels": 2},
        {"auto_role_eligible": True, "reasons": []},
        default_channel=0,
        auto_confirm=False,
        organizations=["HUIT"],
    )
    assert result["status"] == "pending"
    assert result["source"] == "regex"
    assert result["suggested_agent_speaker_id"] == "CHANNEL_1"
    assert result["evidence"]["channel"] == 1


def test_default_agent_channel_accepts_only_zero_or_one():
    assert configured_agent_channel("0") == 0
    assert configured_agent_channel(1) == 1
    with pytest.raises(ValueError, match="0 or 1"):
        configured_agent_channel(2)
    with pytest.raises(ValueError, match="0 or 1"):
        configured_agent_channel("invalid")


def test_ai_model_round_trip_preserves_words_channels_metadata_and_attribution():
    payload = {
        "transcript": "Tổng đài HUIT xin chào.",
        "model": "large-v3",
        "duration": 1,
        "diarization": {"status": "disabled"},
        "audio_metadata": {"num_channels": 2, "sample_rate": 16000, "duration_seconds": 1.25},
        "channel_quality": {"auto_role_eligible": True, "reasons": [], "correlation": 0.1},
        "speaker_attribution": {"status": "pending", "source": "default_config"},
        "segments": [{
            "id": 7,
            "channel": 1,
            "start_time": 0.0,
            "end_time": 1.0,
            "text": "Tổng đài HUIT xin chào.",
            "words": [_word(41, "Tổng", 0.0)],
        }],
    }
    result = AIModelResult.model_validate(payload).model_dump(exclude_none=True)
    assert result["model"] == "large-v3"
    assert result["audio_metadata"] == payload["audio_metadata"]
    assert result["channel_quality"] == payload["channel_quality"]
    assert result["segments"][0]["channel"] == 1
    assert result["segments"][0]["words"] == payload["segments"][0]["words"]


def test_employee_cannot_submit_channel_or_role_claims_through_legacy_call_api():
    response = client.post(
        "/api/calls/",
        json={
            "file_path": "not-used.wav",
            "ai_result": {
                "transcript": "Tổng đài HUIT xin chào.",
                "model": "large-v3",
                "audio_metadata": {"num_channels": 2, "sample_rate": 16000, "duration_seconds": 2},
                "channel_quality": {"auto_role_eligible": True, "reasons": [], "correlation": 0.1},
                "speaker_attribution": {"status": "confirmed", "source": "regex", "agent_channel": 0},
                "segments": [{"channel": 0, "speaker": "agent", "text": "Tổng đài HUIT xin chào."}],
            },
        },
        headers=_headers("telesales"),
    )
    assert response.status_code == 403


def test_employee_legacy_call_without_role_metadata_is_saved_unscored():
    audio_path = settings.UPLOAD_DIR / f"legacy-untrusted-{uuid.uuid4().hex}.wav"
    audio_path.write_bytes(b"test-only audio placeholder")
    try:
        response = client.post(
            "/api/calls/",
            json={
                "file_path": str(audio_path),
                "transcript": "Dạ em chào anh. Cảm ơn anh.",
                "ai_result": {
                    "transcript": "Dạ em chào anh. Cảm ơn anh.",
                    "segments": [{"text": "Dạ em chào anh."}, {"text": "Cảm ơn anh."}],
                },
            },
            headers=_headers("telesales"),
        )
        assert response.status_code == 201
        assert response.json()["compliance_score"] is None
    finally:
        audio_path.unlink(missing_ok=True)


def test_admin_legacy_call_without_confirmed_speaker_roles_is_saved_unscored():
    audio_path = settings.UPLOAD_DIR / f"admin-unattributed-{uuid.uuid4().hex}.wav"
    audio_path.write_bytes(b"test-only audio placeholder")
    try:
        response = client.post(
            "/api/calls/",
            json={"file_path": str(audio_path), "transcript": "Dạ em chào anh. Cảm ơn anh."},
            headers=_headers("admin"),
        )
        assert response.status_code == 201
        assert response.json()["compliance_score"] is None
    finally:
        audio_path.unlink(missing_ok=True)


def _create_mono_record(telesale_id: int | None = None) -> tuple[int, dict]:
    analysis_data = {
        "model": "large-v3",
        "audio_metadata": {"num_channels": 1, "sample_rate": 16000, "duration_seconds": 3.0},
        "channel_quality": {"auto_role_eligible": False, "reasons": ["mono"]},
        "diarization": {"status": "disabled"},
        "speaker_attribution": {"status": "pending", "source": "default_config", "reason": "mono_requires_manual_word_roles"},
        "segments": [
            {
                "id": 0, "channel": 0, "start_time": 0.0, "end_time": 1.0,
                "text": "Dạ em chào anh.", "speaker": "unknown",
                "words": [_word(0, "Dạ", 0.0), _word(1, "em", 0.2), _word(2, "chào", 0.4), _word(3, "anh.", 0.6)],
            },
            {
                "id": 1, "channel": 0, "start_time": 1.0, "end_time": 2.0,
                "text": "lừa đảo mày", "speaker": "unknown",
                "words": [_word(4, "lừa", 1.0), _word(5, "đảo", 1.2), _word(6, "mày", 1.4)],
            },
            {
                "id": 2, "channel": 0, "start_time": 2.0, "end_time": 3.0,
                "text": "Cảm ơn anh.", "speaker": "unknown",
                "words": [_word(7, "Cảm", 2.0), _word(8, "ơn", 2.2), _word(9, "anh.", 2.4)],
            },
        ],
    }
    with SessionLocal() as db:
        record = CallRecord(
            telesale_id=telesale_id,
            file_path="manual-word-role-test.wav",
            transcript="Dạ em chào anh. lừa đảo mày. Cảm ơn anh.",
            compliance_score=None,
            analysis_data=analysis_data,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record.id, analysis_data


def test_mono_admin_word_ranges_score_agent_only_and_keep_source_words_immutable():
    record_id, original_data = _create_mono_record()
    admin_headers = _headers("admin")
    employee_headers = _headers("telesales")
    request_body = {"assignments": [
        {"startWordId": 0, "endWordId": 3, "role": "agent"},
        {"startWordId": 4, "endWordId": 6, "role": "customer"},
        {"startWordId": 7, "endWordId": 9, "role": "agent"},
    ]}

    forbidden = client.put(f"/api/mediafile/{record_id}/word-roles", json=request_body, headers=employee_headers)
    assert forbidden.status_code == 403
    response = client.put(f"/api/mediafile/{record_id}/word-roles", json=request_body, headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["complianceScore"] == 100.0
    assert body["roleMapping"]["status"] == "confirmed"
    assert body["roleMapping"]["source"] == "manual"
    assert body["roleMapping"]["assignments"] == [
        {"start_word_id": 0, "end_word_id": 3, "role": "agent"},
        {"start_word_id": 4, "end_word_id": 6, "role": "customer"},
        {"start_word_id": 7, "end_word_id": 9, "role": "agent"},
    ]
    assert body["audioMetadata"]["sample_rate"] == 16000
    assert [region["wordId"] for region in body["stt"]["regions"]] == list(range(10))
    assert all(region["role"] == "customer" for region in body["stt"]["regions"] if region["wordId"] == 5)
    with SessionLocal() as db:
        stored = db.query(CallRecord).filter(CallRecord.id == record_id).one()
        assert stored.analysis_data["segments"] == original_data["segments"]


def test_mono_pending_review_notifies_employee_only_after_score():
    admin_headers = _headers("admin")
    employee_headers = _headers("telesales")
    admin_id = int(decode_access_token(admin_headers["Authorization"].split()[1])["sub"])
    employee_id = int(decode_access_token(employee_headers["Authorization"].split()[1])["sub"])
    record_id, _ = _create_mono_record(employee_id)
    job_id = f"pending-mono-{uuid.uuid4().hex}"
    with SessionLocal() as db:
        record = db.query(CallRecord).filter(CallRecord.id == record_id).one()
        job = AsrJob(job_id=job_id, file_path=record.file_path, status="running", telesale_id=employee_id, call_record_id=record.id)
        db.add(job)
        db.flush()
        job.call_record = record
        create_upload_notification(db, user_id=admin_id, job_id=job_id, asr_job_id=job.id, filename=record.file_path)
        db.commit()
        job_db_id = job.id

    with SessionLocal() as db:
        job = db.query(AsrJob).filter(AsrJob.id == job_db_id).one()
        job.call_record = db.query(CallRecord).filter(CallRecord.id == record_id).one()
        _set_status(db, job, "completed")

    assert [item for item in client.get("/api/notifications/", headers=employee_headers).json() if item["job_id"] == job_id] == []
    assert [item["event_type"] for item in client.get("/api/notifications/", headers=admin_headers).json() if item["job_id"] == job_id] == ["needs_confirmation"]
    ranges = {"assignments": [
        {"startWordId": 0, "endWordId": 3, "role": "agent"},
        {"startWordId": 4, "endWordId": 6, "role": "customer"},
        {"startWordId": 7, "endWordId": 9, "role": "agent"},
    ]}
    for _ in range(2):
        response = client.put(f"/api/mediafile/{record_id}/word-roles", json=ranges, headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["complianceScore"] == 100.0
    employee_done = [item for item in client.get("/api/notifications/", headers=employee_headers).json() if item["job_id"] == job_id]
    assert len(employee_done) == 1
    assert employee_done[0]["event_type"] == "completed"
    assert "100/100" in employee_done[0]["message"]


@pytest.mark.parametrize(
    "assignments",
    [
        [{"startWordId": 0, "endWordId": 3, "role": "agent"}],
        [{"startWordId": 1, "endWordId": 3, "role": "agent"}, {"startWordId": 4, "endWordId": 9, "role": "customer"}],
        [{"startWordId": 0, "endWordId": 4, "role": "customer"}, {"startWordId": 4, "endWordId": 9, "role": "agent"}],
        [{"startWordId": 9, "endWordId": 0, "role": "agent"}],
        [{"startWordId": 0, "endWordId": 9, "role": "customer"}],
        [{"startWordId": 0, "endWordId": 20, "role": "agent"}],
    ],
)
def test_mono_word_ranges_reject_gaps_overlap_reverse_missing_agent_and_unknown_words(assignments):
    record_id, _ = _create_mono_record()
    response = client.put(
        f"/api/mediafile/{record_id}/word-roles",
        json={"assignments": assignments},
        headers=_headers("admin"),
    )
    assert response.status_code == 400
    with SessionLocal() as db:
        stored = db.query(CallRecord).filter(CallRecord.id == record_id).one()
        assert stored.compliance_score is None
        assert stored.analysis_data["speaker_attribution"]["status"] == "pending"


def test_word_role_score_failure_rolls_back_mapping_score_and_violations():
    record_id, _ = _create_mono_record()
    with SessionLocal() as db:
        record = db.query(CallRecord).filter(CallRecord.id == record_id).one()
        record.compliance_score = 77.0
        record.analysis_data = {
            **record.analysis_data,
            "speaker_attribution": {"status": "confirmed", "source": "manual"},
        }
        db.add(Violation(
            call_record_id=record_id,
            violation_type="sensitive_keyword",
            keyword_detected="old",
            snippet="previous accepted violation",
            timestamp=1.0,
            severity="high",
            deduction=20.0,
        ))
        db.commit()

    with patch.object(Session, "commit", side_effect=RuntimeError("commit failed after violation delete")):
        with SessionLocal() as db, pytest.raises(RuntimeError, match="commit failed after violation delete"):
            CallService.confirm_word_roles(
                db,
                record_id,
                [WordRoleAssignment(startWordId=0, endWordId=9, role="agent")],
            )

    with SessionLocal() as db:
        stored = db.query(CallRecord).filter(CallRecord.id == record_id).one()
        assert stored.compliance_score == 77.0
        assert stored.analysis_data["speaker_attribution"] == {"status": "confirmed", "source": "manual"}
        assert [item.snippet for item in stored.violations] == ["previous accepted violation"]


def test_pending_stereo_is_admin_only_then_zero_score_is_notified_once_and_replay_keeps_manual_role():
    admin_headers = _headers("admin")
    employee_headers = _headers("telesales")
    admin_id = int(decode_access_token(admin_headers["Authorization"].split()[1])["sub"])
    employee_id = int(decode_access_token(employee_headers["Authorization"].split()[1])["sub"])
    job_id = f"pending-stereo-{uuid.uuid4().hex}"
    audio_metadata = {"num_channels": 2, "sample_rate": 16000, "duration_seconds": 4.0}
    pending_mapping = {
        "status": "pending", "source": "default_config", "actor": "system",
        "agent_speaker_id": None, "suggested_agent_speaker_id": "CHANNEL_0",
        "agent_channel": None, "default_agent_channel": 0,
        "reason": "no_unique_employee_opening", "evidence": None, "assignments": [],
    }
    segments = [
        {"id": 0, "channel": 0, "speaker": "unknown", "start_time": 0.0, "end_time": 2.0, "text": "mày mày mày mày", "words": [_word(i, "mày", i * 0.25) for i in range(4)]},
        {"id": 1, "channel": 1, "speaker": "unknown", "start_time": 0.0, "end_time": 1.0, "text": "Dạ em chào anh.", "words": [_word(4, "Dạ", 0.0)]},
        {"id": 2, "channel": 1, "speaker": "unknown", "start_time": 1.0, "end_time": 2.0, "text": "Cảm ơn anh.", "words": [_word(5, "Cảm", 1.0)]},
    ]
    with SessionLocal() as db:
        record = CallRecord(
            telesale_id=employee_id,
            file_path="pending-stereo.wav",
            transcript="mày mày mày mày. Dạ em chào anh. Cảm ơn anh.",
            analysis_data={
                "model": "large-v3",
                "audio_metadata": audio_metadata,
                "channel_quality": {"auto_role_eligible": False, "reasons": ["no_unique_employee_opening"]},
                "diarization": {"status": "disabled"},
                "speaker_attribution": pending_mapping,
                "segments": segments,
            },
        )
        db.add(record)
        db.flush()
        job = AsrJob(
            job_id=job_id,
            file_path=record.file_path,
            status="running",
            telesale_id=employee_id,
            call_record_id=record.id,
        )
        db.add(job)
        db.flush()
        job.call_record = record
        create_upload_notification(
            db,
            user_id=admin_id,
            job_id=job_id,
            asr_job_id=job.id,
            filename=record.file_path,
        )
        db.commit()
        record_id, job_db_id = record.id, job.id

    with SessionLocal() as db:
        job = db.query(AsrJob).filter(AsrJob.id == job_db_id).one()
        job.call_record = db.query(CallRecord).filter(CallRecord.id == record_id).one()
        _set_status(db, job, "completed")

    admin_pending = client.get("/api/notifications/", headers=admin_headers).json()
    employee_pending = client.get("/api/notifications/", headers=employee_headers).json()
    assert [item["event_type"] for item in admin_pending if item["job_id"] == job_id] == ["needs_confirmation"]
    assert [item for item in employee_pending if item["job_id"] == job_id] == []
    assert client.get("/api/analytics/me", headers=employee_headers).json()["pendingSpeakerConfirmation"] == 1

    for _ in range(2):
        response = client.put(
            f"/api/mediafile/{record_id}/speaker-roles",
            json={"agentSpeakerId": "CHANNEL_0"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert response.json()["complianceScore"] == 0.0
        assert response.json()["roleMapping"]["assignments"] == {
            "CHANNEL_0": "agent",
            "CHANNEL_1": "customer",
        }

    admin_done = [item for item in client.get("/api/notifications/", headers=admin_headers).json() if item["job_id"] == job_id]
    employee_done = [item for item in client.get("/api/notifications/", headers=employee_headers).json() if item["job_id"] == job_id]
    assert len(admin_done) == len(employee_done) == 1
    assert admin_done[0]["event_type"] == employee_done[0]["event_type"] == "completed"
    assert "0/100" in employee_done[0]["message"]
    with SessionLocal() as db:
        record = db.query(CallRecord).filter(CallRecord.id == record_id).one()
        assert record.analysis_data["speaker_attribution"]["source"] == "manual"
        assert record.analysis_data["speaker_attribution"]["actor"] == "user"
        assert record.analysis_data["speaker_attribution"]["actor_id"] == admin_id
        assert record.analysis_data["segments"] == segments
    with patch("app.services.asr_service.wait_for_result", side_effect=AssertionError("manual result must not replay")):
        with SessionLocal() as db:
            process_asr_result(db, job_db_id)
    with SessionLocal() as db:
        record = db.query(CallRecord).filter(CallRecord.id == record_id).one()
        assert record.analysis_data["speaker_attribution"]["source"] == "manual"
        assert record.compliance_score == 0.0


def test_asr_processing_scores_only_regex_confirmed_agent_and_preserves_word_ids(tmp_path):
    original_auto_confirm = settings.AUTO_CONFIRM_STEREO
    settings.AUTO_CONFIRM_STEREO = True
    audio_path = settings.UPLOAD_DIR / f"stereo-{uuid.uuid4().hex}.wav"
    audio_path.write_bytes(b"labelled stereo fixture")
    with SessionLocal() as db:
        job = AsrJob(job_id=f"stereo-job-{uuid.uuid4().hex}", file_path=str(audio_path), status="queued")
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id
    result = {
        "text": "Xin chào anh. Tổng đài HUIT xin chào anh. lừa đảo mày. Cảm ơn anh.",
        "duration_seconds": 4,
        "model": "large-v3",
        "diarization": {"status": "disabled"},
        "audio_metadata": {"num_channels": 2, "sample_rate": 16000, "duration_seconds": 4.0},
        "channel_quality": {"auto_role_eligible": True, "reasons": [], "correlation": 0.1},
        "segments": [
            {"id": 0, "channel": 0, "start": 0.0, "end": 1.0, "text": "Xin chào anh.", "words": [_word(10, "Xin", 0.0)]},
            {"id": 1, "channel": 1, "start": 0.0, "end": 1.0, "text": "Tổng đài HUIT xin chào anh.", "words": [_word(11, "Tổng", 0.0)]},
            {"id": 2, "channel": 1, "start": 1.0, "end": 2.0, "text": "Cảm ơn anh.", "words": [_word(12, "Cảm", 1.0)]},
            {"id": 3, "channel": 0, "start": 1.0, "end": 2.0, "text": "lừa đảo mày.", "words": [_word(13, "lừa", 1.0)]},
        ],
    }
    try:
        with patch("app.services.asr_service.wait_for_result", return_value=result):
            with SessionLocal() as db:
                process_asr_result(db, job_id)
        with SessionLocal() as db:
            job = db.query(AsrJob).filter(AsrJob.id == job_id).one()
            record = db.query(CallRecord).filter(CallRecord.id == job.call_record_id).one()
            assert job.status == "completed"
            assert record.compliance_score == 100.0
            assert record.analysis_data["speaker_attribution"]["agent_channel"] == 1
            assert record.analysis_data["segments"][0]["words"][0]["id"] == 10
            assert record.analysis_data["segments"][3]["speaker"] == "customer"
            media = client.get(f"/api/mediafile/{record.id}", headers=_headers("admin")).json()
            assert media["numChannels"] == 2
            assert media["sampleRate"] == 16000

            record_id = record.id
            original_mapping = record.analysis_data["speaker_attribution"]
            original_score = record.compliance_score
        with patch("app.services.asr_service.wait_for_result", side_effect=AssertionError("must not replay")):
            with SessionLocal() as db:
                process_asr_result(db, job_id)
        with SessionLocal() as db:
            record = db.query(CallRecord).filter(CallRecord.id == record_id).one()
            assert record.analysis_data["speaker_attribution"] == original_mapping
            assert record.compliance_score == original_score
    finally:
        settings.AUTO_CONFIRM_STEREO = original_auto_confirm
        audio_path.unlink(missing_ok=True)


def test_asr_call_and_job_link_roll_back_together_if_terminal_commit_fails():
    audio_path = settings.UPLOAD_DIR / f"atomic-asr-{uuid.uuid4().hex}.wav"
    audio_path.write_bytes(b"labelled mono fixture")
    with SessionLocal() as db:
        job = AsrJob(job_id=f"atomic-job-{uuid.uuid4().hex}", file_path=str(audio_path), status="queued")
        db.add(job)
        db.commit()
        db.refresh(job)
        job_db_id = job.id
    result = {
        "text": "Dạ em chào anh.",
        "duration_seconds": 1,
        "model": "large-v3",
        "diarization": {"status": "disabled"},
        "audio_metadata": {"num_channels": 1, "sample_rate": 16000, "duration_seconds": 1.0},
        "channel_quality": {"auto_role_eligible": False, "reasons": ["mono"], "correlation": None},
        "segments": [{"id": 0, "channel": 0, "start": 0.0, "end": 1.0, "text": "Dạ em chào anh.", "words": []}],
    }
    original_create_call = CallService.create_call

    def create_then_fail_before_link(**kwargs):
        original_create_call(**kwargs)
        raise RuntimeError("failure before job link")

    try:
        with patch("app.services.asr_service.wait_for_result", return_value=result), patch.object(
            CallService, "create_call", side_effect=create_then_fail_before_link
        ):
            with SessionLocal() as db:
                process_asr_result(db, job_db_id)
        with SessionLocal() as db:
            job = db.query(AsrJob).filter(AsrJob.id == job_db_id).one()
            assert job.status == "failed"
            assert job.call_record_id is None
            assert db.query(CallRecord).filter(CallRecord.file_path == str(audio_path)).count() == 0
    finally:
        audio_path.unlink(missing_ok=True)


def test_rejected_asr_completion_rolls_back_new_call_record():
    audio_path = settings.UPLOAD_DIR / f"rejected-asr-{uuid.uuid4().hex}.wav"
    audio_path.write_bytes(b"labelled mono fixture")
    with SessionLocal() as db:
        job = AsrJob(job_id=f"rejected-job-{uuid.uuid4().hex}", file_path=str(audio_path), status="queued")
        db.add(job)
        db.commit()
        db.refresh(job)
        job_db_id = job.id
    result = {
        "text": "Dạ em chào anh.",
        "duration_seconds": 1,
        "model": "large-v3",
        "diarization": {"status": "disabled"},
        "audio_metadata": {"num_channels": 1, "sample_rate": 16000, "duration_seconds": 1.0},
        "channel_quality": {"auto_role_eligible": False, "reasons": ["mono"], "correlation": None},
        "segments": [{"id": 0, "channel": 0, "start": 0.0, "end": 1.0, "text": "Dạ em chào anh.", "words": []}],
    }
    original_set_status = _set_status

    def reject_completion(db, job, status, error_message=None):
        if status == "completed":
            job.status = "completed"
        return original_set_status(db, job, status, error_message)

    try:
        with patch("app.services.asr_service.wait_for_result", return_value=result), patch(
            "app.services.asr_service._set_status", side_effect=reject_completion
        ):
            with SessionLocal() as db:
                process_asr_result(db, job_db_id)
        with SessionLocal() as db:
            job = db.query(AsrJob).filter(AsrJob.id == job_db_id).one()
            assert job.status == "running"
            assert job.call_record_id is None
            assert db.query(CallRecord).filter(CallRecord.file_path == str(audio_path.resolve()).replace("\\", "/")).count() == 0
    finally:
        audio_path.unlink(missing_ok=True)


@pytest.mark.skipif(not os.environ.get("KLTN_TEST_DATABASE_URL", "").startswith("postgresql"), reason="requires the isolated PostgreSQL concurrency test database")
def test_two_processes_finalize_one_asr_job_without_orphan_or_overwrite():
    audio_path = settings.UPLOAD_DIR / f"parallel-{uuid.uuid4().hex}.wav"
    audio_path.write_bytes(b"isolated parallel processing fixture")
    with SessionLocal() as db:
        job = AsrJob(job_id=f"parallel-job-{uuid.uuid4().hex}", file_path=str(audio_path), status="queued")
        db.add(job)
        db.commit()
        db.refresh(job)
        job_db_id = job.id

    context = multiprocessing.get_context("spawn")
    start_barrier = context.Barrier(2)
    workers = [
        context.Process(target=_run_concurrent_asr_worker, args=(job_db_id, start_barrier, str(audio_path)))
        for _ in range(2)
    ]
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=60)
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
        assert [worker.exitcode for worker in workers] == [0, 0]

        with SessionLocal() as db:
            job = db.query(AsrJob).filter(AsrJob.id == job_db_id).one()
            records = db.query(CallRecord).filter(CallRecord.file_path == str(audio_path.resolve()).replace("\\", "/")).all()
            assert job.status == "completed"
            assert job.call_record_id is not None
            assert len(records) == 1
            assert records[0].id == job.call_record_id
            assert records[0].compliance_score is None
            assert records[0].analysis_data["speaker_attribution"]["status"] == "pending"
    finally:
        audio_path.unlink(missing_ok=True)


@pytest.mark.skipif(not os.environ.get("KLTN_TEST_DATABASE_URL", "").startswith("postgresql"), reason="requires the isolated PostgreSQL concurrency test database")
def test_late_postgresql_poll_failure_cannot_overwrite_admin_correction():
    audio_path = settings.UPLOAD_DIR / f"late-worker-{uuid.uuid4().hex}.wav"
    audio_path.write_bytes(b"isolated late-worker fixture")
    agent_text = "Tổng đài HUIT xin chào anh."
    words = [
        _word(0, "Tổng", 0.0),
        _word(1, "đài", 0.1),
        _word(2, "HUIT", 0.2),
        _word(3, "xin", 0.3),
        _word(4, "chào", 0.4),
        _word(5, "anh.", 0.5),
    ]
    result = {
        "text": agent_text,
        "duration_seconds": 1,
        "model": "large-v3",
        "diarization": {"status": "disabled"},
        "audio_metadata": {"num_channels": 1, "sample_rate": 16000, "duration_seconds": 1.0},
        "channel_quality": {"auto_role_eligible": False, "reasons": ["mono"], "correlation": None},
        "segments": [{"id": 0, "channel": 0, "start": 0.0, "end": 1.0, "text": agent_text, "words": words}],
    }
    with SessionLocal() as db:
        employee = User(
            email=f"late-worker-{uuid.uuid4().hex}@example.com",
            password_hash=hash_password("backend-test-password"),
            full_name="Late Worker Test",
            role="telesales",
            is_active=True,
        )
        db.add(employee)
        db.flush()
        job_id = f"late-job-{uuid.uuid4().hex}"
        job = AsrJob(
            job_id=job_id,
            file_path=str(audio_path),
            status="queued",
            telesale_id=employee.id,
        )
        db.add(job)
        db.flush()
        create_upload_notification(
            db,
            user_id=employee.id,
            job_id=job_id,
            asr_job_id=job.id,
            filename=audio_path.name,
        )
        db.commit()
        db.refresh(job)
        job_db_id = job.id

    context = multiprocessing.get_context("spawn")
    result_ready = context.Event()
    release_result = context.Event()
    late_worker = context.Process(
        target=_run_delayed_asr_worker,
        args=(job_db_id, result_ready, release_result, str(audio_path)),
    )
    try:
        late_worker.start()
        assert result_ready.wait(timeout=30), "late worker did not reach its ASR wait"

        with patch("app.services.asr_service.wait_for_result", return_value=result):
            with SessionLocal() as db:
                process_asr_result(db, job_db_id)
        with SessionLocal() as db:
            job = db.query(AsrJob).filter(AsrJob.id == job_db_id).one()
            call_record_id = job.call_record_id
            assert call_record_id is not None
            assert job.status == "completed"

        response = client.put(
            f"/api/mediafile/{call_record_id}/word-roles",
            json={"assignments": [{"startWordId": 0, "endWordId": 5, "role": "agent"}]},
            headers=_headers("admin"),
        )
        assert response.status_code == 200
        with SessionLocal() as db:
            record = db.query(CallRecord).filter(CallRecord.id == call_record_id).one()
            assert record.analysis_data["speaker_attribution"]["source"] == "manual"
            assert record.compliance_score == 90.0
            assert record.transcript == agent_text
            notification = db.query(CallNotification).filter(CallNotification.asr_job_id == job_db_id).one()
            notification_before = (
                notification.id,
                notification.event_type,
                notification.title,
                notification.message,
                notification.call_record_id,
                notification.is_read,
            )

        release_result.set()
        late_worker.join(timeout=60)
        if late_worker.is_alive():
            late_worker.terminate()
            late_worker.join(timeout=5)
        assert late_worker.exitcode == 0
        with SessionLocal() as db:
            job = db.query(AsrJob).filter(AsrJob.id == job_db_id).one()
            records = db.query(CallRecord).filter(CallRecord.file_path == str(audio_path.resolve()).replace("\\", "/")).all()
            record = db.query(CallRecord).filter(CallRecord.id == call_record_id).one()
            assert job.call_record_id == call_record_id
            assert job.status == "completed"
            assert job.error_message is None
            assert len(records) == 1
            assert record.analysis_data["speaker_attribution"]["source"] == "manual"
            assert record.compliance_score == 90.0
            assert record.transcript == agent_text
            notification = db.query(CallNotification).filter(CallNotification.asr_job_id == job_db_id).one()
            assert (
                notification.id,
                notification.event_type,
                notification.title,
                notification.message,
                notification.call_record_id,
                notification.is_read,
            ) == notification_before
    finally:
        release_result.set()
        if late_worker.is_alive():
            late_worker.terminate()
            late_worker.join(timeout=5)
        audio_path.unlink(missing_ok=True)
