"""账号报告证据与 AI 输出的数据契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
KeywordText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=12)]
TargetUserLevel = Literal["高", "较高", "中等", "较低", "低", "high", "medium", "low"]
SUPPORTED_REPORT_PLATFORM_ALIASES = {
    "xhs",
    "小红书",
    "dy",
    "douyin",
    "抖音",
    "ks",
    "kuaishou",
    "快手",
}


class EvidenceModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class ContentEvidence(EvidenceModel):
    platform: str
    content_id: str
    title: str = ""
    summary: str = ""
    creator_hash: str = ""
    creator_name: str = ""
    creator_display_name: str = ""
    creator_profile_url: str = ""
    creator_avatar_url: str = ""
    public_url: str = ""
    cover_url: str = ""
    video_download_url: str = ""
    published_at: str = ""
    liked_count: int = 0
    collected_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    view_count: int = 0
    source_keyword: str = ""
    engagement_score: int = 0
    hot_score: float = 0
    source_operation: str = ""
    source_sort: str = ""
    evidence_completeness: float = 0
    content_type: Literal["image", "video", "unknown"] = "unknown"


class CreatorEvidence(EvidenceModel):
    platform: str
    creator_hash: str
    name: str = ""
    display_name: str = Field(default="", alias="displayName")
    profile_url: str = Field(default="", alias="profileUrl")
    avatar_url: str = Field(default="", alias="avatarUrl")
    fans_count: int = 0
    works_count: int = 0
    liked_count: int = 0
    interaction_count: int = 0
    hit_content_count: int = 0
    representative_contents: list[str] = Field(default_factory=list, max_length=3)
    matched_queries: list[str] = Field(default_factory=list, max_length=5)
    source_operations: list[str] = Field(default_factory=list, max_length=10)
    evidence_completeness: float = 0
    similarity_score: float = 0


class CommentEvidence(EvidenceModel):
    """仅供报告提示词使用的有限、去身份化评论。"""

    platform: str
    content_id: str
    text: str
    liked_count: int = 0


class CurrentAccountEvidence(EvidenceModel):
    profiles: list[CreatorEvidence] = Field(default_factory=list, max_length=4)
    contents: list[ContentEvidence] = Field(default_factory=list, max_length=20)
    comments: list[CommentEvidence] = Field(default_factory=list, max_length=20)


class IndustryEvidence(EvidenceModel):
    hot_contents: list[ContentEvidence] = Field(
        default_factory=list, alias="hotContents", max_length=80
    )
    similar_accounts: list[CreatorEvidence] = Field(
        default_factory=list, alias="similarAccounts", max_length=40
    )
    comments: list[CommentEvidence] = Field(default_factory=list, max_length=20)


class AccountReportEvidence(EvidenceModel):
    current_account: CurrentAccountEvidence = Field(alias="currentAccountEvidence")
    industry: IndustryEvidence = Field(alias="industryEvidence")
    owner_hashes: list[str] = Field(default_factory=list, alias="ownerHashes")


ReportEvidence = AccountReportEvidence


class KeywordPack(BaseModel):
    """结构化词包：核心/长尾/同义/排除；检索用词由 core+longTail 收敛。"""

    model_config = ConfigDict(populate_by_name=True)

    core: list[KeywordText] = Field(default_factory=list, max_length=2)
    long_tail: list[KeywordText] = Field(
        default_factory=list, alias="longTail", max_length=6
    )
    synonyms: list[KeywordText] = Field(default_factory=list, max_length=4)
    excludes: list[KeywordText] = Field(default_factory=list, max_length=8)


class KeywordPlan(BaseModel):
    """各支持平台共用的 5 个检索词。"""

    model_config = ConfigDict(populate_by_name=True)

    keywords: list[KeywordText] = Field(min_length=5, max_length=5)
    pack: KeywordPack | None = None

    @field_validator("keywords")
    @classmethod
    def validate_keywords(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("检索词不得重复")
        return values


class SimilarAccount(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    platform: ShortText
    creator_hash: ShortText = Field(alias="creatorHash")
    name: ShortText
    profile_url: str = Field(default="", alias="profileUrl")
    avatar_url: str = Field(default="", alias="avatarUrl")
    similarity_reason: NonEmptyText = Field(alias="similarityReason")
    metrics: dict[str, Any] = Field(default_factory=dict)
    representative_contents: list[NonEmptyText] = Field(
        default_factory=list, alias="representativeContents", max_length=3
    )

    @field_validator("name", mode="before")
    @classmethod
    def clip_name(cls, value: Any) -> Any:
        text = " ".join(str(value or "").split()).strip()
        return text[:100] if text else value

    @field_validator("similarity_reason", mode="before")
    @classmethod
    def clip_similarity_reason(cls, value: Any) -> Any:
        text = " ".join(str(value or "").split()).strip()
        return text[:500] if text else value

    @field_validator("representative_contents", mode="before")
    @classmethod
    def clip_representative_contents(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        clipped: list[str] = []
        for item in value[:3]:
            text = " ".join(str(item or "").split()).strip()
            if text:
                clipped.append(text[:500])
        return clipped


class ComplianceRule(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    risk_level: Literal["high", "medium", "low"] = Field(alias="riskLevel")
    expression: NonEmptyText
    reason: NonEmptyText
    suggestion: NonEmptyText
    platforms: list[ShortText] = Field(default_factory=list, max_length=4)


class GenderUserProfile(BaseModel):
    """单一性别画像；无业务价值时允许明确标记为不适用。"""

    model_config = ConfigDict(extra="forbid")

    applicable: bool
    description: NonEmptyText


class TargetUserCategory(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    category_name: ShortText = Field(alias="categoryName")
    specific_profile: NonEmptyText | None = Field(default=None, alias="specificProfile")
    purchase_motivation: NonEmptyText = Field(alias="purchaseMotivation")
    male_profile: GenderUserProfile | None = Field(default=None, alias="maleProfile")
    female_profile: GenderUserProfile | None = Field(default=None, alias="femaleProfile")

    @model_validator(mode="after")
    def validate_profile_shape(self) -> "TargetUserCategory":
        if self.specific_profile or self.male_profile or self.female_profile:
            return self
        raise ValueError("目标用户类别必须包含 specificProfile 或兼容旧版性别画像")


class TargetUserRankingItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    category_name: ShortText = Field(alias="categoryName")
    priority: int | None = Field(default=None, ge=1, le=5)
    content_attraction: TargetUserLevel = Field(alias="contentAttraction")
    trust_difficulty: TargetUserLevel = Field(alias="trustDifficulty")
    payment_likelihood: TargetUserLevel = Field(alias="paymentLikelihood")
    repurchase_likelihood: TargetUserLevel = Field(alias="repurchaseLikelihood")
    reason: NonEmptyText


class TargetUserPriorityRanking(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    ranked_categories: list[TargetUserRankingItem] = Field(
        alias="rankedCategories", min_length=3, max_length=5
    )
    priority_category: ShortText = Field(alias="priorityCategory")
    priority_reason: NonEmptyText = Field(alias="priorityReason")


class TargetUserPositioningReminder(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    common_misjudgment: NonEmptyText = Field(alias="commonMisjudgment")
    hypothesis_to_validate: NonEmptyText = Field(alias="hypothesisToValidate")


class TargetUserProfile(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    assumption: str = Field(default="", max_length=500)
    categories: list[TargetUserCategory] = Field(min_length=3, max_length=5)
    priority_ranking: TargetUserPriorityRanking = Field(alias="priorityRanking")
    positioning_reminder: TargetUserPositioningReminder = Field(alias="positioningReminder")

    @model_validator(mode="after")
    def validate_category_ranking(self) -> "TargetUserProfile":
        category_names = [item.category_name for item in self.categories]
        ranked_names = [item.category_name for item in self.priority_ranking.ranked_categories]
        if len(set(category_names)) != len(category_names):
            raise ValueError("目标用户类别名称不得重复")
        if len(set(ranked_names)) != len(ranked_names) or set(ranked_names) != set(category_names):
            raise ValueError("优先用户排序必须完整且仅覆盖目标用户类别")
        if self.priority_ranking.priority_category != ranked_names[0]:
            raise ValueError("最值得优先服务的类别必须是优先排序第一项")
        return self


class HotContent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    platform: ShortText
    content_id: ShortText = Field(alias="contentId")
    title: NonEmptyText
    selection_reason: NonEmptyText = Field(alias="selectionReason")
    public_url: str = Field(default="", alias="publicUrl")
    cover_url: str = Field(default="", alias="coverUrl")
    content_type: Literal["image", "video", "unknown"] = Field(
        default="unknown", alias="contentType"
    )
    tags: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class SourceMeta(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    platforms: list[ShortText] = Field(max_length=4)
    keywords: list[KeywordText] = Field(max_length=5)
    sample_count: int = Field(alias="sampleCount", ge=0)
    failed_platforms: list[dict[str, Any]] = Field(
        default_factory=list, alias="failedPlatforms", max_length=10
    )
    unsupported_platforms: list[ShortText] = Field(
        default_factory=list, alias="unsupportedPlatforms", max_length=4
    )
    generated_at: datetime | None = Field(default=None, alias="generatedAt")

    @field_validator("keywords")
    @classmethod
    def validate_keyword_count(cls, values: list[str]) -> list[str]:
        if values and len(values) < 3:
            raise ValueError("非降级报告必须包含至少 3 个关键词")
        if len(set(values)) != len(values):
            raise ValueError("来源关键词不得重复")
        return values

    @field_validator("failed_platforms")
    @classmethod
    def validate_failed_platforms(cls, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in values:
            if not item:
                raise ValueError("失败平台摘要不得为空")
            sanitized: dict[str, Any] = {}
            for key, value in item.items():
                clean_key = str(key).strip()
                if not clean_key:
                    raise ValueError("失败平台摘要键不得为空")
                if isinstance(value, str):
                    value = value.strip()
                    if not value:
                        raise ValueError("失败平台摘要字符串不得为空")
                sanitized[clean_key] = value
            normalized.append(sanitized)
        return normalized

    @model_validator(mode="after")
    def validate_degraded_keyword_source(self) -> "SourceMeta":
        if self.keywords:
            return self
        normalized_platforms = {platform.strip().lower() for platform in self.platforms}
        if normalized_platforms & SUPPORTED_REPORT_PLATFORM_ALIASES:
            raise ValueError("包含支持平台时来源关键词不得为空")
        if "视频号" not in self.unsupported_platforms:
            raise ValueError("空来源关键词仅允许明确标记视频号不支持的降级报告")
        return self


class AccountReportPayload(BaseModel):
    """AI 一次性返回的完整账号报告；字段与持久化 JSON 一致。"""

    model_config = ConfigDict(populate_by_name=True)

    similar_accounts: list[SimilarAccount] = Field(alias="similarAccounts", max_length=20)
    compliance_rules: list[ComplianceRule] = Field(alias="complianceRules", min_length=1, max_length=20)
    target_user_profile: TargetUserProfile = Field(alias="targetUserProfile")
    hot_contents: list[HotContent] = Field(alias="hotContents", max_length=20)
    source_meta: SourceMeta = Field(alias="sourceMeta")

    def compatibility_summaries(self) -> dict[str, str]:
        """生成仍受支持的旧版四字段，保证老客户端继续获得可读中文内容。"""

        competitors = "；".join(
            f"{item.name}（{item.platform}）：{item.similarity_reason}"
            for item in self.similar_accounts
        ) or "暂无足够的公开相似账号样本。"
        risk_labels = {"high": "高", "medium": "中", "low": "低"}
        prohibited_words = "；".join(
            f"[{risk_labels[item.risk_level]}] {item.expression}：{item.reason}；建议：{item.suggestion}"
            for item in self.compliance_rules
        )
        profile = self.target_user_profile
        target_users = "；".join(
            f"{item.category_name}：{item.purchase_motivation}"
            for item in profile.categories
        )
        target_users += (
            f"。优先服务：{profile.priority_ranking.priority_category}，"
            f"{profile.priority_ranking.priority_reason}"
        )
        hot_content = "；".join(
            f"{item.title}（{item.platform}）：{item.selection_reason}"
            for item in self.hot_contents
        ) or "暂无足够的公开爆款样本。"
        return {
            "competitors": competitors,
            "prohibitedWords": prohibited_words,
            "targetUsers": target_users,
            "hotContent": hot_content,
        }
