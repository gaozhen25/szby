from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.generation import WorkflowSchema
from app.schemas.uploads import UploadedObjectRef


class DigitalHumanTrainingScriptSchema(BaseModel):
    version: str
    text: str
    minDurationSeconds: int
    maxDurationSeconds: int
    recommendedDurationSeconds: int
    instructions: list[str]


class DigitalHumanProfileSchema(BaseModel):
    id: str
    accountId: str
    name: str
    status: str
    sourceVideoUrl: str
    coverUrl: str = ""
    width: int = 0
    height: int = 0
    durationSeconds: int = 0
    trainingScriptVersion: str
    validationReport: dict[str, Any] = Field(default_factory=dict)
    voiceStatus: str
    voicePreviewUrl: str = ""
    enrollmentWorkflowId: str | None = None
    errorCode: str = ""
    errorMessage: str = ""
    createdAt: datetime
    updatedAt: datetime


class CreateDigitalHumanProfileResponse(BaseModel):
    profile: DigitalHumanProfileSchema
    workflow: WorkflowSchema


class CreateDigitalHumanProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    trainingScriptVersion: str = "zh_cn_v1"
    consentConfirmed: bool
    sourceVideo: UploadedObjectRef


class DigitalHumanVideoCreateRequest(BaseModel):
    profileId: str = Field(min_length=1)
    creationId: str = ""
    title: str = Field(min_length=1, max_length=255)
    scriptText: str = Field(min_length=1, max_length=10000)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    subtitlesEnabled: bool = True
    backgroundUrl: str = Field(default="", max_length=2000)
    bubbleUrl: str = Field(default="", max_length=2000)
    backgroundMusicUrl: str = Field(default="", max_length=2000)
    backgroundMusicGain: float = Field(default=0.1, ge=0, le=10)
    idempotencyKey: str = Field(default="", max_length=128)


class DigitalHumanVideoListResponse(BaseModel):
    items: list[WorkflowSchema]
    total: int
    page: int
    pageSize: int
