from pydantic import BaseModel, Field


class AccountQuotaSchema(BaseModel):
    changeBatch: int
    changeSingle: int
    aiImage: int


class KnowledgeBaseSummarySchema(BaseModel):
    id: str
    name: str
    productName: str


class PublishSettingSchema(BaseModel):
    androidId: str
    platform: str = ""


class AccountSchema(BaseModel):
    id: str
    name: str
    type: str
    platform: str
    platforms: list[str]
    avatar: str
    description: str
    purpose: str
    accountLinks: dict[str, str]
    publishSettings: dict[str, PublishSettingSchema] = Field(default_factory=dict)
    industry: str
    productService: str
    targetCity: str
    targetAudience: str
    conversionGoal: str
    knowledgeBaseId: str | None
    knowledgeBaseSummary: KnowledgeBaseSummarySchema | None
    quota: AccountQuotaSchema


class AccountListResponse(BaseModel):
    items: list[AccountSchema]
    total: int
    page: int
    pageSize: int


class CreateAccountRequest(BaseModel):
    name: str
    description: str
    purpose: str
    type: str = "普通号"
    platform: str = "小红书"
    platforms: list[str] | None = None
    accountLinks: dict[str, str] | None = None
    publishSettings: dict[str, PublishSettingSchema] | None = None
    industry: str = ""
    productService: str = ""
    targetCity: str = ""
    targetAudience: str = ""
    conversionGoal: str = ""
    knowledgeBaseId: str | None = None


class UpdateAccountRequest(BaseModel):
    name: str
    description: str
    purpose: str
    type: str = "普通号"
    platform: str = "小红书"
    platforms: list[str] | None = None
    accountLinks: dict[str, str] | None = None
    publishSettings: dict[str, PublishSettingSchema] | None = None
    industry: str = ""
    productService: str = ""
    targetCity: str = ""
    targetAudience: str = ""
    conversionGoal: str = ""
    knowledgeBaseId: str | None = None
