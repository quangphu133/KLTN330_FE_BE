from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.analytics_schema import AnalyticsDashboardResponse
from app.services.analytics_service import AnalyticsService
from app.api.v1.endpoints.auth import get_current_user, require_admin
from app.models.user import User
from app.models.call_record import CallRecord
from pathlib import Path

router = APIRouter()


class DashboardFilterRequest(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None
    telesaleId: Optional[int] = None
    topNKeywords: Optional[int] = 5
    negativeLevelThreshold: Optional[float] = 0.3
    offset: Optional[int] = 0
    limit: Optional[int] = 10

    model_config = ConfigDict(extra="forbid")


@router.post("/dashboard", response_model=AnalyticsDashboardResponse)
def get_dashboard_analytics_post(
    filters: Optional[DashboardFilterRequest] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    del current_user
    if not filters:
        filters = DashboardFilterRequest()
    return AnalyticsService.get_dashboard(
        db,
        start=filters.start,
        end=filters.end,
        telesale_id=filters.telesaleId,
        top_n_keywords=filters.topNKeywords or 5,
        negative_level_threshold=filters.negativeLevelThreshold or 0.3,
        offset=filters.offset or 0,
        limit=filters.limit or 10,
    )


@router.get("/dashboard", response_model=AnalyticsDashboardResponse)
def get_dashboard_analytics_get(
    request: Request,
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    telesaleId: Optional[int] = Query(None),
    topNKeywords: int = Query(5),
    negativeLevelThreshold: float = Query(0.3),
    offset: int = Query(0),
    limit: int = Query(10),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    del current_user
    if "operatorId" in request.query_params:
        raise HTTPException(status_code=422, detail="operatorId đã ngừng hỗ trợ; hãy dùng telesaleId")
    return AnalyticsService.get_dashboard(
        db,
        start=start,
        end=end,
        telesale_id=telesaleId,
        top_n_keywords=topNKeywords,
        negative_level_threshold=negativeLevelThreshold,
        offset=offset,
        limit=limit,
    )


@router.get("/me")
def get_my_analytics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    records = (
        db.query(CallRecord)
        .filter(CallRecord.telesale_id == current_user.id)
        .order_by(CallRecord.created_at.desc())
        .all()
    )
    scored = [record.compliance_score for record in records if record.compliance_score is not None]
    pending = 0
    for record in records:
        analysis_data = record.analysis_data or {}
        speaker_attribution = analysis_data.get("speaker_attribution") or {}
        diarization = analysis_data.get("diarization") or {}
        if speaker_attribution.get("status") == "pending":
            pending += 1
            continue
        speakers = diarization.get("speakers") or []
        speaker_ids = [str(speaker.get("speaker_id")) for speaker in speakers]
        if (
            diarization.get("status") == "completed"
            and len(speaker_ids) == 2
            and len(set(speaker_ids)) == 2
            and not (diarization.get("role_mapping") or {}).get("agent_speaker_id")
        ):
            pending += 1
    return {
        "totalCalls": len(records),
        "pendingSpeakerConfirmation": pending,
        "averageScore": sum(scored) / len(scored) if scored else None,
        "recentCalls": [
            {
                "id": record.id,
                "fileName": Path(record.file_path).name,
                "complianceScore": record.compliance_score,
                "callDate": record.call_date.isoformat() if record.call_date else None,
                "duration": record.audio_duration or 0,
            }
            for record in records[:5]
        ],
    }
