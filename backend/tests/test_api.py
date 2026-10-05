import sys
import os
from io import BytesIO
from pathlib import Path
import time
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import load_workbook

# Add the project root directory to sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app
from app.asr_client import AsrApiError
from app.db.database import SessionLocal
from app.db.init_db import initialize_database
from app.models.asr_job import AsrJob
from app.models.call_record import CallRecord
from app.models.notification import CallNotification
from app.models.violation import Violation
from app.models.vocabulary import Vocabulary
from app.services.analytics_service import AnalyticsService
from app.core.security import create_access_token, decode_access_token
from app.core.security import hash_password
from app.models.user import User
from datetime import timedelta


client = TestClient(app)


def admin_headers():
    with SessionLocal() as db:
        admin = db.query(User).filter(User.role == "admin").first()
        if admin is None:
            admin = User(
                email="backend-tests-admin@example.com",
                password_hash=hash_password("test-only-password"),
                full_name="Backend Test Admin",
                role="admin",
                is_active=True,
            )
            db.add(admin)
            db.commit()
            db.refresh(admin)
        token = create_access_token({"sub": str(admin.id), "role": "admin"})
    return {"Authorization": f"Bearer {token}"}


def create_telesale(email: str) -> tuple[int, dict[str, str]]:
    with SessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password("test-only-password"),
            full_name="Test Telesale",
            role="telesales",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token({"sub": str(user.id), "role": user.role})
        return user.id, {"Authorization": f"Bearer {token}"}


def test_health_check():
    res = client.get("/")
    assert res.status_code == 200
    assert res.json()["status"] == "online"


def test_legacy_api_v1_is_removed():
    assert client.get("/api/v1/auth/signin").status_code == 404
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/auth/signin" in paths
    assert not any(path.startswith("/api/v1/") for path in paths)


def test_database_initialization_is_idempotent_and_preserves_edited_regex():
    initialize_database()
    with SessionLocal() as db:
        entry = db.query(Vocabulary).filter(Vocabulary.name == "Regex | Lời chào bắt buộc").one()
        original_data = entry.data
        entry.data = {"phrases": ["custom test value"]}
        db.commit()

    initialize_database()
    with SessionLocal() as db:
        entry = db.query(Vocabulary).filter(Vocabulary.name == "Regex | Lời chào bắt buộc").one()
        assert entry.data == {"phrases": ["custom test value"]}
        entry.data = original_data
        db.commit()


def test_failed_asr_upload_is_saved_without_a_score():
    files = {"file": ("offline-call.wav", b"audio", "audio/wav")}
    with patch(
        "app.services.asr_service.submit_to_asr",
        side_effect=AsrApiError(503, "unavailable", "ASR unavailable"),
    ):
        response = client.post("/api/transcribe/upload", files=files, headers=admin_headers())

    assert response.status_code == 202
    assert response.json()["status"] == "failed"
    record_id = response.json()["call_record_id"]
    with SessionLocal() as db:
        record = db.query(CallRecord).filter(CallRecord.id == record_id).one()
        assert record.compliance_score is None
        dashboard = AnalyticsService.get_dashboard(db)
        assert dashboard["summaryData"]["averageNegativeLevelOverall"] is None

    headers = admin_headers()
    result = client.get(f"/api/mediafile/{record_id}/result", headers=headers)
    assert result.status_code == 200
    assert result.json()["stt"]["text"] is None

    exported = client.get("/api/mediafile/export/excel", headers=headers)
    assert exported.status_code == 200
    sheet = load_workbook(BytesIO(exported.content), read_only=True).active
    assert any(row[0] == record_id and row[6] == "Chưa chấm điểm" for row in sheet.iter_rows(min_row=2, values_only=True))


