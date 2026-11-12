from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from app.schemas.uploads import UploadedObjectRef


class GenerationAssetSchema(BaseModel):
    id: str
    assetType: str
    fileName: str
    mimeType: str
    url: str
    status: str
    analysis: str = ""
    error: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


class WorkflowStepSchema(BaseModel):
    id: str
    type: str
    status: str
    progress: int = 0
    sortOrder: int = 0
    groupKey: str = ""
    assetId: str | None = None
    inputPayload: dict[str, Any] = Field(default_factory=dict)
    resultPayload: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    createdAt: datetime
    updatedAt: datetime


class WorkflowSchema(BaseModel):
    id: str
    type: str
    creationId: str | None = None
    status: str
    progress: int = 0
    currentStage: str = ""
    targetPlatform: str
    title: str = ""
    topicTitle: str | None = None
    copyText: str = ""
    prompt: str = ""
    ratio: str | None = None
    requestedCount: int = 1
    error: str = ""
    inputPayload: dict[str, Any] = Field(default_factory=dict)
    resultPayload: dict[str, Any] = Field(default_factory=dict)
    assets: list[GenerationAssetSchema] = Field(default_factory=list)
    steps: list[WorkflowStepSchema] = Field(default_factory=list)
    createdAt: datetime
    updatedAt: datetime




class ImageGenerationSlotSchema(BaseModel):
    slotId: str
    sourceType: str = "manual"
    sourceUrl: str = ""
    sourcePrompt: str = ""


class CreatePromptWorkflowRequest(BaseModel):
    referenceUrls: list[str] = Field(default_factory=list, min_length=1, max_length=8)
    copyText: str = ""
    targetPlatform: str = ""
    topicTitle: str | None = None


class CreateImageWorkflowRequest(BaseModel):
    prompt: str
    selectedTagIds: list[str] = Field(default_factory=list)
    negativePrompt: str = ""
    count: int = Field(default=1, ge=1, le=8)
    ratio: str = "3:4"
    promptJobId: str | None = None
    sourcePromptWorkflowId: str | None = None
    referenceUrls: list[str] = Field(default_factory=list)
    materialUrls: list[str] = Field(default_factory=list)
    slots: list[ImageGenerationSlotSchema] = Field(default_factory=list)
    variantsPerSlot: int = Field(default=1, ge=1, le=2)
    refinement: str = ""
    regenerateSlotId: str | None = None
    referenceStrength: int = Field(default=70, ge=0, le=100)
    materialStrength: str = "中"


class CreateTopicPromptWorkflowRequest(BaseModel):
    topicId: str = ""
    topicTitle: str = ""
    copyText: str = ""
    targetPlatform: str = ""
    imageCount: int = Field(default=1, ge=1, le=4)
    collectionMode: Literal["independent", "series"] = "independent"
    ratio: Literal["1:1", "3:4", "9:16", "4:3", "16:9"] = "3:4"
    creativityLevel: Literal["low", "medium", "high"] = "medium"
    visualStyle: Literal[
        "auto",
        "realistic_photography",
        "commercial_poster",
        "lifestyle_editorial",
        "illustration",
        "minimal_graphic",
    ] = "auto"
    customRequirements: str = Field(default="", max_length=500)
    referenceUrls: list[str] = Field(default_factory=list, max_length=8)


class CreateScriptRewriteWorkflowRequest(BaseModel):
    originalScript: list[str] = Field(default_factory=list)
    copyText: str = ""
    targetPlatform: str = ""
    topicTitle: str | None = None


class CreateVideoScriptWorkflowRequest(BaseModel):
    topicId: str = Field(min_length=1)
    targetPlatform: str = Field(min_length=1)
    durationSeconds: Literal[30, 60, 90, 180] = 60
    contentGoal: Literal["auto", "exposure", "acquisition", "conversion", "persona"] = "auto"
    videoFormat: Literal[
        "auto",
        "list_talking_head",
        "knowledge_explainer",
        "vlog_workday",
        "story_case",
        "product_service_showcase",
        "interview_dialogue",
    ] = "auto"
    toneStyle: Literal[
        "auto",
        "professional",
        "conversational",
        "sharp",
        "humorous",
        "empathetic_story",
    ] = "auto"
    customRequirements: str = Field(default="", max_length=500)


class PromptTagSchema(BaseModel):
    id: str
    categoryId: str = ""
    label: str
    prompt: str
    source: str = "system"
    sortOrder: int = 0


class PromptTagCategorySchema(BaseModel):
    id: str
    label: str
    tags: list[PromptTagSchema]
    source: str = "system"
    sortOrder: int = 0


class PromptTagCategoryCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=64)
    sortOrder: int = 0


class PromptTagCategoryUpdateRequest(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=64)
    sortOrder: int | None = None


class PromptTagCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=64)
    prompt: str = Field(min_length=1)
    sortOrder: int = 0


class PromptTagUpdateRequest(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=64)
    prompt: str | None = Field(default=None, min_length=1)
    sortOrder: int | None = None


class ComposePromptRequest(BaseModel):
    prompt: str = Field(default="", max_length=500)
    selectedTagIds: list[str] = Field(default_factory=list)
    negativePrompt: str = ""


class ComposePromptResponse(BaseModel):
    prompt: str
    finalPrompt: str
    selectedTagIds: list[str]
    selectedTags: list[PromptTagSchema]
    negativePrompt: str = ""


class PromptTemplateParamsSchema(BaseModel):
    ratio: str = "3:4"
    count: str = "same"


class PromptTemplateCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    prompt: str = Field(default="", max_length=500)
    selectedTagIds: list[str] = Field(default_factory=list)
    negativePrompt: str = ""
    params: PromptTemplateParamsSchema = Field(default_factory=PromptTemplateParamsSchema)


class PromptTemplateUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    prompt: str | None = Field(default=None, max_length=500)
    selectedTagIds: list[str] | None = None
    negativePrompt: str | None = None
    params: PromptTemplateParamsSchema | None = None


class PromptTemplateSchema(BaseModel):
    id: str
    name: str
    description: str = ""
    prompt: str = ""
    selectedTagIds: list[str] = Field(default_factory=list)
    negativePrompt: str = ""
    params: dict[str, str] = Field(default_factory=dict)
    previewPrompt: str = ""
    createdAt: datetime
    updatedAt: datetime


class ReversePromptRequest(BaseModel):
    imageUrl: str
    uploadId: str = ""
    model: str | None = None
    title: str = ""
    description: str = ""
    targetPlatform: str = ""


class PersonReplacementRequest(BaseModel):
    targetImage: UploadedObjectRef
    personImage: UploadedObjectRef
    consentConfirmed: bool
    ratio: str = "3:4"
    count: int = Field(default=1, ge=1, le=4)


class ReversePromptResponse(BaseModel):
    positive: str
    negative: str = ""
    publishCopy: str = ""
    styleTags: list[str] = Field(default_factory=list)
    keyParams: dict[str, Any] = Field(default_factory=dict)
    imageUrl: str = ""
