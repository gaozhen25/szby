from pydantic import BaseModel, Field


class KnowledgeBaseSchema(BaseModel):
    id: str
    name: str
    productName: str
    industry: str
    productIntro: str
    brandStory: str
    price: str
    logoUrl: str
    imageMaterials: list[str]
    contactInfo: str
    websiteUrl: str
    enabledFields: dict[str, bool]
    createdAt: str
    updatedAt: str


class KnowledgeBaseListResponse(BaseModel):
    items: list[KnowledgeBaseSchema]
    total: int
    page: int
    pageSize: int


class CreateKnowledgeBaseRequest(BaseModel):
    name: str
    productName: str
    industry: str = ""
    productIntro: str = ""
    brandStory: str = ""
    price: str = ""
    logoUrl: str = ""
    imageMaterials: list[str] = Field(default_factory=list)
    contactInfo: str = ""
    websiteUrl: str = ""
    enabledFields: dict[str, bool]


class UpdateKnowledgeBaseRequest(BaseModel):
    name: str | None = None
    productName: str | None = None
    industry: str | None = None
    productIntro: str | None = None
    brandStory: str | None = None
    price: str | None = None
    logoUrl: str | None = None
    imageMaterials: list[str] | None = None
    contactInfo: str | None = None
    websiteUrl: str | None = None
    enabledFields: dict[str, bool] | None = None
