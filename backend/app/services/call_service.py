# Ghi chú nhóm: Chuẩn hóa thông báo nghiệp vụ và thuật ngữ tiếng Việt.
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple, Dict
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models.call_record import CallRecord
from app.models.violation import Violation
from app.models.user import User
from app.models.project import Project
from app.schemas.call_schema import CallRecordCreate, CallRecordUpdate
from app.schemas.ai_schema import AISpeechSegment
from app.schemas.mediafile_schema import WordRoleAssignment
from app.services.rule_service import analyze_transcript
from app.core.config import settings

class CallService:
    @staticmethod
    def create_call(
        db: Session,
        call_in: CallRecordCreate,
        trusted_asr: bool = False,
        allow_scoring: bool = True,
        commit: bool = True,
    ) -> CallRecord:
        # Validate the selected owner as an active employee account.
        if call_in.telesale_id:
            user = db.query(User).filter(
                User.id == call_in.telesale_id,
                User.role == "telesales",
                User.is_active.is_(True),
            ).first()
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Không tìm thấy nhân viên đang hoạt động với mã: {call_in.telesale_id}"
                )

        if call_in.project_id and not db.query(Project).filter(Project.id == call_in.project_id).first():
            raise HTTPException(status_code=404, detail=f"Không tìm thấy dự án có mã: {call_in.project_id}")

        # 2. Chuẩn hóa dữ liệu transcript và segments từ AI JSON hoặc raw transcript
        final_transcript = call_in.transcript or ""
        segments = []
        duration = call_in.audio_duration or 0
        sentiment = call_in.sentiment
        analysis_data = None

        if call_in.ai_result:
            if call_in.ai_result.transcript:
                final_transcript = call_in.ai_result.transcript
            elif call_in.ai_result.segments:
                # Nếu chỉ có mảng segments, tự động ghép thành transcript hoàn chỉnh
                final_transcript = " ".join([seg.text for seg in call_in.ai_result.segments])
            
            segments = call_in.ai_result.segments or []
            if call_in.ai_result.duration:
                duration = call_in.ai_result.duration
            if call_in.ai_result.sentiment:
                sentiment = call_in.ai_result.sentiment
            analysis_data = call_in.ai_result.model_dump(exclude_none=True)

        # 3. Phân tích nội dung bóc băng bằng Regex Rules
        diarization = (analysis_data or {}).get("diarization")
        role_mapping = (diarization or {}).get("role_mapping", {})
        attribution = (analysis_data or {}).get("speaker_attribution") or {}
        manually_attributed = bool(segments and any(
            (segment.speaker or "").strip().lower() in {"agent", "customer"}
            for segment in segments
        )) or bool(diarization and diarization.get("status") == "completed" and role_mapping.get("agent_speaker_id"))
        diarization_ready = allow_scoring and manually_attributed
        if trusted_asr:
            diarization_ready = attribution.get("status") == "confirmed"
        analysis = analyze_transcript(final_transcript, segments=segments) if diarization_ready else {
            "compliance_score": None,
            "violations": [],
        }

        stored_file_path = Path(call_in.file_path)
        if not stored_file_path.is_absolute():
            stored_file_path = settings.UPLOAD_DIR / stored_file_path
        stored_file_path = stored_file_path.resolve()
        if not stored_file_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Tệp âm thanh không tồn tại: {stored_file_path}",
            )

        # 4. Khởi tạo bản ghi cuộc gọi
        db_call = CallRecord(
            telesale_id=call_in.telesale_id,
            project_id=call_in.project_id,
            client_number=call_in.client_number,
            call_date=call_in.call_date or datetime.now(timezone.utc).replace(tzinfo=None),
            file_path=stored_file_path.as_posix(),
            audio_duration=duration,
            transcript=final_transcript,
            compliance_score=analysis["compliance_score"],
            sentiment=sentiment,
            analysis_data=analysis_data,
        )
        try:
            db.add(db_call)
            db.flush()
            for violation in analysis["violations"]:
                db.add(Violation(call_record_id=db_call.id, **violation))
            if commit:
                db.commit()
                db.refresh(db_call)
        except Exception:
            db.rollback()
            raise
        return db_call

    @staticmethod
    def confirm_speaker_roles(db: Session, call_id: int, agent_speaker_id: str, actor_id: Optional[int] = None) -> CallRecord:
        """Confirm the agent speaker and recalculate regex violations atomically."""
        record = CallService.get_by_id(db, call_id)
        data = dict(record.analysis_data or {})
        attribution = dict(data.get("speaker_attribution") or {})
        if agent_speaker_id in {"CHANNEL_0", "CHANNEL_1"} and attribution:
            audio_metadata = data.get("audio_metadata") or {}
            channel = int(agent_speaker_id[-1])
            segments = data.get("segments") or []
            if audio_metadata.get("num_channels") != 2 or not any(item.get("channel") == channel for item in segments):
                raise HTTPException(status_code=400, detail="Không tìm thấy kênh âm thanh để xác nhận")
            attribution.update({
                "status": "confirmed",
                "source": "manual",
                "actor": "user",
                "actor_id": actor_id,
                "agent_speaker_id": agent_speaker_id,
                "suggested_agent_speaker_id": agent_speaker_id,
                "agent_channel": channel,
                "reason": "admin_manual_override",
                "assignments": {"CHANNEL_0": "customer" if channel == 1 else "agent", "CHANNEL_1": "customer" if channel == 0 else "agent"},
            })
            data["speaker_attribution"] = attribution
            analysis_segments = [
                AISpeechSegment(
                    id=item.get("id"),
                    text=item.get("text", ""),
                    start_time=item.get("start_time", item.get("start")),
                    end_time=item.get("end_time", item.get("end")),
                    speaker="agent" if item.get("channel") == channel else "customer",
                    channel=item.get("channel"),
                    words=item.get("words") or [],
                )
                for item in segments
            ]
            analysis = analyze_transcript(record.transcript or "", segments=analysis_segments)
            return CallService._save_role_analysis(db, record, data, analysis)

        diarization = dict(data.get("diarization") or {})
        speakers = diarization.get("speakers") or []
        speaker_ids = [str(item.get("speaker_id")) for item in speakers]
        if diarization.get("status") != "completed" or len(speaker_ids) != 2 or len(set(speaker_ids)) != 2:
            raise HTTPException(status_code=400, detail="Cuộc gọi chưa có đúng hai người nói để xác nhận")
        if agent_speaker_id not in speaker_ids:
            raise HTTPException(status_code=400, detail="Mã người nói không tồn tại trong cuộc gọi")

        customer_speaker_id = next(speaker for speaker in speaker_ids if speaker != agent_speaker_id)
        for speaker in speakers:
            speaker["role"] = "agent" if speaker["speaker_id"] == agent_speaker_id else "customer"

        role_mapping = dict(diarization.get("role_mapping") or {})
        role_mapping.update({
            "status": "confirmed",
            "source": "manual",
            "actor": "user",
            "actor_id": actor_id,
            "agent_speaker_id": agent_speaker_id,
            "customer_speaker_id": customer_speaker_id,
        })
        diarization["speakers"] = speakers
        diarization["role_mapping"] = role_mapping
        for utterance in diarization.get("utterances") or []:
            speaker_id = utterance.get("speaker_id")
            utterance["speaker"] = (
                "agent" if speaker_id == agent_speaker_id
                else "customer" if speaker_id == customer_speaker_id
                else "unknown"
            )
        for segment in diarization.get("segments") or []:
            speaker_id = segment.get("speaker_id")
            segment["speaker"] = "agent" if speaker_id == agent_speaker_id else "customer" if speaker_id == customer_speaker_id else "unknown"
            for word in segment.get("words") or []:
                word_id = word.get("speaker_id")
                word["speaker"] = "agent" if word_id == agent_speaker_id else "customer" if word_id == customer_speaker_id else "unknown"

        data["diarization"] = diarization
        analysis_segments = [
            AISpeechSegment(
                text=item.get("text", ""),
                start_time=item.get("start"),
                end_time=item.get("end"),
                speaker=item.get("speaker", "unknown"),
                speaker_id=item.get("speaker_id"),
            )
            for item in diarization.get("utterances") or []
        ]
        analysis = analyze_transcript(record.transcript or "", segments=analysis_segments)
        return CallService._save_role_analysis(db, record, data, analysis)

    @staticmethod
    def confirm_word_roles(
        db: Session,
        call_id: int,
        assignments: List[WordRoleAssignment],
        actor_id: Optional[int] = None,
    ) -> CallRecord:
        """Apply admin-confirmed roles to every stored word of a mono recording."""
        record = CallService.get_by_id(db, call_id)
        data = dict(record.analysis_data or {})
        metadata = data.get("audio_metadata") or {}
        segments = data.get("segments") or []
        if metadata.get("num_channels") != 1:
            raise HTTPException(status_code=400, detail="Xác nhận vai trò theo từ chỉ áp dụng cho bản ghi mono")

        words = [word for segment in segments for word in segment.get("words") or []]
        word_indexes: Dict[int, int] = {}
        for index, word in enumerate(words):
            word_id = word.get("id")
            if not isinstance(word_id, int) or word_id in word_indexes:
                raise HTTPException(status_code=400, detail="Danh sách từ không có mã ổn định duy nhất")
            word_indexes[word_id] = index
        if not words:
            raise HTTPException(status_code=400, detail="Không có dữ liệu từ để xác nhận")

        roles: Dict[int, str] = {}
        next_index = 0
        has_agent = False
        for assignment in assignments:
            start_id, end_id = assignment.startWordId, assignment.endWordId
            if start_id not in word_indexes or end_id not in word_indexes:
                raise HTTPException(status_code=400, detail="Mã từ không tồn tại trong bản ghi")
            start_index, end_index = word_indexes[start_id], word_indexes[end_id]
            if start_index != next_index or end_index < start_index:
                raise HTTPException(status_code=400, detail="Khoảng từ phải theo thứ tự, không chồng lấn và bao phủ toàn bộ transcript")
            for word in words[start_index:end_index + 1]:
                roles[word["id"]] = assignment.role
            next_index = end_index + 1
            has_agent = has_agent or assignment.role == "agent"
        if next_index != len(words) or not has_agent:
            raise HTTPException(status_code=400, detail="Gán vai trò cho toàn bộ từ và ít nhất một từ của nhân viên")

        analysis_segments = []
        for segment in segments:
            agent_words = []
            def append_agent_words():
                if not agent_words:
                    return
                analysis_segments.append(AISpeechSegment(
                    text=" ".join(str(word.get("word") or "").strip() for word in agent_words).strip(),
                    start_time=agent_words[0].get("start"),
                    end_time=agent_words[-1].get("end"),
                    speaker="agent",
                    channel=0,
                ))
                agent_words.clear()
            for word in segment.get("words") or []:
                if roles[word["id"]] == "agent":
                    agent_words.append(word)
                else:
                    append_agent_words()
            append_agent_words()

        attribution = {
            "status": "confirmed",
            "source": "manual",
            "actor": "user",
            "actor_id": actor_id,
            "agent_speaker_id": None,
            "suggested_agent_speaker_id": None,
            "agent_channel": None,
            "default_agent_channel": data.get("speaker_attribution", {}).get("default_agent_channel"),
            "reason": "admin_word_role_override",
            "evidence": None,
            "assignments": [
                {
                    "start_word_id": assignment.startWordId,
                    "end_word_id": assignment.endWordId,
                    "role": assignment.role,
                }
                for assignment in assignments
            ],
        }
        data["speaker_attribution"] = attribution
        analysis = analyze_transcript(record.transcript or "", segments=analysis_segments)
        return CallService._save_role_analysis(db, record, data, analysis)

    @staticmethod
    def _save_role_analysis(db: Session, record: CallRecord, data: dict, analysis: dict) -> CallRecord:
        try:
            record.analysis_data = data
            record.compliance_score = analysis["compliance_score"]
            db.query(Violation).filter(Violation.call_record_id == record.id).delete(synchronize_session=False)
            for violation in analysis["violations"]:
                db.add(Violation(call_record_id=record.id, **violation))
            db.commit()
            db.refresh(record)
        except Exception:
            db.rollback()
            raise
        return record

    @staticmethod
    def get_by_id(db: Session, call_id: int) -> CallRecord:
        record = db.query(CallRecord).filter(CallRecord.id == call_id).first()
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy cuộc gọi có mã: {call_id}"
            )
        return record

    @staticmethod
    def get_all(
        db: Session,
        telesale_id: Optional[int] = None,
        min_score: Optional[float] = None,
        max_score: Optional[float] = None,
        skip: int = 0,
        limit: int = 50
    ) -> List[CallRecord]:
        query = db.query(CallRecord)
        if telesale_id:
            query = query.filter(CallRecord.telesale_id == telesale_id)
        if min_score is not None:
            query = query.filter(CallRecord.compliance_score >= min_score)
        if max_score is not None:
            query = query.filter(CallRecord.compliance_score <= max_score)
        
        return query.order_by(CallRecord.created_at.desc()).offset(skip).limit(limit).all()

    @staticmethod
    def delete(db: Session, call_id: int) -> bool:
        record = CallService.get_by_id(db, call_id)
        db.delete(record)
        db.commit()
        return True

    @staticmethod
    def get_violations(
        db: Session,
        call_record_id: Optional[int] = None,
        severity: Optional[str] = None,
        violation_type: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> List[Violation]:
        query = db.query(Violation)
        if call_record_id:
            query = query.filter(Violation.call_record_id == call_record_id)
        if severity:
            query = query.filter(Violation.severity == severity)
        if violation_type:
            query = query.filter(Violation.violation_type == violation_type)
        
        return query.order_by(Violation.created_at.desc()).offset(skip).limit(limit).all()
