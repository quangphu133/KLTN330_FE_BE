from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Any, Literal
from datetime import datetime


class AdditionalMetadata(BaseModel):
    outerId: Optional[str] = None
    clientId: Optional[str] = None
    clientNumber: Optional[str] = None
    direction: Optional[str] = None


class SummaryAnalyserResult(BaseModel):
    simultaneousSpeechCount: Optional[int] = None
    simultaneousSilenceCount: int = 0
    maxSimultaneousSpeechDuration: Optional[float] = None
    maxSimultaneousSilenceDuration: float = 0
    averageSimultaneousSpeechDuration: Optional[float] = None
    averageSimultaneousSilenceDuration: float = 0
    keywordsSearchCounter: dict = {}
    totalSpeechOverall: float = 0
    totalNonSpeechOverall: float = 0
    negativeLevelOverall: Optional[float] = None
    totalSpeechDurationOperator: Optional[float] = None
    totalNonSpeechDurationOperator: Optional[float] = None
    negativeSpeechWeightedDurationOperator: Optional[float] = None
    negativeLevelOperator: Optional[float] = None
    totalSpeechDurationClient: Optional[float] = None
    totalNonSpeechDurationClient: Optional[float] = None
    negativeSpeechWeightedDurationClient: Optional[float] = None
    negativeLevelClient: Optional[float] = None


class MediaFile(BaseModel):
    """
    Shape tương thích với frontend MediaFile interface.
    Được map từ CallRecord.
    """
    projectName: Optional[str] = None
    gptChecklist: Optional[Any] = None
    gptSummary: Optional[str] = None
    id: int
    fileName: Optional[str] = None
    totalCount: int = 0
    numChannels: int = 1
    sampleRate: int = 8000
    duration: int = 0
    operatorChannel: Optional[str] = "1"
    lastAccessUtc: str
    createDate: str
    isFailed: bool = False
    additionalMetadata: AdditionalMetadata
    summaryAnalyserResult: SummaryAnalyserResult
    filteredKeywordsCount: int = 0
    telesaleId: Optional[int] = None
    telesaleName: Optional[str] = None
    complianceScore: Optional[float] = None
    transcriptionStatus: Optional[str] = None
    transcriptionError: Optional[str] = None
    diarizationStatus: Optional[str] = None
    speakerRoleStatus: Optional[str] = None
    speakerCount: int = 0

    model_config = ConfigDict(from_attributes=True)


class MediaFileResponse(BaseModel):
    totalCount: int
    mediaFile: List[MediaFile]


class MediaFileResultResponse(BaseModel):
    """Kết quả phân tích đầy đủ, tương thích frontend MediaFileResultResponse."""
    gptSummary: Optional[str] = None
    gptChecklist: Optional[Any] = None
    stt: Optional[Any] = None
    tonal: Optional[Any] = None
    simultaneousSpeech: Optional[Any] = None
    simultaneousSilence: Optional[Any] = None
    keywordsSearchResult: Optional[Any] = None
    diarization: Optional[Any] = None
    roleMapping: Optional[Any] = None


class SpeakerRoleUpdate(BaseModel):
    agentSpeakerId: str = Field(..., min_length=1)


class WordRoleAssignment(BaseModel):
    startWordId: int
    endWordId: int
    role: Literal["agent", "customer"]


class WordRoleUpdate(BaseModel):
    assignments: List[WordRoleAssignment] = Field(..., min_length=1)
