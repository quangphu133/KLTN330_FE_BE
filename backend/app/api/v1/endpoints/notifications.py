from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.v1.endpoints.auth import get_current_user
from app.db.database import get_db
from app.models.asr_job import AsrJob
from app.models.call_record import CallRecord
from app.models.notification import CallNotification
from app.models.user import User

router = APIRouter(prefix="/notifications", tags=["Notifications"])


class NotificationResponse(BaseModel):
    id: int
    event_type: str
    title: str
    message: str
    call_record_id: int | None
    asr_job_id: int | None
    job_id: str | None = None
    job_status: str | None = None
    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.get("/", response_model=list[NotificationResponse])
def list_notifications(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = (
        db.query(CallNotification, AsrJob.job_id, AsrJob.status, CallRecord.compliance_score, CallRecord.file_path)
        .outerjoin(AsrJob, CallNotification.asr_job_id == AsrJob.id)
        .outerjoin(CallRecord, CallNotification.call_record_id == CallRecord.id)
        .filter(CallNotification.user_id == current_user.id)
    )
    if current_user.role != "admin":
        query = query.filter(
            CallNotification.event_type.notin_(("processing", "queued", "running")),
            or_(CallNotification.event_type != "needs_confirmation", CallRecord.compliance_score.is_not(None)),
            or_(CallNotification.event_type != "completed", CallRecord.compliance_score.is_not(None)),
        )
    rows = query.order_by(CallNotification.created_at.desc()).offset(offset).limit(limit).all()

    responses = []
    repaired = False
    for notification, job_id, job_status, score, file_path in rows:
        updates = {"job_id": job_id, "job_status": job_status}
        if current_user.role != "admin" and notification.event_type == "needs_confirmation" and score is not None:
            filename = Path(file_path).name if file_path else f"Cuộc gọi #{notification.call_record_id}"
            notification.event_type = "completed"
            notification.title = f"Đã có điểm đánh giá: {filename}"[:160]
            notification.message = f"Bản ghi {filename} đã có điểm đánh giá: {score:g}/100."
            notification.is_read = False
            repaired = True
        responses.append(NotificationResponse.model_validate(notification).model_copy(update=updates))
    if repaired:
        db.commit()
    return responses


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
def mark_notification_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(CallNotification, AsrJob.job_id, AsrJob.status)
        .outerjoin(AsrJob, CallNotification.asr_job_id == AsrJob.id)
        .filter(CallNotification.id == notification_id, CallNotification.user_id == current_user.id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy thông báo")
    notification, job_id, job_status = row
    notification.is_read = True
    db.commit()
    db.refresh(notification)
    return NotificationResponse.model_validate(notification).model_copy(
        update={"job_id": job_id, "job_status": job_status}
    )