def test_mediafile_result_marks_only_stored_non_missing_timestamps_as_available():
    with SessionLocal() as db:
        record = CallRecord(
            file_path="timestamp-metadata.wav",
            transcript="Synthetic transcript for timestamp metadata coverage.",
            compliance_score=0.0,
        )
        db.add(record)
        db.flush()
        db.add_all([
            Violation(
                call_record_id=record.id,
                violation_type="negative_attitude",
                timestamp=None,
            ),
            Violation(
                call_record_id=record.id,
                violation_type="sensitive_keyword",
                timestamp=0.0,
                deduction=0.0,
            ),
            Violation(
                call_record_id=record.id,
                violation_type="forced_selling",
                timestamp=2.5,
            ),
            Violation(
                call_record_id=record.id,
                violation_type="missing_greeting",
                timestamp=0.0,
            ),
        ])
        db.commit()
        call_id = record.id

    response = client.get(f"/api/mediafile/{call_id}/result", headers=admin_headers())

    assert response.status_code == 200
    result = response.json()
    assert result["complianceScore"] == 0.0
    regions = {item["categoryName"]: item for item in result["keywordsSearchResult"]["regions"]}
    assert regions["negative_attitude"]["hasTimestamp"] is False
    assert regions["negative_attitude"]["startTime"] == 0.0
    assert regions["sensitive_keyword"]["hasTimestamp"] is True
    assert regions["sensitive_keyword"]["startTime"] == 0.0
    assert regions["sensitive_keyword"]["endTime"] == 2.0
    assert regions["sensitive_keyword"]["deduction"] == 0.0
    assert regions["forced_selling"]["hasTimestamp"] is True
    assert regions["forced_selling"]["startTime"] == 2.5
    assert regions["forced_selling"]["endTime"] == 4.5
    assert regions["missing_greeting"]["hasTimestamp"] is False


def test_user_crud():
    username = f"telesale_{int(time.time())}"

    # 1. Create
    user_payload = {
        "email": f"{username}@example.com",
        "password": "password123",
        "full_name": "Nguyen Van B",
        "role": "telesales",
    }

    headers = admin_headers()
    res_create = client.post("/api/users/", json=user_payload, headers=headers)
    assert res_create.status_code == 201
    user_id = res_create.json()["id"]

    # 2. Get by ID
    res_get = client.get(f"/api/users/{user_id}", headers=headers)
    assert res_get.status_code == 200
    assert res_get.json()["email"] == f"{username}@example.com"

    # 3. Update
    res_update = client.put(
        f"/api/users/{user_id}",
        json={"full_name": "Nguyen Van B - VIP"},
        headers=headers,
    )
    assert res_update.status_code == 200
    assert res_update.json()["full_name"] == "Nguyen Van B - VIP"

    # 4. List
    res_list = client.get("/api/users/", headers=headers)
    assert res_list.status_code == 200
    assert any(user["id"] == user_id for user in res_list.json())

    # 5. Delete
    res_delete = client.delete(f"/api/users/{user_id}", headers=headers)
    assert res_delete.status_code == 200


