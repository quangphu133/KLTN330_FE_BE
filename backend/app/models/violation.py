from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Float
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.db.database import Base

class Violation(Base):
    __tablename__ = "violations"

    id = Column(Integer, primary_key=True, index=True)
    call_record_id = Column(Integer, ForeignKey("call_records.id", ondelete="CASCADE"), nullable=False)
    violation_type = Column(String(50), nullable=False)      # "missing_greeting", "forbidden_keyword", "abusive_language", v.v.
    keyword_detected = Column(String(100), nullable=True)    # Từ khóa vi phạm phát hiện được
    snippet = Column(Text, nullable=True)                   # Trích đoạn hội thoại chứa lỗi
    timestamp = Column(Float, nullable=True)                 # Thời điểm lỗi trong file audio (giây)
    severity = Column(String(20), default="medium")         # "low", "medium", "high"
    deduction = Column(Float, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    # Relationships
    call_record = relationship("CallRecord", back_populates="violations")
