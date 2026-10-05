from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

class ViolationBase(BaseModel):
    violation_type: str
    keyword_detected: Optional[str] = None
    snippet: Optional[str] = None
    timestamp: Optional[float] = 0.0
    severity: str = "medium"
    deduction: Optional[float] = None

class ViolationCreate(ViolationBase):
    call_record_id: int

class ViolationResponse(ViolationBase):
    id: int
    call_record_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