def test_email_signin_and_expired_token():
    email = f"signin_{int(time.time())}@example.com"
    created = client.post(
        "/api/users/",
        json={
            "email": email,
            "password": "password123",
            "full_name": "Sign In Test",
            "role": "telesales",
        },
        headers=admin_headers(),
    )
    assert created.status_code == 201

    response = client.post(
        "/api/auth/signin",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200
    assert decode_access_token(response.json()["accessToken"])["email"] == email

    expired = create_access_token({"sub": str(created.json()["id"])}, timedelta(seconds=-1))
    assert decode_access_token(expired) is None


def test_audio_file_upload_and_analysis_flow():
    # 1. Upload audio
    dummy_audio = b"RIFF....WAVEfmt ....data...."
    files = {
        "file": (
            "demo_call.wav",
            dummy_audio,
            "audio/wav",
        )
    }

    headers = admin_headers()
    res_file = client.post("/api/files/upload", files=files, headers=headers)
    assert res_file.status_code == 201
    file_path = res_file.json()["file_path"]

    # 2. Process AI JSON result and create a call record.
    ai_call_payload = {
        "file_path": file_path,
        "ai_result": {
            "transcript": (
                "Dạ em chào quý khách, em gọi tư vấn gói bảo hiểm. "
                "Mày không mua thì lượn đi."
            ),
            "segments": [
                {
                    "speaker": "agent",
                    "start_time": 0.0,
                    "end_time": 3.2,
                    "text": (
                        "Dạ em chào quý khách, "
                        "em gọi tư vấn gói bảo hiểm."
                    ),
                },
                {
                    "speaker": "customer",
                    "start_time": 3.5,
                    "end_time": 5.0,
                    "text": "Tôi bận lắm.",
                },
                {
                    "speaker": "agent",
                    "start_time": 5.2,
                    "end_time": 7.8,
                    "text": "Mày không mua thì lượn đi.",
                },
            ],
"sentiment": "negative",
            "duration": 8,
        },
    }

    res_call = client.post("/api/calls/", json=ai_call_payload, headers=headers)
    assert res_call.status_code == 201

    call_json = res_call.json()
    call_id = call_json["id"]

    assert call_json["compliance_score"] < 100.0
    assert len(call_json["violations"]) > 0

    # 3. Query violations
    res_violations = client.get(
        f"/api/violations/?call_record_id={call_id}", headers=headers
    )
    assert res_violations.status_code == 200
    assert len(res_violations.json()) > 0

    # 4. Cleanup
    res_delete = client.request(
        "DELETE",
        f"/api/calls/{call_id}",
        json={"reason": "Dữ liệu thử nghiệm đã hoàn tất."},
        headers=headers,
    )
    assert res_delete.status_code == 200


def test_employee_user_filter_excludes_admin_and_applies_before_pagination():
    headers = admin_headers()
    created_ids = []
    for suffix in range(3):
        response = client.post(
            "/api/users/",
            json={
                "email": f"employee-filter-{time.time_ns()}-{suffix}@example.com",
                "password": "test-password",
                "full_name": f"Employee {suffix}",
                "role": "telesales",
            },
            headers=headers,
        )
        assert response.status_code == 201
        created_ids.append(response.json()["id"])

    first_page = client.get("/api/users/?role=telesales&skip=0&limit=2", headers=headers)
    second_page = client.get("/api/users/?role=telesales&skip=2&limit=2", headers=headers)
    assert first_page.status_code == second_page.status_code == 200
    first_ids = [item["id"] for item in first_page.json()]
    second_ids = [item["id"] for item in second_page.json()]
    assert first_ids == sorted(first_ids)
    assert second_ids == sorted(second_ids)
    assert set(created_ids).issubset(set(first_ids + second_ids))
    assert all(item["role"] == "telesales" for item in first_page.json() + second_page.json())


def test_operator_endpoints_and_legacy_operator_id_are_rejected():
    headers = admin_headers()
    paths = client.get("/openapi.json").json()["paths"]
    assert not any(path.startswith("/api/operators") for path in paths)
    assert client.get("/api/mediafile/?operatorId=1", headers=headers).status_code == 422

    response = client.post(
        "/api/transcribe/upload",
        files={"file": ("legacy-operator.wav", b"audio", "audio/wav")},
        data={"operatorId": "1"},
        headers=headers,
    )
    assert response.status_code == 422


def test_admin_transcribe_upload_assigns_selected_employee():
    employee_id, employee_headers = create_telesale(f"admin-upload-{time.time_ns()}@example.com")
    files = {"file": ("admin-upload.wav", b"audio", "audio/wav")}
    admin = admin_headers()
    with patch(
        "app.services.asr_service.submit_to_asr",
        side_effect=AsrApiError(503, "unavailable", "ASR unavailable"),
    ):
        response = client.post(
            "/api/transcribe/upload",
            files=files,
            data={"telesale_id": str(employee_id)},
            headers=admin,
        )

    assert response.status_code == 202
    with SessionLocal() as db:
        job = db.query(AsrJob).filter(AsrJob.id == response.json()["id"]).one()
        record = db.query(CallRecord).filter(CallRecord.id == job.call_record_id).one()
        assert job.telesale_id == employee_id
        assert record.telesale_id == employee_id
    job_id = response.json()["job_id"]
    uploader_notifications = [
        item for item in client.get("/api/notifications/", headers=admin).json()
        if item["job_id"] == job_id
    ]
    employee_notifications = [
        item for item in client.get("/api/notifications/", headers=employee_headers).json()
        if item["job_id"] == job_id
    ]
    assert len(uploader_notifications) == len(employee_notifications) == 1
    assert uploader_notifications[0]["job_status"] == "failed"
    assert uploader_notifications[0]["event_type"] == employee_notifications[0]["event_type"] == "failed"


def test_employee_sync_apis_are_scoped_and_keep_zero_score():
    owner_id, owner_headers = create_telesale("sync-owner@example.com")
    other_id, other_headers = create_telesale("sync-other@example.com")
    with SessionLocal() as db:
        own_record = CallRecord(
            telesale_id=owner_id,
            file_path="missing-owner-audio.wav",
            compliance_score=0,
            analysis_data={
                "diarization": {
                    "status": "completed",
                    "speakers": [{"speaker_id": "speaker_0"}, {"speaker_id": "speaker_1"}],
                    "role_mapping": {},
                }
            },
        )
        other_record = CallRecord(
            telesale_id=other_id,
            file_path="missing-other-audio.wav",
            compliance_score=75,
        )
        db.add_all([own_record, other_record])
        db.flush()
        own_job = AsrJob(job_id="sync-owner-job", file_path=own_record.file_path, status="failed", telesale_id=owner_id, call_record_id=own_record.id, error_message="test failure")
        other_job = AsrJob(job_id="sync-other-job", file_path=other_record.file_path, status="queued", telesale_id=other_id)
        db.add_all([own_job, other_job])
        db.flush()
        own_notification = CallNotification(
            user_id=owner_id,
            event_key="sync-owner-event",
            event_type="failed",
            title="Failure",
            message="Test event",
            call_record_id=own_record.id,
            asr_job_id=own_job.id,
        )
        other_notification = CallNotification(
            user_id=other_id,
            event_key="sync-other-event",
            event_type="queued",
            title="Queued",
            message="Other user's event",
            call_record_id=other_record.id,
            asr_job_id=other_job.id,
        )
        db.add_all([own_notification, other_notification])
        db.commit()
        own_record_id = own_record.id
        other_record_id = other_record.id
        own_job_id = own_job.job_id
        other_job_id = other_job.job_id
        own_notification_id = own_notification.id
        other_notification_id = other_notification.id

    analytics = client.get("/api/analytics/me", headers=owner_headers)
    assert analytics.status_code == 200
    assert analytics.json()["totalCalls"] == 1
    assert analytics.json()["pendingSpeakerConfirmation"] == 1
    assert analytics.json()["averageScore"] == 0
    assert analytics.json()["recentCalls"][0]["id"] == own_record_id

    media_files = client.get("/api/mediafile/", headers=owner_headers)
    assert media_files.status_code == 200
    assert media_files.json()["totalCount"] == 1
    assert media_files.json()["mediaFile"][0]["complianceScore"] == 0
    assert media_files.json()["mediaFile"][0]["transcriptionStatus"] == "failed"
    assert client.get(f"/api/mediafile/{other_record_id}/result", headers=owner_headers).status_code == 404
    assert client.get(f"/api/mediafile/{other_record_id}/stream", headers=owner_headers).status_code == 404

    jobs = client.get("/api/transcribe/", headers=owner_headers)
    assert jobs.status_code == 200
    assert [job["job_id"] for job in jobs.json()] == [own_job_id]
    assert client.get(f"/api/transcribe/{other_job_id}/status", headers=owner_headers).status_code == 404

    notifications = client.get("/api/notifications/", headers=owner_headers)
    assert notifications.status_code == 200
    assert [item["id"] for item in notifications.json()] == [own_notification_id]
    assert notifications.json()[0]["job_id"] == own_job_id
    assert notifications.json()[0]["job_status"] == "failed"
    assert client.patch(f"/api/notifications/{other_notification_id}/read", headers=owner_headers).status_code == 404
    first_read = client.patch(f"/api/notifications/{own_notification_id}/read", headers=owner_headers)
    second_read = client.patch(f"/api/notifications/{own_notification_id}/read", headers=owner_headers)
    assert first_read.status_code == second_read.status_code == 200
    assert first_read.json()["is_read"] is True


def test_employee_upload_assigns_owner_when_ai_is_offline():
    owner_id, owner_headers = create_telesale("upload-owner@example.com")
    files = {"file": ("owner-offline.wav", b"audio", "audio/wav")}
    with patch(
        "app.services.asr_service.submit_to_asr",
        side_effect=AsrApiError(503, "unavailable", "ASR unavailable"),
    ):
        response = client.post("/api/transcribe/upload", files=files, headers=owner_headers)

    assert response.status_code == 202
    record_id = response.json()["call_record_id"]
    job_id = response.json()["job_id"]
    with SessionLocal() as db:
        record = db.query(CallRecord).filter(CallRecord.id == record_id).one()
        job = db.query(AsrJob).filter(AsrJob.call_record_id == record_id).one()
        assert record.telesale_id == owner_id
        assert job.telesale_id == owner_id
    notifications = client.get("/api/notifications/", headers=owner_headers).json()
    upload_notifications = [item for item in notifications if item["job_id"] == job_id]
    assert len(upload_notifications) == 1
    assert upload_notifications[0]["event_type"] == "failed"
    assert upload_notifications[0]["job_status"] == "failed"
    assert "chưa phân tích được" in upload_notifications[0]["message"]
    own_calls = client.get("/api/mediafile/", headers=owner_headers).json()["mediaFile"]
    assert any(call["id"] == record_id for call in own_calls)


def test_successful_upload_creates_one_processing_notification_for_uploader():
    uploader_id, uploader_headers = create_telesale(f"upload-queued-{time.time_ns()}@example.com")
    job_id = f"upload-queued-{time.time_ns()}"

    def fake_submit_to_asr(**kwargs):
        job = AsrJob(
            job_id=job_id,
            file_path=kwargs["file_path"],
            status="queued",
            telesale_id=kwargs["telesale_id"],
        )
        kwargs["db"].add(job)
        kwargs["db"].flush()
        return job

    with patch("app.services.asr_service.submit_to_asr", side_effect=fake_submit_to_asr), patch(
        "app.api.v1.endpoints.transcribe._background_process"
    ):
        response = client.post(
            "/api/transcribe/upload",
            files={"file": ("follow-up-call.wav", b"audio", "audio/wav")},
            headers=uploader_headers,
        )

    assert response.status_code == 202
    notifications = client.get("/api/notifications/", headers=uploader_headers).json()
    upload_notifications = [item for item in notifications if item["job_id"] == job_id]
    assert upload_notifications == []


def test_processing_upload_notification_changes_to_failure_without_duplicates():
    uploader_id, uploader_headers = create_telesale(f"upload-failed-{time.time_ns()}@example.com")
    job_id = f"upload-failed-{time.time_ns()}"

    with SessionLocal() as db:
        job = AsrJob(job_id=job_id, file_path="worker-failure.wav", status="running")
        db.add(job)
        db.flush()
        from app.services.notification_service import create_upload_notification

        notification = create_upload_notification(
            db,
            user_id=uploader_id,
            job_id=job_id,
            asr_job_id=job.id,
            filename="worker-failure.wav",
        )
        db.commit()
        notification_id = notification.id

    with SessionLocal() as db:
        from app.services.asr_service import _set_status

        job = db.query(AsrJob).filter(AsrJob.job_id == job_id).one()
        _set_status(db, job, "failed", error_message="worker error")

    notification = next(
        item for item in client.get("/api/notifications/", headers=uploader_headers).json()
        if item["job_id"] == job_id
    )
    assert notification["id"] == notification_id
    assert notification["job_status"] == "failed"
    assert notification["event_type"] == "failed"
    assert "không xử lý được" in notification["message"]


def test_upload_notification_updates_once_and_notifies_assigned_employee():
    uploader_id, uploader_headers = create_telesale(f"uploading-admin-{time.time_ns()}@example.com")
    employee_id, employee_headers = create_telesale(f"assigned-worker-{time.time_ns()}@example.com")
    job_id = f"upload-completed-{time.time_ns()}"

    with SessionLocal() as db:
        call_record = CallRecord(
            telesale_id=employee_id,
            file_path="notification-lifecycle.wav",
            analysis_data={
                "diarization": {
                    "status": "completed",
                    "speakers": [{"speaker_id": "speaker_0"}, {"speaker_id": "speaker_1"}],
                    "role_mapping": {},
                }
            },
        )
        db.add(call_record)
        db.flush()
        job = AsrJob(
            job_id=job_id,
            file_path=call_record.file_path,
            status="running",
            telesale_id=employee_id,
            call_record_id=call_record.id,
        )
        db.add(job)
        db.flush()
        from app.services.notification_service import create_upload_notification

        notification = create_upload_notification(
            db,
            user_id=uploader_id,
            job_id=job_id,
            asr_job_id=job.id,
            filename="two-speakers.wav",
        )
        db.commit()
        notification_id = notification.id

    with SessionLocal() as db:
        from app.services.asr_service import _set_status

        job = db.query(AsrJob).filter(AsrJob.job_id == job_id).one()
        _set_status(db, job, "completed")

    uploader_notifications = [
        item for item in client.get("/api/notifications/", headers=uploader_headers).json()
        if item["job_id"] == job_id
    ]
    employee_notifications = [
        item for item in client.get("/api/notifications/", headers=employee_headers).json()
        if item["job_id"] == job_id
    ]
    assert uploader_notifications == []
    assert employee_notifications == []
    with SessionLocal() as db:
        stored = db.query(CallNotification).filter(CallNotification.id == notification_id).one()
        assert stored.event_type == "needs_confirmation"

    with SessionLocal() as db:
        from app.services.asr_service import _set_status

        notification = db.query(CallNotification).filter(CallNotification.id == notification_id).one()
        notification.is_read = True
        job = db.query(AsrJob).filter(AsrJob.job_id == job_id).one()
        _set_status(db, job, "completed")
        assert notification.is_read is True

    assert len([
        item for item in client.get("/api/notifications/", headers=uploader_headers).json()
        if item["job_id"] == job_id
    ]) == 0
    assert len([
        item for item in client.get("/api/notifications/", headers=employee_headers).json()
        if item["job_id"] == job_id
    ]) == 0

    same_user_job_id = f"upload-same-user-{time.time_ns()}"
    with SessionLocal() as db:
        call_record = CallRecord(
            telesale_id=employee_id,
            file_path="same-uploader-owner.wav",
            analysis_data={
                "diarization": {
                    "status": "completed",
                    "speakers": [{"speaker_id": "speaker_0"}, {"speaker_id": "speaker_1"}],
                    "role_mapping": {},
                }
            },
        )
        db.add(call_record)
        db.flush()
        job = AsrJob(
            job_id=same_user_job_id,
            file_path=call_record.file_path,
            status="running",
            telesale_id=employee_id,
            call_record_id=call_record.id,
        )
        db.add(job)
        db.flush()
        from app.services.notification_service import create_upload_notification

        create_upload_notification(
            db,
            user_id=employee_id,
            job_id=same_user_job_id,
            asr_job_id=job.id,
            filename="same-uploader-owner.wav",
        )
        db.commit()

    with SessionLocal() as db:
        from app.services.asr_service import _set_status

        job = db.query(AsrJob).filter(AsrJob.job_id == same_user_job_id).one()
        _set_status(db, job, "completed")

    same_user_notifications = [
        item for item in client.get("/api/notifications/", headers=employee_headers).json()
        if item["job_id"] == same_user_job_id
    ]
    assert same_user_notifications == []


def test_admin_speaker_confirmation_scores_once_and_notifies_employee_with_violation_deductions():
    employee_id, employee_headers = create_telesale(f"speaker-confirm-{time.time_ns()}@example.com")
    admin = admin_headers()
    job_id = f"speaker-confirm-job-{time.time_ns()}"
    with SessionLocal() as db:
        record = CallRecord(
            telesale_id=employee_id,
            file_path="speaker-confirm.wav",
            transcript="Dạ em chào anh, nội dung có lừa đảo.",
            analysis_data={
                "diarization": {
                    "status": "completed",
                    "speakers": [{"speaker_id": "speaker_0"}, {"speaker_id": "speaker_1"}],
                    "utterances": [
                        {"speaker_id": "speaker_0", "start": 1.25, "end": 2.5, "text": "Dạ em chào anh, nội dung có lừa đảo."},
                        {"speaker_id": "speaker_1", "start": 2.5, "end": 3.0, "text": "Vâng."},
                    ],
                    "role_mapping": {},
                }
            },
        )
        db.add(record)
        db.flush()
        job = AsrJob(job_id=job_id, file_path=record.file_path, status="completed", telesale_id=employee_id, call_record_id=record.id)
        db.add(job)
        db.flush()
        from app.services.notification_service import create_upload_notification

        create_upload_notification(db, user_id=employee_id, job_id=job_id, asr_job_id=job.id, filename="speaker-confirm.wav", event_type="needs_confirmation", title="Cần xác nhận người nói")
        db.commit()
        call_id = record.id

    forbidden = client.put(
        f"/api/mediafile/{call_id}/speaker-roles",
        json={"agentSpeakerId": "speaker_0"},
        headers=employee_headers,
    )
    assert forbidden.status_code == 403

    confirmed = client.put(
        f"/api/mediafile/{call_id}/speaker-roles",
        json={"agentSpeakerId": "speaker_0"},
        headers=admin,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["complianceScore"] == 70.0
    violations = confirmed.json()["keywordsSearchResult"]["regions"]
    deductions = {item["categoryName"]: item["deduction"] for item in violations}
    assert deductions == {"missing_closing": 10.0, "sensitive_keyword": 20.0}
    assert all(item["displayName"] and item["snippet"] for item in violations)
    assert next(item for item in violations if item["categoryName"] == "missing_closing")["hasTimestamp"] is False

    notifications = [
        item for item in client.get("/api/notifications/", headers=employee_headers).json()
        if item["job_id"] == job_id
    ]
    assert len(notifications) == 1
    assert notifications[0]["event_type"] == "completed"
    assert "70/100" in notifications[0]["message"]

    with SessionLocal() as db:
        record = db.query(CallRecord).filter(CallRecord.id == call_id).one()
        record.compliance_score = 75.5
        db.commit()
        from app.services.notification_service import notify_call_scored

        notify_call_scored(db, record)
    decimal_notifications = [
        item for item in client.get("/api/notifications/", headers=employee_headers).json()
        if item["job_id"] == job_id
    ]
    assert len(decimal_notifications) == 1
    assert "75.5/100" in decimal_notifications[0]["message"]

    with SessionLocal() as db:
        record = db.query(CallRecord).filter(CallRecord.id == call_id).one()
        record.compliance_score = 0
        db.commit()
        notify_call_scored(db, record)
    zero_notifications = [
        item for item in client.get("/api/notifications/", headers=employee_headers).json()
        if item["job_id"] == job_id
    ]
    assert len(zero_notifications) == 1
    assert "0/100" in zero_notifications[0]["message"]


def test_employee_legacy_call_api_cannot_assign_agent_speaker():
    _, employee_headers = create_telesale(f"legacy-speaker-{time.time_ns()}@example.com")
    response = client.post(
        "/api/calls/",
        json={
            "file_path": "not-needed.wav",
            "ai_result": {
                "transcript": "Hello",
                "segments": [{"speaker": "agent", "text": "Hello"}],
            },
        },
        headers=employee_headers,
    )
    assert response.status_code == 403


def test_admin_deletion_requires_reason_and_notifies_assigned_employee():
    telesale_id, telesale_headers = create_telesale(f"delete-notice-{time.time_ns()}@example.com")
    admin = admin_headers()
    with SessionLocal() as db:
        record = CallRecord(
            telesale_id=telesale_id,
            file_path="delete-notice-audio.wav",
            client_number="0900000000",
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        call_id = record.id

    missing_reason = client.delete(f"/api/calls/{call_id}", headers=admin)
    assert missing_reason.status_code == 422
    assert client.get(f"/api/mediafile/{call_id}", headers=telesale_headers).status_code == 200

    deleted = client.request(
        "DELETE",
        f"/api/calls/{call_id}",
        json={"reason": "Bản ghi bị gán nhầm nhân viên."},
        headers=admin,
    )
    assert deleted.status_code == 200

    notifications = client.get("/api/notifications/", headers=telesale_headers)
    assert notifications.status_code == 200
    deletion_notice = next(
        item for item in notifications.json() if item["event_type"] == "deleted"
    )
    assert deletion_notice["call_record_id"] is None
    assert "Bản ghi bị gán nhầm nhân viên." in deletion_notice["message"]


if __name__ == "__main__":
    test_health_check()
    print("[PASS] Health Check Test")

    test_user_crud()
    print("[PASS] User CRUD Test")

    test_audio_file_upload_and_analysis_flow()
    print("[PASS] File Upload and AI Call Analysis Test")

    print("\n>>> ALL TESTS PASSED SUCCESSFULLY! <<<")
