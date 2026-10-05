# Ghi chú nhóm: Cập nhật mô tả API và thông báo phản hồi bằng tiếng Việt.
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.schemas.call_schema import CallRecordCreate, CallRecordResponse
from app.services.call_service import CallService
from app.api.v1.endpoints.auth import get_current_user, require_admin
from app.models.user import User
from app.models.call_record import CallRecord
from app.services.notification_service import create_once

router = APIRouter(prefix="/calls", tags=["Call Records"])


class DeleteCallRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=400)

@router.post(
    "/", 
    response_model=CallRecordResponse, 
    status_code=status.HTTP_201_CREATED,
    summary="Tạo bản ghi cuộc gọi & tự động phân tích vi phạm"
)
def create_call_record(call_in: CallRecordCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Tiếp nhận thông tin cuộc gọi (kèm dữ liệu bóc băng hoặc JSON chi tiết từ mô hình AI).
    Hệ thống tự động chạy Regex Engine đối soát luật, tính điểm tuân thủ và lưu vết vi phạm.
    """
    if current_user.role != "admin":
        ai_result = call_in.ai_result
        diarization = ai_result.diarization if ai_result else None
        untrusted_channel_data = bool(ai_result and (
            ai_result.model == "large-v3"
            or ai_result.audio_metadata is not None
            or ai_result.channel_quality is not None
            or ai_result.speaker_attribution is not None
            or diarization is not None
            or any(segment.channel is not None or segment.words for segment in ai_result.segments or [])
        ))
        employee_role_claim = bool(ai_result and any(
            (segment.speaker or "").strip().lower() in {"agent", "customer"}
            for segment in ai_result.segments or []
        ))
        if untrusted_channel_data or employee_role_claim:
            raise HTTPException(status_code=403, detail="Chỉ quản trị viên được xác nhận người nói")
        call_in.telesale_id = current_user.id
    return CallService.create_call(
        db=db,
        call_in=call_in,
        allow_scoring=current_user.role == "admin",
    )

@router.get("/", response_model=List[CallRecordResponse], summary="Lấy danh sách các cuộc gọi")
def get_call_records(
    telesale_id: Optional[int] = Query(None, description="Lọc theo mã nhân viên"),
    min_score: Optional[float] = Query(None, description="Lọc cuộc gọi có điểm tuân thủ >= min_score"),
    max_score: Optional[float] = Query(None, description="Lọc cuộc gọi có điểm tuân thủ <= max_score"),
    skip: int = Query(0, ge=0, description="Vị trí bắt đầu"),
    limit: int = Query(50, ge=1, le=100, description="Số lượng bản ghi tối đa"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Lấy danh sách cuộc gọi kèm bộ lọc theo nhân viên, mức điểm và phân trang.
    """
    if current_user.role != "admin":
        telesale_id = current_user.id
    return CallService.get_all(
        db=db,
        telesale_id=telesale_id,
        min_score=min_score,
        max_score=max_score,
        skip=skip,
        limit=limit
    )

@router.get("/{call_id}", response_model=CallRecordResponse, summary="Xem chi tiết cuộc gọi")
def get_call_record_by_id(call_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Lấy thông tin chi tiết của cuộc gọi cùng danh sách tất cả các vi phạm phát hiện được.
    """
    record = CallService.get_by_id(db=db, call_id=call_id)
    if current_user.role != "admin" and record.telesale_id != current_user.id:
        raise HTTPException(status_code=404, detail="Không tìm thấy cuộc gọi")
    return record

@router.delete("/{call_id}", status_code=status.HTTP_200_OK, summary="Xóa bản ghi cuộc gọi")
def delete_call_record(
    call_id: int,
    payload: DeleteCallRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    del current_user
    """
    Xóa bản ghi cuộc gọi và các vi phạm liên quan khỏi hệ thống.
    """
    reason = payload.reason.strip()
    if len(reason) < 5:
        raise HTTPException(status_code=422, detail="Lý do xóa phải có ít nhất 5 ký tự")

    record = db.query(CallRecord).filter(CallRecord.id == call_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy cuộc gọi")

    if record.telesale_id is not None:
        create_once(
            db,
            user_id=record.telesale_id,
            event_key=f"call-deleted:{record.id}",
            event_type="deleted",
            title="Cuộc gọi đã bị xóa",
            message=f"Cuộc gọi #{record.id} đã bị xóa. Lý do: {reason}",
        )

    CallService.delete(db=db, call_id=call_id)
    return {"status": "success", "message": f"Đã xóa thành công cuộc gọi ID {call_id}"}
