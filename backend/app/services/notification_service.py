from sqlalchemy.orm import Session
from pathlib import Path

from app.models.asr_job import AsrJob
from app.models.call_record import CallRecord
from app.models.notification import CallNotification


def create_once(
    db: Session,
    *,
    user_id: int | None,
    event_key: str,
    event_type: str,
    title: str,
    message: str,
    call_record_id: int | None = None,
    asr_job_id: int | None = None,
) -> None:
    if user_id is None or db.query(CallNotification.id).filter(CallNotification.event_key == event_key).first():
        return
    db.add(CallNotification(
        user_id=user_id,
        event_key=event_key,
        event_type=event_type,
        title=title,
        message=message,
        call_record_id=call_record_id,
        asr_job_id=asr_job_id,
    ))
    db.flush()


def create_upload_notification(
    db: Session,
    *,
    user_id: int,
    job_id: str,
    asr_job_id: int,
    filename: str,
    event_type: str = "processing",
    title: str | None = None,
    message: str | None = None,
    call_record_id: int | None = None,
) -> CallNotification:
    event_key = f"asr:{job_id}:upload:{user_id}"
    notification = db.query(CallNotification).filter(CallNotification.event_key == event_key).first()
    if notification is None:
        safe_filename = filename.replace("\r", " ").replace("\n", " ").strip() or "Bản ghi âm"
        notification = CallNotification(
            user_id=user_id,
            event_key=event_key,
            event_type=event_type,
            title=f"{title or 'Đang xử lý'}: {safe_filename}"[:160],
            message=message or "Bản ghi đã tải lên đang được xử lý và sẽ sớm khả dụng.",
            call_record_id=call_record_id,
            asr_job_id=asr_job_id,
        )
        db.add(notification)
    else:
        notification.event_type = event_type
        notification.title = title or notification.title
        notification.message = message or notification.message
        notification.call_record_id = call_record_id
    db.flush()
    return notification


def update_upload_notifications(
    db: Session,
    *,
    asr_job_id: int,
    job_id: str,
    event_type: str,
    title: str,
    message: str,
    call_record_id: int | None,
) -> set[int]:
    notifications = (
        db.query(CallNotification)
        .filter(
            CallNotification.asr_job_id == asr_job_id,
            CallNotification.event_key.like(f"asr:{job_id}:upload:%"),
        )
        .all()
    )
    recipients = {notification.user_id for notification in notifications}
    for notification in notifications:
        changed_status = notification.event_type != event_type
        filename = notification.title.split(": ", maxsplit=1)[-1]
        new_title = f"{title}: {filename}"[:160]
        if changed_status or notification.title != new_title or notification.message != message:
            notification.event_type = event_type
            notification.title = new_title
            notification.message = message
            notification.call_record_id = call_record_id
            if changed_status:
                notification.is_read = False
    db.flush()
    return recipients


def notify_call_scored(db: Session, call_record: CallRecord) -> None:
    """Notify the call owner once its score has been persisted."""
    if call_record.compliance_score is None:
        return

    job = (
        db.query(AsrJob)
        .filter(AsrJob.call_record_id == call_record.id)
        .order_by(AsrJob.created_at.desc())
        .first()
    )
    filename = Path(call_record.file_path).name if call_record.file_path else f"Cuộc gọi #{call_record.id}"
    score = f"{call_record.compliance_score:g}"
    title = "Đã có điểm đánh giá"
    message = f"Bản ghi {filename} đã có điểm đánh giá: {score}/100."
    recipients = set()

    if job is not None:
        recipients = update_upload_notifications(
            db,
            asr_job_id=job.id,
            job_id=job.job_id,
            event_type="completed",
            title=title,
            message=message,
            call_record_id=call_record.id,
        )
        pending_notifications = (
            db.query(CallNotification)
            .filter(
                CallNotification.asr_job_id == job.id,
                CallNotification.event_type.in_(("needs_confirmation", "completed")),
            )
            .all()
        )
        for notification in pending_notifications:
            if notification.event_type != "completed" or notification.message != message:
                notification.event_type = "completed"
                notification.title = title
                notification.message = message
                notification.call_record_id = call_record.id
                notification.is_read = False
            recipients.add(notification.user_id)

    if call_record.telesale_id is not None and call_record.telesale_id not in recipients:
        event_key = (
            f"asr:{job.job_id}:scored:{call_record.telesale_id}"
            if job is not None
            else f"call:{call_record.id}:scored:{call_record.telesale_id}"
        )
        create_once(
            db,
            user_id=call_record.telesale_id,
            event_key=event_key,
            event_type="completed",
            title=title,
            message=message,
            call_record_id=call_record.id,
            asr_job_id=job.id if job is not None else None,
        )
    db.commit()
