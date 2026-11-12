from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.materials import MaterialSchema
from app.schemas.tasks import TaskSchema


class GenerateCreationRequest(BaseModel):
    topicId: str
    targetPlatform: str


class CreationContentSchema(BaseModel):
    scriptOriginal: list[str]
    scriptRewritten: list[str]
    title: str
    body: str
    hashtags: list[str]
    cover: dict[str, str]
    bgmSuggestion: str
    sensitiveCheck: dict[str, object]
    imagePrompt: str = ""
    assets: list[dict[str, object]] = Field(default_factory=list)


class CreationResponse(BaseModel):
    creationId: str
    topicId: str
    topicTitle: str
    type: str
    targetPlatform: str
    content: CreationContentSchema
    creationState: dict[str, object] = Field(default_factory=dict)


class SubmitCreationTaskRequest(BaseModel):
    topicId: str = ""
    targetPlatform: str
    type: str
    content: CreationContentSchema
    creationState: dict[str, object] = Field(default_factory=dict)
    assignee: str = ""
    dueDate: str = ""
    priority: str = "normal"
    status: str = "draft"
    handoffNote: str = ""
    persistExtractAssets: bool = False
    extractHistoryId: str | None = None
    linkReference: dict[str, Any] | None = None
    saveScriptMaterial: bool = False


class AssetPersistenceSummarySchema(BaseModel):
    jobId: str
    historyId: str
    status: str
    error: str = ""


class SubmitCreationTaskResponse(TaskSchema):
    material: MaterialSchema | None = None
    assetPersistence: AssetPersistenceSummarySchema | None = None


class PublishCreationRequest(BaseModel):
    targetPlatform: str = ""
    assetList: list[str] = Field(default_factory=list)
    videoUrl: str = ""
    filename: str = ""
    title: str = Field(default="", max_length=255)
    description: str
    visibility: Literal["0", "1", "2"] = "0"
    copyToAlbum: bool = True
    sha256: str = ""
    sizeBytes: int | None = None
    retry: bool = False

    @field_validator("description")
    @classmethod
    def require_description(cls, value: str) -> str:
        description = value.strip()
        if not description:
            raise ValueError("description is required")
        return description

    def normalized_asset_list(self) -> list[str]:
        assets = [str(item).strip() for item in self.assetList if str(item).strip()]
        if assets:
            return assets
        fallback = self.videoUrl.strip()
        return [fallback] if fallback else []


class PublishVideoUploadResponse(BaseModel):
    url: str
    filename: str
    contentType: str
    sizeBytes: int
    taskId: str


class PublishImageUploadResponse(BaseModel):
    url: str
    filename: str
    contentType: str
    sizeBytes: int
    taskId: str


class PublishCreationResponse(BaseModel):
    externalId: str
    platform: str
    status: str
    androidId: str
    materialId: str = ""
    publishJobId: str = ""
    taskId: str = ""
    attempt: int = 1
    errorMessage: str | None = None
    createdAt: str | None = None
    triggeredAt: str | None = None
    startedAt: str | None = None
    finishedAt: str | None = None
