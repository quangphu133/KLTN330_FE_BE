# Ghi chú nhóm: Chuẩn hóa thông báo nghiệp vụ và thuật ngữ tiếng Việt.
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, UploadFile, status
from app.models.call_record import CallRecord
from app.models.project import Project
from app.models.asr_job import AsrJob
from app.services.file_service import FileService
from app.services.rule_service import analyze_transcript


class MediaFileService:
    """Map CallRecord ↔ MediaFile shape cho frontend."""

    @staticmethod
    def _to_media_file(record: CallRecord, total_count: int = 0, transcription_status: Optional[str] = None) -> dict:
        created_iso = (record.call_date or record.created_at).isoformat() if (record.call_date or record.created_at) else ""
        telesale_name = (record.telesale.full_name or record.telesale.email) if record.telesale else None
        proj_name = record.project.name if record.project else None
        neg_level = (
            round((100 - record.compliance_score) / 100, 4)
            if record.compliance_score is not None
            else None
        )
        analysis_data = record.analysis_data or {}
        diarization = analysis_data.get("diarization") or {}
        audio_metadata = analysis_data.get("audio_metadata") or {}
        role_mapping = analysis_data.get("speaker_attribution") or diarization.get("role_mapping") or {}
        effective_transcription_status = transcription_status
        if role_mapping.get("status") == "pending" and record.transcript:
            effective_transcription_status = "needs_confirmation"

        return {
            "id": record.id,
            "fileName": Path(record.file_path).name if record.file_path else None,
            "projectName": proj_name,
            "gptChecklist": None,
            "gptSummary": None,
            "totalCount": total_count,
            "numChannels": audio_metadata.get("num_channels", 1),
            "sampleRate": audio_metadata.get("sample_rate", 8000),
            "duration": record.audio_duration or 0,
            "telesaleId": record.telesale_id,
            "telesaleName": telesale_name,
            "operatorChannel": role_mapping.get("agent_speaker_id"),
            "lastAccessUtc": created_iso,
            "createDate": created_iso,
            "isFailed": transcription_status == "failed",
            "additionalMetadata": {
                "outerId": None,
                "clientId": None,
                "clientNumber": record.client_number,
                "direction": None,
            },
            "summaryAnalyserResult": {
                "simultaneousSpeechCount": None,
                "simultaneousSilenceCount": 0,
                "maxSimultaneousSpeechDuration": None,
                "maxSimultaneousSilenceDuration": 0,
                "averageSimultaneousSpeechDuration": None,
                "averageSimultaneousSilenceDuration": 0,
                "keywordsSearchCounter": {},
                "totalSpeechOverall": record.audio_duration or 0,
                "totalNonSpeechOverall": 0,
                "negativeLevelOverall": neg_level,
                "totalSpeechDurationOperator": None,
                "totalNonSpeechDurationOperator": None,
                "negativeSpeechWeightedDurationOperator": None,
                "negativeLevelOperator": neg_level,
                "totalSpeechDurationClient": None,
                "totalNonSpeechDurationClient": None,
                "negativeSpeechWeightedDurationClient": None,
                "negativeLevelClient": None,
            },
            "filteredKeywordsCount": len(record.violations),
            "complianceScore": record.compliance_score,
            "transcriptionStatus": effective_transcription_status,
            "transcriptionError": None,
            "diarizationStatus": diarization.get("status"),
            "speakerRoleStatus": role_mapping.get("status"),
            "speakerCount": len(diarization.get("speakers") or []) or (2 if audio_metadata.get("num_channels") == 2 else 0),
        }

    @staticmethod
    def get_list(
        db: Session,
        start: Optional[str] = None,
        end: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
        search_phrase: Optional[str] = None,
        telesale_id: Optional[int] = None,
    ) -> dict:
        query = db.query(CallRecord)
        if telesale_id is not None:
            query = query.filter(CallRecord.telesale_id == telesale_id)
        if start:
            start_date = datetime.fromisoformat(start.replace("Z", "+00:00"))
            if start_date.tzinfo is not None:
                start_date = start_date.astimezone(timezone.utc).replace(tzinfo=None)
            query = query.filter(CallRecord.call_date >= start_date)
        if end:
            end_date = datetime.fromisoformat(end.replace("Z", "+00:00"))
            if end_date.tzinfo is not None:
                end_date = end_date.astimezone(timezone.utc).replace(tzinfo=None)
            query = query.filter(CallRecord.call_date <= end_date)
        if search_phrase:
            query = query.filter(CallRecord.transcript.ilike(f"%{search_phrase}%"))
        total = query.count()
        records = query.order_by(CallRecord.created_at.desc()).offset(offset).limit(limit).all()
        jobs = {}
        if records:
            jobs = {
                job.call_record_id: {"status": job.status, "error": job.error_message}
                for job in db.query(AsrJob)
                .filter(AsrJob.call_record_id.in_([record.id for record in records]))
                .all()
            }
        return {
            "totalCount": total,
            "mediaFile": [
                MediaFileService._with_transcription_error(
                    MediaFileService._to_media_file(r, total, (jobs.get(r.id) or {}).get("status")),
                    (jobs.get(r.id) or {}).get("error"),
                )
                for r in records
            ],
        }

    @staticmethod
    def _with_transcription_error(media_file: dict, error: Optional[str]) -> dict:
        media_file["transcriptionError"] = error
        return media_file

    @staticmethod
    def get_by_id(db: Session, record_id: int) -> dict:
        record = db.query(CallRecord).filter(CallRecord.id == record_id).first()
        if not record:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy bản ghi có mã: {record_id}")
        return MediaFileService._to_media_file(record)

    @staticmethod
    def get_result(db: Session, record_id: int) -> dict:
        record = db.query(CallRecord).filter(CallRecord.id == record_id).first()
        if not record:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy bản ghi có mã: {record_id}")

        analysis_data = record.analysis_data or {}
        diarization = analysis_data.get("diarization") or {}
        role_mapping = diarization.get("role_mapping") or {}

        speaker_attribution = analysis_data.get("speaker_attribution") or {}
        role_mapping = speaker_attribution or diarization.get("role_mapping") or {}
        diarization_utterances = diarization.get("utterances") or []
        source_utterances = diarization_utterances or [
            {
                "id": item.get("id", index),
                "speaker_id": item.get("speaker_id"),
                "speaker": item.get("speaker", "unknown"),
                "start": item.get("start", item.get("start_time", 0.0)),
                "end": item.get("end", item.get("end_time", 0.0)),
                "channel": item.get("channel", 0),
                "text": item.get("text", ""),
                "words": item.get("words", []),
            }
            for index, item in enumerate(analysis_data.get("segments") or [])
        ]
        word_role_by_id = {}
        role_assignments = role_mapping.get("assignments") or []
        if isinstance(role_assignments, list):
            indexed_words = [word for utterance in source_utterances for word in utterance.get("words") or []]
            word_positions = {word.get("id"): index for index, word in enumerate(indexed_words)}
            for assignment in role_assignments:
                if not isinstance(assignment, dict):
                    continue
                start_index = word_positions.get(assignment.get("start_word_id"))
                end_index = word_positions.get(assignment.get("end_word_id"))
                if start_index is not None and end_index is not None and end_index >= start_index:
                    for word in indexed_words[start_index:end_index + 1]:
                        word_role_by_id[word.get("id")] = assignment.get("role")
        if word_role_by_id or isinstance(role_assignments, dict):
            derived_utterances = []
            for utterance in source_utterances:
                words = utterance.get("words") or []
                if not words:
                    derived_utterances.append(utterance)
                    continue
                groups = []
                for word in words:
                    role = word_role_by_id.get(word.get("id"))
                    if role is None and isinstance(role_assignments, dict):
                        role = role_assignments.get(f"CHANNEL_{utterance.get('channel', 0)}")
                    if role is None and utterance.get("speaker") in {"agent", "customer"}:
                        role = utterance.get("speaker")
                    if not groups or groups[-1][0] != role:
                        groups.append((role, []))
                    groups[-1][1].append(word)
                for role, grouped_words in groups:
                    text = " ".join(str(word.get("word") or "").strip() for word in grouped_words).strip()
                    if not text:
                        continue
                    derived_utterances.append({
                        "id": grouped_words[0].get("id", utterance.get("id")),
                        "channel": utterance.get("channel", 0),
                        "speaker_id": utterance.get("speaker_id"),
                        "speaker": role or "unknown",
                        "start": grouped_words[0].get("start", utterance.get("start")),
                        "end": grouped_words[-1].get("end", utterance.get("end")),
                        "text": text,
                        "words": grouped_words,
                    })
            source_utterances = derived_utterances
        chunks = []
        text_cursor = 0
        for chunk_id, utterance in enumerate(source_utterances):
            utterance_text = str(utterance.get("text", "")).strip()
            if not utterance_text:
                continue
            start_char = text_cursor
            end_char = start_char + len(utterance_text)
            regions = []
            word_cursor = start_char
            for word in utterance.get("words") or []:
                word_text = str(word.get("word", "")).strip()
                if not word_text:
                    continue
                word_start = word.get("start")
                word_end = word.get("end")
                word_start_char = word_cursor
                word_end_char = word_start_char + len(word_text)
                role = word_role_by_id.get(word.get("id"))
                if role is None and isinstance(role_assignments, dict):
                    role = role_assignments.get(f"CHANNEL_{utterance.get('channel', 0)}")
                if role is None and utterance.get("speaker") in {"agent", "customer"}:
                    role = utterance.get("speaker")
                regions.append({
                    "wordId": word.get("id"),
                    "channel": utterance.get("channel", 0),
                    "startChar": word_start_char,
                    "endChar": word_end_char,
                    "startTime": word_start,
                    "endTime": word_end,
                    "role": role,
                })
                word_cursor = word_end_char + 1
            speaker = utterance.get("speaker", "unknown")
            if isinstance(role_assignments, dict):
                speaker = role_assignments.get(f"CHANNEL_{utterance.get('channel', 0)}", speaker)
            chunks.append({
                "id": utterance.get("id", chunk_id),
                "channel": utterance.get("channel", 0),
                "startChar": start_char,
                "endChar": end_char,
                "startTime": utterance.get("start"),
                "endTime": utterance.get("end"),
                "text": utterance_text,
                "regions": regions,
                "speakerId": utterance.get("speaker_id"),
                "speaker": speaker,
            })
            text_cursor = end_char + 1

        # Map violations → keywordsSearchResult regions
        kw_regions = []
        violation_names = {
            "missing_greeting": "Thiếu lời chào bắt buộc",
            "missing_closing": "Thiếu lời cảm ơn hoặc chào kết thúc",
            "sensitive_keyword": "Từ khóa nhạy cảm",
            "forced_selling": "Ép buộc khách hàng",
            "abusive_language": "Ngôn từ thiếu chuẩn mực",
            "negative_attitude": "Thái độ thiếu tích cực",
        }
        for v in record.violations:
            kw_regions.append({
                "category": 0,
                "categoryName": v.violation_type,
                "displayName": violation_names.get(v.violation_type, "Lỗi vi phạm"),
                "phrase": v.keyword_detected,
                "snippet": v.snippet,
                "severity": v.severity,
                "deduction": v.deduction,
                "hasTimestamp": not v.violation_type.startswith("missing_"),
                "startChar": 0,
                "endChar": 0,
                "startTime": v.timestamp or 0.0,
                "endTime": (v.timestamp or 0.0) + 2.0,
                "channel": 0,
            })

        return {
            "id": record.id,
            "telesaleId": record.telesale_id,
            "complianceScore": record.compliance_score,
            "callDate": record.call_date.isoformat() if record.call_date else None,
            "duration": record.audio_duration or 0,
            "clientNumber": record.client_number,
            "fileName": Path(record.file_path).name if record.file_path else None,
            "gptSummary": None,
            "gptChecklist": None,
            "stt": {
                "text": record.transcript,
                "chunks": chunks,
                "regions": [region for chunk in chunks for region in chunk["regions"]],
            },
            "tonal": {"regions": []},
            "simultaneousSpeech": {"regions": []},
            "simultaneousSilence": {"regions": []},
            "keywordsSearchResult": {"regions": kw_regions},
            "diarization": diarization,
            "audioMetadata": analysis_data.get("audio_metadata"),
            "roleMapping": role_mapping,
        }

    @staticmethod
    async def create_from_upload(
        db: Session,
        file: UploadFile,
        project_id: Optional[int] = None,
        client_number: Optional[str] = None,
        call_date: Optional[datetime] = None,
        telesale_id: Optional[int] = None,
    ) -> dict:
        # Lưu file
        saved = await FileService.save_audio_file(file)
        file_path = saved.file_path

        # Tạo CallRecord
        record = CallRecord(
            file_path=file_path,
            telesale_id=telesale_id,
            project_id=project_id,
            client_number=client_number,
            call_date=call_date or datetime.now(timezone.utc).replace(tzinfo=None),
            compliance_score=None,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return MediaFileService._to_media_file(record)
