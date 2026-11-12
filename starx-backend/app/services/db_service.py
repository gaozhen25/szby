from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import String, cast, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import create_access_token, verify_password
from app.db.models import (
    AccountQuotaRecord,
    AccountRecord,
    ContentCreationRecord,
    CompetitorAccountRecord,
    CompetitorVideoRecord,
    DashboardAccountSnapshotRecord,
    DashboardContentSnapshotRecord,
    DashboardRecord,
    FavoriteTopicRecord,
    KnowledgeBaseRecord,
    MaterialRecord,
    ReportRecord,
    TaskRecord,
    TopicRecord,
    UserRecord,
)
from app.models.account import Account, AccountQuota, Dashboard, KnowledgeBase, KnowledgeBaseSummary, Report
from app.models.material import Material
from app.models.task import Task
from app.models.topic import FavoriteTopic, Topic
from app.models.user import User
from app.schemas.auth import AuthResponse, UserSchema
from app.schemas.creations import CreationContentSchema, CreationResponse
from app.services.publish_attempts import PublishAttemptMixin
from app.services.account_report.similar_accounts import (
    MAX_MANUAL_SIMILAR_ACCOUNTS,
    effective_similar_accounts,
    normalize_public_profile_url,
    same_similar_account,
    similar_account_key,
)


REPORT_SECTION_COLUMNS = {
    "competitors": "competitors",
    "prohibitedWords": "prohibited_words",
    "targetUsers": "target_users",
    "hotContent": "hot_content",
}

STRUCTURED_REPORT_COLUMNS = {
    "similarAccounts": "similar_accounts",
    "complianceRules": "compliance_rules",
    "targetUserProfile": "target_user_profile",
    "hotContents": "hot_contents",
    "sourceMeta": "source_meta",
}

SUPPORTED_PLATFORMS = {"小红书", "抖音", "视频号", "快手"}
BENCHMARK_ACCOUNT_PLATFORMS = {"小红书", "抖音"}
AUTOPHONE_PLATFORM_BY_ACCOUNT_PLATFORM = {
    "小红书": "xhs",
    "抖音": "douyin",
    "快手": "kuaishou",
}
ENABLED_KNOWLEDGE_BASE_FIELDS = {
    "productIntro",
    "brandStory",
    "price",
    "logoUrl",
    "imageMaterials",
    "contactInfo",
    "websiteUrl",
}
SERVER_OWNED_CREATION_STATE_KEYS = {"publish", "publishHistory"}


def normalize_benchmark_accounts(
    platforms: list[str],
    benchmark_accounts: dict[str, str] | None,
) -> dict[str, str]:
    """兼容旧对标号字段（可选）；忽略其它平台键。新流程改用 similarTargetFansWan。"""

    selected = list(platforms or [])
    selected_set = set(selected)
    normalized: dict[str, str] = {}
    for platform, raw in dict(benchmark_accounts or {}).items():
        name = str(platform or "").strip()
        value = str(raw or "").strip()
        if not name or not value:
            continue
        if name not in BENCHMARK_ACCOUNT_PLATFORMS:
            continue
        if name not in selected_set:
            raise ValueError("对标博主平台必须属于已选平台")
        if name in normalized:
            raise ValueError(f"{name}对标博主只能填写 1 个")
        normalized[name] = value
    return normalized


def normalize_similar_target_fans_wan(value: object) -> float | None:
    """相似账号目标粉丝数，单位万；空/无效视为未填。"""

    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("相似账号粉丝数须为数字（单位：万）") from exc
    if number <= 0:
        return None
    if number > 100_000:
        raise ValueError("相似账号粉丝数过大（单位：万）")
    return round(number, 2)


def normalize_platforms(platforms: list[str]) -> list[str]:
    normalized: list[str] = []
    for platform in platforms:
        if platform in SUPPORTED_PLATFORMS and platform not in normalized:
            normalized.append(platform)
    return normalized or ["小红书"]


def normalize_enabled_fields(enabled_fields: dict[str, bool]) -> dict[str, bool]:
    unknown_fields = set(enabled_fields) - ENABLED_KNOWLEDGE_BASE_FIELDS
    if unknown_fields:
        raise ValueError("enabledFields contains unsupported keys")
    return {field: bool(enabled_fields.get(field, False)) for field in sorted(ENABLED_KNOWLEDGE_BASE_FIELDS)}


def _bounded_limit(limit: int, *, default: int = 100, maximum: int = 100) -> int:
    try:
        value = int(limit)
    except Exception:
        value = default
    return min(max(value, 1), maximum)


def _merge_client_creation_state(
    existing_state: dict[str, object] | None,
    client_state: dict[str, object] | None,
) -> dict[str, object]:
    merged = dict(client_state or {})
    existing = dict(existing_state or {})
    for key in SERVER_OWNED_CREATION_STATE_KEYS:
        merged.pop(key, None)
        if key in existing:
            merged[key] = existing[key]
    return merged


class TaskCreationConflictError(ValueError):
    pass


class DBService(PublishAttemptMixin):
    def __init__(self, session: Session) -> None:
        self.session = session

    def login_user(self, email: str, password: str) -> AuthResponse:
        user = self.session.scalar(select(UserRecord).where(UserRecord.email == email, UserRecord.status == "active"))
        if user is None or not verify_password(password, user.password_hash):
            raise ValueError("invalid_credentials")
        return AuthResponse(
            accessToken=create_access_token(user.id),
            user=UserSchema(id=user.id, email=user.email, nickname=user.nickname),
        )

    def get_user(self, user_id: str) -> User | None:
        record = self.session.get(UserRecord, user_id)
        if record is None or record.status != "active":
            return None
        return User(id=record.id, email=record.email, password=record.password_hash, nickname=record.nickname)

    def _require_owned_knowledge_base(self, user_id: str, knowledge_base_id: str | None) -> KnowledgeBaseRecord | None:
        if knowledge_base_id is None:
            return None
        record = self.session.scalar(
            select(KnowledgeBaseRecord).where(
                KnowledgeBaseRecord.id == knowledge_base_id,
                KnowledgeBaseRecord.user_id == user_id,
                KnowledgeBaseRecord.status == "active",
            )
        )
        if record is None:
            raise ValueError("knowledge base is not available for this user")
        return record

    def _normalize_platform_accounts(
        self,
        platforms: list[str],
        platform_accounts: dict[str, str] | None,
    ) -> dict[str, str]:
        supported = {"抖音", "小红书"}
        cleaned = {
            str(platform).strip(): str(account).strip()
            for platform, account in (platform_accounts or {}).items()
            if str(platform).strip() and str(account).strip()
        }
        extra = set(cleaned) - set(platforms)
        unsupported = set(cleaned) - supported
        if extra or unsupported:
            raise ValueError("platformAccounts contains unsupported platform")
        return {platform: cleaned[platform] for platform in platforms if platform in cleaned}

    def _normalize_account_links(
        self,
        platforms: list[str],
        account_links: dict[str, str],
        platform_accounts: dict[str, str] | None = None,
    ) -> dict[str, str]:
        cleaned_links = {
            str(platform): str(link).strip()
            for platform, link in (account_links or {}).items()
            if str(platform).strip()
        }
        selected = set(platforms)
        provided = {platform for platform, link in cleaned_links.items() if link}
        covered_by_account = set(platform_accounts or {})
        missing = selected - provided - covered_by_account
        extra = set(cleaned_links) - selected
        if missing or extra:
            raise ValueError("platform links must cover selected platforms")
        return {
            platform: cleaned_links[platform]
            for platform in platforms
            if platform in cleaned_links and cleaned_links[platform]
        }

    def _normalize_publish_settings(
        self,
        platforms: list[str],
        publish_settings: dict[str, object] | None,
    ) -> dict[str, dict[str, str]]:
        if not publish_settings:
            return {}
        selected = set(platforms)
        normalized: dict[str, dict[str, str]] = {}
        for platform, raw_setting in publish_settings.items():
            platform_name = str(platform).strip()
            if platform_name not in selected:
                raise ValueError("publishSettings must target selected platforms")
            default_external_platform = AUTOPHONE_PLATFORM_BY_ACCOUNT_PLATFORM.get(platform_name)
            if default_external_platform is None:
                raise ValueError("publishSettings only supports 小红书, 抖音, and 快手")
            if hasattr(raw_setting, "model_dump"):
                setting = raw_setting.model_dump()
            elif isinstance(raw_setting, dict):
                setting = raw_setting
            else:
                raise ValueError("publishSettings contains invalid platform settings")
            android_id = str(setting.get("androidId") or "").strip()
            external_platform = str(setting.get("platform") or default_external_platform).strip()
            if not android_id:
                continue
            if external_platform not in {"xhs", "douyin", "kuaishou"}:
                raise ValueError("publishSettings contains unsupported external platform")
            normalized[platform_name] = {"androidId": android_id, "platform": external_platform}
        return normalized

    def _knowledge_base_summary_from_record(self, record: KnowledgeBaseRecord | None) -> KnowledgeBaseSummary | None:
        if record is None or record.status != "active":
            return None
        return KnowledgeBaseSummary(id=record.id, name=record.name, productName=record.product_name)

    def _knowledge_base_from_record(self, record: KnowledgeBaseRecord) -> KnowledgeBase:
        return KnowledgeBase(
            id=record.id,
            name=record.name,
            productName=record.product_name,
            industry=record.industry,
            productIntro=record.product_intro,
            brandStory=record.brand_story,
            price=record.price,
            logoUrl=record.logo_url,
            imageMaterials=list(record.image_materials or []),
            contactInfo=record.contact_info,
            websiteUrl=record.website_url,
            enabledFields=normalize_enabled_fields(dict(record.enabled_fields or {})),
            createdAt=record.created_at.isoformat(),
            updatedAt=record.updated_at.isoformat(),
        )

    def _account_from_record(self, record: AccountRecord) -> Account:
        quota = (
            self.session.scalars(
                select(AccountQuotaRecord)
                .where(AccountQuotaRecord.account_id == record.id)
                .order_by(AccountQuotaRecord.quota_date.desc())
            ).first()
        )
        platforms = normalize_platforms(list(record.platforms or [record.platform]))
        knowledge_base = record.knowledge_base
        if knowledge_base is None and record.knowledge_base_id:
            knowledge_base = self.session.get(KnowledgeBaseRecord, record.knowledge_base_id)
        report = self.session.get(ReportRecord, record.id)
        source_meta = dict(getattr(report, "source_meta", None) or {}) if report is not None else {}
        benchmark_accounts = {
            str(platform).strip(): str(value).strip()
            for platform, value in dict(source_meta.get("benchmarkAccounts") or {}).items()
            if str(platform or "").strip() and str(value or "").strip()
        }
        similar_target_fans_wan = None
        raw_fans_wan = source_meta.get("similarTargetFansWan")
        if raw_fans_wan is not None and raw_fans_wan != "":
            try:
                similar_target_fans_wan = normalize_similar_target_fans_wan(raw_fans_wan)
            except ValueError:
                similar_target_fans_wan = None
        return Account(
            id=record.id,
            name=record.name,
            type=record.account_type,
            platform=platforms[0],
            platforms=platforms,
            avatar=record.avatar,
            description=record.description,
            purpose=record.purpose,
            quota=AccountQuota(
                changeBatch=quota.change_batch_limit if quota else 5,
                changeSingle=quota.change_single_limit if quota else 3,
                aiImage=quota.ai_image_limit if quota else 10,
            ),
            accountLinks=dict(record.account_links or {}),
            platformAccounts=dict(record.platform_accounts or {}),
            platformAccountIdentities=dict(record.platform_account_identities or {}),
            benchmarkAccounts=benchmark_accounts,
            similarTargetFansWan=similar_target_fans_wan,
            publishSettings=dict(record.publish_settings or {}),
            industry=record.industry or "",
            productService=record.product_service or "",
            targetCity=record.target_city or "",
            targetAudience=record.target_audience or "",
            conversionGoal=record.conversion_goal or "",
            knowledgeBaseId=record.knowledge_base_id,
            knowledgeBaseSummary=self._knowledge_base_summary_from_record(knowledge_base),
        )

    def list_accounts(self, user_id: str) -> list[Account]:
        records = self.session.scalars(
            select(AccountRecord).where(AccountRecord.user_id == user_id, AccountRecord.status == "active").order_by(AccountRecord.id)
        ).all()
        return [self._account_from_record(record) for record in records]

    def list_accounts_page(
        self,
        user_id: str,
        *,
        page: int = 1,
        page_size: int = 12,
        keyword: str = "",
        platform: str = "",
    ) -> tuple[list[Account], int, int, int]:
        page_value = max(int(page or 1), 1)
        page_size_value = _bounded_limit(page_size, default=12, maximum=100)
        query = select(AccountRecord).where(
            AccountRecord.user_id == user_id,
            AccountRecord.status == "active",
        )

        platform_value = (platform or "").strip()
        if platform_value and platform_value != "全部":
            platform_pattern = f"%{platform_value}%"
            query = query.where(
                or_(
                    AccountRecord.platform == platform_value,
                    cast(AccountRecord.platforms, String).ilike(platform_pattern),
                )
            )

        keyword_value = (keyword or "").strip()
        if keyword_value:
            like_pattern = f"%{keyword_value}%"
            query = query.where(
                or_(
                    AccountRecord.name.ilike(like_pattern),
                    AccountRecord.description.ilike(like_pattern),
                    AccountRecord.purpose.ilike(like_pattern),
                    AccountRecord.account_type.ilike(like_pattern),
                    AccountRecord.industry.ilike(like_pattern),
                    AccountRecord.product_service.ilike(like_pattern),
                    AccountRecord.target_city.ilike(like_pattern),
                    AccountRecord.target_audience.ilike(like_pattern),
                    AccountRecord.conversion_goal.ilike(like_pattern),
                    AccountRecord.platform.ilike(like_pattern),
                    cast(AccountRecord.platforms, String).ilike(like_pattern),
                )
            )

        total = self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        records = self.session.scalars(
            query.order_by(AccountRecord.id)
            .offset((page_value - 1) * page_size_value)
            .limit(page_size_value)
        ).all()
        return [self._account_from_record(record) for record in records], total, page_value, page_size_value

    def get_account(self, user_id: str, account_id: str) -> Account:
        record = self.session.scalar(
            select(AccountRecord).where(AccountRecord.id == account_id, AccountRecord.user_id == user_id, AccountRecord.status == "active")
        )
        if record is None:
            raise StopIteration(account_id)
        return self._account_from_record(record)

    def create_account(
        self,
        user_id: str,
        name: str,
        description: str,
        purpose: str,
        account_type: str,
        platforms: list[str] | None = None,
        account_links: dict[str, str] | None = None,
        publish_settings: dict[str, object] | None = None,
        industry: str = "",
        product_service: str = "",
        target_city: str = "",
        target_audience: str = "",
        conversion_goal: str = "",
        knowledge_base_id: str | None = None,
        platform_accounts: dict[str, str] | None = None,
        benchmark_accounts: dict[str, str] | None = None,
        similar_target_fans_wan: float | None = None,
    ) -> Account:
        account_id = f"acc{uuid4().hex[:8]}"
        requested_platforms = platforms or ["小红书"]
        if not requested_platforms:
            raise ValueError("at least one supported platform must be selected")
        if any(platform not in SUPPORTED_PLATFORMS for platform in requested_platforms):
            raise ValueError("at least one supported platform must be selected")
        normalized_platforms = normalize_platforms(requested_platforms)
        # 对标账号字段已废弃：创建时忽略，避免写入旧数据
        _ = normalize_benchmark_accounts(normalized_platforms, benchmark_accounts)
        normalized_fans_wan = normalize_similar_target_fans_wan(similar_target_fans_wan)
        normalized_platform_accounts = self._normalize_platform_accounts(
            normalized_platforms, platform_accounts
        )
        normalized_account_links = self._normalize_account_links(
            normalized_platforms,
            account_links or {},
            normalized_platform_accounts,
        )
        normalized_publish_settings = self._normalize_publish_settings(normalized_platforms, publish_settings)
        knowledge_base = self._require_owned_knowledge_base(user_id, knowledge_base_id)
        account = AccountRecord(
            id=account_id,
            user_id=user_id,
            name=name,
            avatar=name[0],
            account_type=account_type,
            platform=normalized_platforms[0],
            platforms=normalized_platforms,
            description=description,
            purpose=purpose,
            account_links=normalized_account_links,
            platform_accounts=normalized_platform_accounts,
            platform_account_identities={},
            publish_settings=normalized_publish_settings,
            industry=(industry or "").strip(),
            product_service=(product_service or "").strip(),
            target_city=(target_city or "").strip(),
            target_audience=(target_audience or "").strip(),
            conversion_goal=(conversion_goal or "").strip(),
            knowledge_base_id=knowledge_base.id if knowledge_base else None,
            status="active",
        )
        self.session.add(account)
        self.session.add(
            AccountQuotaRecord(
                account_id=account_id,
                quota_date=date.today(),
                change_batch_limit=5,
                change_batch_used=0,
                change_single_limit=3,
                change_single_used=0,
                ai_image_limit=50 if account_type == "专业号" else 10,
                ai_image_used=0,
            )
        )
        self.session.add(DashboardRecord(account_id=account_id, views="0", change_count=0, creation=0, tools=0, competitor_count=0, competitor_posts=0, material_count=0))
        report_source_meta: dict[str, object] = {}
        # 新流程只存粉丝目标；不再写入对标账号
        if normalized_fans_wan is not None:
            report_source_meta["similarTargetFansWan"] = normalized_fans_wan
        self.session.add(
            ReportRecord(
                account_id=account_id,
                competitors="",
                prohibited_words="",
                target_users="",
                hot_content="",
                top_bloggers="",
                source_meta=report_source_meta,
            )
        )
        self.session.commit()
        return self._account_from_record(account)

    def update_account(
        self,
        user_id: str,
        account_id: str,
        name: str,
        description: str,
        purpose: str,
        account_type: str,
        platforms: list[str] | None = None,
        account_links: dict[str, str] | None = None,
        publish_settings: dict[str, object] | None = None,
        industry: str = "",
        product_service: str = "",
        target_city: str = "",
        target_audience: str = "",
        conversion_goal: str = "",
        knowledge_base_id: str | None = None,
        platform_accounts: dict[str, str] | None = None,
        benchmark_accounts: dict[str, str] | None = None,
        similar_target_fans_wan: float | None = None,
    ) -> Account:
        record = self.session.scalar(
            select(AccountRecord).where(
                AccountRecord.id == account_id,
                AccountRecord.user_id == user_id,
                AccountRecord.status == "active",
            )
        )
        if record is None:
            raise StopIteration(account_id)
        requested_platforms = platforms or [record.platform or "小红书"]
        if not requested_platforms:
            raise ValueError("at least one supported platform must be selected")
        if any(platform not in SUPPORTED_PLATFORMS for platform in requested_platforms):
            raise ValueError("at least one supported platform must be selected")
        normalized_platforms = normalize_platforms(requested_platforms)
        # 对标账号字段已废弃：更新时清空旧值
        _ = normalize_benchmark_accounts(normalized_platforms, benchmark_accounts)
        normalized_fans_wan = normalize_similar_target_fans_wan(similar_target_fans_wan)
        normalized_platform_accounts = self._normalize_platform_accounts(
            normalized_platforms, platform_accounts
        )
        normalized_account_links = self._normalize_account_links(
            normalized_platforms,
            account_links or {},
            normalized_platform_accounts,
        )
        normalized_publish_settings = self._normalize_publish_settings(normalized_platforms, publish_settings)
        knowledge_base = self._require_owned_knowledge_base(user_id, knowledge_base_id or None)

        cleaned_name = (name or "").strip()
        record.name = cleaned_name
        record.avatar = cleaned_name[0] if cleaned_name else record.avatar
        record.account_type = account_type
        record.platform = normalized_platforms[0]
        record.platforms = normalized_platforms
        record.description = description
        record.purpose = purpose
        record.account_links = normalized_account_links
        previous_identities = dict(record.platform_account_identities or {})
        previous_platform_accounts = dict(record.platform_accounts or {})
        changed_social_platforms = {
            platform
            for platform in {"抖音", "小红书"}
            if previous_platform_accounts.get(platform)
            != normalized_platform_accounts.get(platform)
        }
        record.platform_accounts = normalized_platform_accounts
        record.platform_account_identities = {
            platform: identity
            for platform, identity in previous_identities.items()
            if platform in normalized_platform_accounts
            and str(identity.get("input") or "") == normalized_platform_accounts[platform]
        }
        for changed_platform in changed_social_platforms:
            self.session.execute(
                delete(DashboardContentSnapshotRecord).where(
                    DashboardContentSnapshotRecord.account_id == account_id,
                    DashboardContentSnapshotRecord.platform == changed_platform,
                )
            )
            self.session.execute(
                delete(DashboardAccountSnapshotRecord).where(
                    DashboardAccountSnapshotRecord.account_id == account_id,
                    DashboardAccountSnapshotRecord.platform == changed_platform,
                )
            )
        record.publish_settings = normalized_publish_settings
        record.industry = (industry or "").strip()
        record.product_service = (product_service or "").strip()
        record.target_city = (target_city or "").strip()
        record.target_audience = (target_audience or "").strip()
        record.conversion_goal = (conversion_goal or "").strip()
        record.knowledge_base_id = knowledge_base.id if knowledge_base else None
        record.updated_at = datetime.now(UTC)
        report = self.session.get(ReportRecord, account_id)
        if report is not None:
            meta = dict(report.source_meta or {})
            meta.pop("benchmarkAccounts", None)
            if normalized_fans_wan is not None:
                meta["similarTargetFansWan"] = normalized_fans_wan
            else:
                meta.pop("similarTargetFansWan", None)
            report.source_meta = meta
        self.session.commit()
        self.session.refresh(record)
        return self._account_from_record(record)

    def list_knowledge_bases(
        self,
        user_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        keyword: str = "",
    ) -> tuple[list[KnowledgeBase], int, int, int]:
        page_value = max(int(page or 1), 1)
        page_size_value = _bounded_limit(page_size, default=20, maximum=100)
        query = select(KnowledgeBaseRecord).where(
            KnowledgeBaseRecord.user_id == user_id,
            KnowledgeBaseRecord.status == "active",
        )
        keyword_value = (keyword or "").strip()
        if keyword_value:
            like_pattern = f"%{keyword_value}%"
            query = query.where(
                or_(
                    KnowledgeBaseRecord.name.ilike(like_pattern),
                    KnowledgeBaseRecord.product_name.ilike(like_pattern),
                )
            )
        total = self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        records = self.session.scalars(
            query
            .order_by(KnowledgeBaseRecord.created_at.desc(), KnowledgeBaseRecord.id.desc())
            .offset((page_value - 1) * page_size_value)
            .limit(page_size_value)
        ).all()
        return [self._knowledge_base_from_record(record) for record in records], total, page_value, page_size_value

    def get_knowledge_base(self, user_id: str, knowledge_base_id: str) -> KnowledgeBase:
        record = self._require_owned_knowledge_base(user_id, knowledge_base_id)
        assert record is not None
        return self._knowledge_base_from_record(record)

    def create_knowledge_base(
        self,
        user_id: str,
        name: str,
        product_name: str,
        product_intro: str,
        brand_story: str,
        price: str,
        logo_url: str,
        image_materials: list[str],
        contact_info: str,
        website_url: str,
        enabled_fields: dict[str, bool],
        *,
        industry: str = "",
    ) -> KnowledgeBase:
        record = KnowledgeBaseRecord(
            id=f"kb{uuid4().hex[:10]}",
            user_id=user_id,
            name=name,
            product_name=product_name,
            industry=(industry or "").strip(),
            product_intro=product_intro,
            brand_story=brand_story,
            price=price,
            logo_url=logo_url,
            image_materials=list(image_materials or []),
            contact_info=contact_info,
            website_url=website_url,
            enabled_fields=normalize_enabled_fields(enabled_fields),
            status="active",
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._knowledge_base_from_record(record)

    def update_knowledge_base(
        self,
        user_id: str,
        knowledge_base_id: str,
        *,
        name: str | None = None,
        product_name: str | None = None,
        industry: str | None = None,
        product_intro: str | None = None,
        brand_story: str | None = None,
        price: str | None = None,
        logo_url: str | None = None,
        image_materials: list[str] | None = None,
        contact_info: str | None = None,
        website_url: str | None = None,
        enabled_fields: dict[str, bool] | None = None,
    ) -> KnowledgeBase:
        record = self._require_owned_knowledge_base(user_id, knowledge_base_id)
        assert record is not None
        if name is not None:
            record.name = name
        if product_name is not None:
            record.product_name = product_name
        if industry is not None:
            record.industry = industry.strip()
        if product_intro is not None:
            record.product_intro = product_intro
        if brand_story is not None:
            record.brand_story = brand_story
        if price is not None:
            record.price = price
        if logo_url is not None:
            record.logo_url = logo_url
        if image_materials is not None:
            record.image_materials = list(image_materials)
        if contact_info is not None:
            record.contact_info = contact_info
        if website_url is not None:
            record.website_url = website_url
        if enabled_fields is not None:
            record.enabled_fields = normalize_enabled_fields(enabled_fields)
        record.updated_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(record)
        return self._knowledge_base_from_record(record)

    def delete_knowledge_base(self, user_id: str, knowledge_base_id: str) -> bool:
        record = self._require_owned_knowledge_base(user_id, knowledge_base_id)
        assert record is not None
        bound_account = self.session.scalar(
            select(AccountRecord).where(
                AccountRecord.user_id == user_id,
                AccountRecord.knowledge_base_id == knowledge_base_id,
                AccountRecord.status == "active",
            )
        )
        if bound_account is not None:
            raise ValueError("knowledge base is still bound to active accounts")
        record.status = "deleted"
        record.updated_at = datetime.now(UTC)
        self.session.commit()
        return True

    def delete_account(self, user_id: str, account_id: str) -> bool:
        try:
            record = self.session.scalar(
                select(AccountRecord).where(AccountRecord.id == account_id, AccountRecord.user_id == user_id, AccountRecord.status == "active")
            )
            if record is None:
                raise StopIteration(account_id)
            record.status = "deleted"
            self.session.commit()
            return True
        except StopIteration:
            return False

    def _topic_from_record(self, record: TopicRecord) -> Topic:
        topic_id = record.id.rsplit("_", 1)[-1]
        return Topic(
            id=topic_id,
            title=record.title,
            source=record.source,
            category=record.category,
            type=record.content_type,
            reason=record.reason or "",
            platforms=list(record.platforms or []),
            referenceNote=dict(record.reference_note or {}),
            batchId=record.batch_id or "",
        )

    def _favorite_topic_from_record(self, record: FavoriteTopicRecord) -> FavoriteTopic:
        return FavoriteTopic(
            id=record.id,
            title=record.title,
            source=record.source,
            category=record.category,
            type=record.content_type,
            reason=record.reason or "",
            platforms=list(record.platforms or []),
            referenceNote=dict(record.reference_note or {}),
            batchId=record.source_batch_id or "",
            sourceTopicId=record.source_topic_id,
            sourceBatchId=record.source_batch_id or "",
            collectedAt=record.created_at,
        )

    def list_topics(self, user_id: str, account_id: str, limit: int = 100) -> list[Topic]:
        self.get_account(user_id, account_id)
        records = self.session.scalars(
            select(TopicRecord)
            .where(
                TopicRecord.account_id == account_id,
                TopicRecord.batch_id != "",
            )
            .order_by(TopicRecord.sort_order, TopicRecord.id)
            .limit(_bounded_limit(limit))
        ).all()
        return [self._topic_from_record(record) for record in records]

    def refresh_topics(self, user_id: str, account_id: str) -> list[Topic]:
        records = self.session.scalars(
            select(TopicRecord)
            .where(TopicRecord.account_id == account_id)
            .order_by(TopicRecord.sort_order, TopicRecord.id)
        ).all()
        for record in records:
            record.title = record.title.replace(" ✨", "") + " ✨"
            record.updated_at = datetime.now(UTC)
        self.session.commit()
        return [self._topic_from_record(record) for record in records]

    def list_favorite_topics(self, user_id: str, account_id: str, limit: int = 100) -> list[FavoriteTopic]:
        self.get_account(user_id, account_id)
        records = self.session.scalars(
            select(FavoriteTopicRecord)
            .where(FavoriteTopicRecord.account_id == account_id)
            .order_by(FavoriteTopicRecord.created_at.desc(), FavoriteTopicRecord.id.desc())
            .limit(_bounded_limit(limit))
        ).all()
        return [self._favorite_topic_from_record(record) for record in records]

    def favorite_topic(self, user_id: str, account_id: str, topic_id: str) -> FavoriteTopic:
        self.get_account(user_id, account_id)
        topic = self.session.scalar(
            select(TopicRecord).where(
                TopicRecord.id == f"{account_id}_{topic_id}",
                TopicRecord.account_id == account_id,
            )
        )
        if topic is None:
            raise StopIteration(topic_id)
        existing = self.session.scalar(
            select(FavoriteTopicRecord).where(
                FavoriteTopicRecord.account_id == account_id,
                FavoriteTopicRecord.source_topic_id == topic_id,
                FavoriteTopicRecord.source_batch_id == (topic.batch_id or ""),
            )
        )
        if existing is not None:
            return self._favorite_topic_from_record(existing)
        record = FavoriteTopicRecord(
            id=f"fav_{uuid4().hex}",
            account_id=account_id,
            source_topic_id=topic_id,
            source_batch_id=topic.batch_id or "",
            title=topic.title,
            source=topic.source,
            category=topic.category,
            content_type=topic.content_type,
            reason=topic.reason or "",
            platforms=list(topic.platforms or []),
            reference_note=dict(topic.reference_note or {}),
            created_at=datetime.now(UTC),
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._favorite_topic_from_record(record)

    def delete_favorite_topic(self, user_id: str, account_id: str, favorite_id: str) -> bool:
        self.get_account(user_id, account_id)
        record = self.session.scalar(
            select(FavoriteTopicRecord).where(
                FavoriteTopicRecord.id == favorite_id,
                FavoriteTopicRecord.account_id == account_id,
            )
        )
        if record is None:
            return False
        self.session.delete(record)
        self.session.commit()
        return True

    def generate_creation(self, user_id: str, account_id: str, topic_id: str, target_platform: str) -> CreationResponse:
        self.get_account(user_id, account_id)
        from app.services.topic_repository import find_topic_snapshot

        topic = find_topic_snapshot(self.session, account_id=account_id, topic_id=topic_id)
        if topic is None:
            raise StopIteration(topic_id)
        platform_copy = {
            "小红书": ("封面点击率", "轻快电子 / Lo-Fi Beats"),
            "视频号": ("可信表达", "轻节奏钢琴"),
            "抖音": ("强钩子反差", "高节奏流行剪辑 BGM"),
            "快手": ("真实生活感", "轻节奏市井氛围 BGM"),
        }
        style_label, bgm = platform_copy[target_platform]
        is_video = topic.content_type == "video"
        content = CreationContentSchema(
            scriptOriginal=[] if is_video else [
                f"围绕 {topic.title} 输出符合 {target_platform} 的原版脚本",
                f"重点强调 {style_label} 和平台推荐机制",
            ],
            scriptRewritten=[] if is_video else [
                f"输出去 AI 标签后的 {target_platform} 风格改写脚本",
                "保留信息密度与平台语言风格",
            ],
            title=f"{topic.title} · {target_platform}版",
            body=f"这是一条面向 {target_platform} 的{topic.category}内容，重点突出 {style_label}。",
            hashtags=[f"#{topic.category}", f"#{target_platform}", "#内容创作"],
            cover={"fileId": f"file_{topic_id}", "url": f"https://oss.example.com/{account_id}/{topic_id}.jpg"},
            bgmSuggestion=bgm,
            sensitiveCheck={"status": "passed", "issues": [], "platform": target_platform},
        )
        return CreationResponse(
            creationId=str(uuid4()),
            topicId=topic_id,
            topicTitle=topic.title,
            type=topic.content_type,
            targetPlatform=target_platform,
            content=content,
            creationState={"referenceNote": dict(topic.reference_note or {})},
        )

    def _creation_from_record(self, record: ContentCreationRecord) -> CreationResponse:
        content = CreationContentSchema(
            scriptOriginal=list(record.script_original or []),
            scriptRewritten=list(record.script_rewritten or []),
            title=record.title,
            body=record.body,
            hashtags=list(record.hashtags or []),
            cover=dict(record.cover or {}),
            bgmSuggestion=record.bgm_suggestion,
            sensitiveCheck=dict(record.sensitive_check or {}),
            imagePrompt=record.image_prompt,
            assets=list(record.assets or []),
        )
        return CreationResponse(
            creationId=record.id,
            topicId=record.topic_id,
            topicTitle=record.topic_title,
            type=record.content_type,
            targetPlatform=record.target_platform,
            content=content,
            creationState=self._creation_state_with_publish_attempts(record),
        )

    def _task_from_record(self, record: TaskRecord) -> Task:
        return Task(
            id=record.id,
            title=record.title,
            type=record.content_type,
            status=record.status,
            updated=record.updated,
            targetPlatform=record.target_platform,
            creationId=record.creation_id,
            body=record.body,
            tags=list(record.tags or []),
            assignee=record.assignee,
            dueDate=record.due_date,
            priority=record.priority,
            handoffNote=record.handoff_note,
        )

    def get_creation(self, user_id: str, account_id: str, creation_id: str) -> CreationResponse:
        self.get_account(user_id, account_id)
        record = self.session.scalar(
            select(ContentCreationRecord).where(
                ContentCreationRecord.id == creation_id,
                ContentCreationRecord.account_id == account_id,
                ContentCreationRecord.user_id == user_id,
            )
        )
        if record is None:
            raise StopIteration(creation_id)
        return self._creation_from_record(record)

    def submit_creation_task(
        self,
        user_id: str,
        account_id: str,
        creation_id: str,
        topic_id: str,
        target_platform: str,
        content_type: str,
        content: CreationContentSchema,
        *,
        creation_state: dict[str, object] | None = None,
        assignee: str = "",
        due_date: str = "",
        priority: str = "normal",
        status: str = "draft",
        handoff_note: str = "",
        commit: bool = True,
    ) -> Task:
        self.get_account(user_id, account_id)
        topic_title = ""
        if topic_id:
            topic = self.session.get(TopicRecord, f"{account_id}_{topic_id}")
            topic_title = topic.title if topic else ""
        title = content.title.strip() or topic_title or "未命名创作"
        body = content.body.strip() or "\n".join(content.scriptRewritten or content.scriptOriginal)
        now = datetime.now(UTC)
        creation = self.session.get(ContentCreationRecord, creation_id)
        if creation is None:
            creation = ContentCreationRecord(
                id=creation_id,
                account_id=account_id,
                user_id=user_id,
                topic_id=topic_id,
                topic_title=topic_title,
                title=title,
                content_type=content_type,
                target_platform=target_platform,
                body=body,
            )
            self.session.add(creation)
        elif creation.account_id != account_id or creation.user_id != user_id:
            raise StopIteration(creation_id)
        creation.topic_id = topic_id
        creation.topic_title = topic_title or creation.topic_title
        creation.title = title
        creation.content_type = content_type
        creation.target_platform = target_platform
        creation.body = body
        creation.script_original = list(content.scriptOriginal or [])
        creation.script_rewritten = list(content.scriptRewritten or [])
        creation.hashtags = list(content.hashtags or [])
        creation.cover = dict(content.cover or {})
        creation.bgm_suggestion = content.bgmSuggestion or ""
        creation.sensitive_check = dict(content.sensitiveCheck or {})
        creation.image_prompt = content.imagePrompt or ""
        creation.assets = list(content.assets or [])
        creation.creation_state = _merge_client_creation_state(creation.creation_state, creation_state)
        creation.updated_at = now

        task = self.session.scalar(
            select(TaskRecord).where(TaskRecord.account_id == account_id, TaskRecord.creation_id == creation_id)
        )
        if task is None:
            task = TaskRecord(
                id=f"k{uuid4().hex[:8]}",
                account_id=account_id,
                creation_id=creation_id,
                title=title,
                content_type=content_type,
                status=status or "draft",
                updated="刚刚",
                target_platform=target_platform,
            )
            self.session.add(task)
        task.title = title
        task.content_type = content_type
        task.status = status or task.status or "draft"
        task.updated = "刚刚"
        task.target_platform = target_platform
        task.body = body
        task.tags = list(content.hashtags or [])
        task.assignee = assignee.strip()
        task.due_date = due_date.strip()
        task.priority = priority if priority in {"low", "normal", "high"} else "normal"
        task.handoff_note = handoff_note.strip()
        if commit:
            self.session.commit()
            self.session.refresh(task)
        else:
            self.session.flush()
        return self._task_from_record(task)

    def list_tasks(self, user_id: str, account_id: str, limit: int = 100) -> list[Task]:
        self.get_account(user_id, account_id)
        records = self.session.scalars(
            select(TaskRecord)
            .where(TaskRecord.account_id == account_id)
            .order_by(TaskRecord.id.desc())
            .limit(_bounded_limit(limit))
        ).all()
        return [self._task_from_record(record) for record in records]

    def get_creation_workflow_task(
        self,
        user_id: str,
        account_id: str,
        creation_id: str,
        task_id: str,
    ) -> Task:
        """Return the owned workflow task only when it is bound to this creation."""
        self.get_account(user_id, account_id)
        record = self.session.scalar(
            select(TaskRecord).where(
                TaskRecord.id == task_id,
                TaskRecord.account_id == account_id,
                TaskRecord.creation_id == creation_id,
            )
        )
        if record is None:
            raise StopIteration(task_id)
        creation = self.session.scalar(
            select(ContentCreationRecord.id).where(
                ContentCreationRecord.id == creation_id,
                ContentCreationRecord.account_id == account_id,
                ContentCreationRecord.user_id == user_id,
            )
        )
        if creation is None:
            raise StopIteration(creation_id)
        return self._task_from_record(record)

    def create_task(
        self,
        user_id: str,
        account_id: str,
        title: str,
        content_type: str,
        target_platform: str,
        *,
        creation_id: str | None = None,
        body: str = "",
        tags: list[str] | None = None,
        assignee: str = "",
        due_date: str = "",
        priority: str = "normal",
        handoff_note: str = "",
    ) -> Task:
        self.get_account(user_id, account_id)
        if creation_id:
            creation = self.session.scalar(
                select(ContentCreationRecord).where(
                    ContentCreationRecord.id == creation_id,
                    ContentCreationRecord.account_id == account_id,
                    ContentCreationRecord.user_id == user_id,
                )
            )
            if creation is None:
                raise StopIteration(creation_id)
            existing_task = self.session.scalar(
                select(TaskRecord).where(TaskRecord.creation_id == creation_id)
            )
            if existing_task is not None:
                raise TaskCreationConflictError(creation_id)
        task = TaskRecord(
            id=f"k{uuid4().hex[:8]}",
            account_id=account_id,
            creation_id=creation_id,
            title=title,
            content_type=content_type,
            status="draft",
            updated="刚刚",
            target_platform=target_platform,
            body=body,
            tags=list(tags or []),
            assignee=assignee,
            due_date=due_date,
            priority=priority if priority in {"low", "normal", "high"} else "normal",
            handoff_note=handoff_note,
        )
        self.session.add(task)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            if creation_id and self.session.scalar(
                select(TaskRecord).where(TaskRecord.creation_id == creation_id)
            ) is not None:
                raise TaskCreationConflictError(creation_id) from None
            raise
        return self._task_from_record(task)

    def duplicate_task(self, user_id: str, account_id: str, task_id: str) -> Task:
        """复制流程任务及其关联创作，所有新记录使用独立标识。"""
        self.get_account(user_id, account_id)
        source_task = self.session.scalar(
            select(TaskRecord).where(
                TaskRecord.id == task_id,
                TaskRecord.account_id == account_id,
            )
        )
        if source_task is None:
            raise StopIteration(task_id)

        new_task_id = f"k{uuid4().hex[:8]}"
        new_creation_id: str | None = None
        if source_task.creation_id:
            source_creation = self.session.scalar(
                select(ContentCreationRecord).where(
                    ContentCreationRecord.id == source_task.creation_id,
                    ContentCreationRecord.account_id == account_id,
                    ContentCreationRecord.user_id == user_id,
                )
            )
            if source_creation is None:
                raise StopIteration(source_task.creation_id)

            new_creation_id = f"copy_{uuid4().hex[:31]}"

            def copy_value(value: object) -> object:
                if isinstance(value, dict):
                    return {key: copy_value(item) for key, item in value.items()}
                if isinstance(value, list):
                    return [copy_value(item) for item in value]
                if value == source_task.id:
                    return new_task_id
                if value == source_creation.id:
                    return new_creation_id
                return deepcopy(value)

            # 发布结果属于原流程的运行记录，不能让副本被误判为已经发布。
            creation_state = {
                key: copy_value(value)
                for key, value in (source_creation.creation_state or {}).items()
                if key not in SERVER_OWNED_CREATION_STATE_KEYS
            }
            now = datetime.now(UTC)
            self.session.add(ContentCreationRecord(
                id=new_creation_id,
                account_id=account_id,
                user_id=user_id,
                topic_id=source_creation.topic_id,
                topic_title=source_creation.topic_title,
                title=source_creation.title,
                content_type=source_creation.content_type,
                target_platform=source_creation.target_platform,
                body=source_creation.body,
                script_original=copy_value(source_creation.script_original),
                script_rewritten=copy_value(source_creation.script_rewritten),
                hashtags=copy_value(source_creation.hashtags),
                cover=copy_value(source_creation.cover),
                bgm_suggestion=source_creation.bgm_suggestion,
                sensitive_check=copy_value(source_creation.sensitive_check),
                image_prompt=source_creation.image_prompt,
                assets=copy_value(source_creation.assets),
                creation_state=creation_state,
                created_at=now,
                updated_at=now,
            ))

        duplicate = TaskRecord(
            id=new_task_id,
            account_id=account_id,
            creation_id=new_creation_id,
            title=source_task.title,
            content_type=source_task.content_type,
            status=source_task.status,
            updated="刚刚",
            target_platform=source_task.target_platform,
            body=source_task.body,
            tags=deepcopy(source_task.tags or []),
            assignee=source_task.assignee,
            due_date=source_task.due_date,
            priority=source_task.priority,
            handoff_note=source_task.handoff_note,
        )
        self.session.add(duplicate)
        self.session.commit()
        self.session.refresh(duplicate)
        return self._task_from_record(duplicate)

    def update_task_status(self, user_id: str, account_id: str, task_id: str, status: str) -> Task:
        self.get_account(user_id, account_id)
        task = self.session.get(TaskRecord, task_id)
        if task is None or task.account_id != account_id:
            raise StopIteration(task_id)
        task.status = status
        task.updated = "刚刚"
        self.session.commit()
        return self._task_from_record(task)

    def list_materials(self, user_id: str, account_id: str, limit: int = 100) -> list[Material]:
        self.get_account(user_id, account_id)
        records = self.session.scalars(
            select(MaterialRecord)
            .where(MaterialRecord.account_id == account_id)
            .order_by(MaterialRecord.id.desc())
            .limit(_bounded_limit(limit))
        ).all()
        return [
            Material(
                id=record.id,
                name=record.name,
                type=record.material_type,
                tags=list(record.tags or []),
                date=record.material_date,
                thumb=record.thumb,
                assets=list(record.assets or []),
            )
            for record in records
        ]

    def create_material(
        self,
        user_id: str,
        account_id: str,
        name: str,
        material_type: str,
        tags: list[str],
        thumb: str,
        assets: list[dict[str, object]] | None = None,
    ) -> Material:
        self.get_account(user_id, account_id)
        material = MaterialRecord(
            id=f"m{uuid4().hex[:8]}",
            account_id=account_id,
            name=name,
            material_type=material_type,
            tags=tags,
            material_date=str(date.today()),
            thumb=thumb,
            assets=list(assets or []),
        )
        self.session.add(material)
        self.session.commit()
        return Material(
            id=material.id,
            name=material.name,
            type=material.material_type,
            tags=list(material.tags or []),
            date=material.material_date,
            thumb=material.thumb,
            assets=list(material.assets or []),
        )

    def get_dashboard(self, user_id: str, account_id: str) -> Dashboard:
        self.get_account(user_id, account_id)
        record = self.session.get(DashboardRecord, account_id)
        competitor_count = self.session.scalar(
            select(func.count())
            .select_from(CompetitorAccountRecord)
            .where(
                CompetitorAccountRecord.user_id == user_id,
                CompetitorAccountRecord.account_id == account_id,
            )
        ) or 0
        competitor_posts = self.session.scalar(
            select(func.count())
            .select_from(CompetitorVideoRecord)
            .where(
                CompetitorVideoRecord.user_id == user_id,
                CompetitorVideoRecord.account_id == account_id,
            )
        ) or 0
        if record is None:
            return Dashboard("0", 0, 0, 0, competitor_count, competitor_posts, 0)
        return Dashboard(
            record.views,
            record.change_count,
            record.creation,
            record.tools,
            competitor_count,
            competitor_posts,
            record.material_count,
        )

    def summary(self, user_id: str) -> list[dict[str, object]]:
        return [
            {"id": account.id, "name": account.name, "type": account.type, "dashboard": asdict(self.get_dashboard(user_id, account.id))}
            for account in self.list_accounts(user_id)
        ]

    def get_report(self, user_id: str, account_id: str) -> Report:
        self.get_account(user_id, account_id)
        record = self.session.get(ReportRecord, account_id)
        if record is None:
            raise KeyError(account_id)
        return self._report_from_record(record)

    @staticmethod
    def _report_from_record(record: ReportRecord) -> Report:
        generated_at = record.generated_at
        if generated_at is not None:
            generated_at = (
                generated_at.replace(tzinfo=UTC) if generated_at.tzinfo is None else generated_at.astimezone(UTC)
            )
        return Report(
            competitors=record.competitors,
            prohibitedWords=record.prohibited_words,
            targetUsers=record.target_users,
            hotContent=record.hot_content,
            similarAccounts=effective_similar_accounts(record),
            complianceRules=list(record.compliance_rules or []),
            targetUserProfile=dict(record.target_user_profile or {}),
            hotContents=list(record.hot_contents or []),
            sourceMeta=dict(record.source_meta or {}),
            reportVersion=record.report_version,
            generatedAt=generated_at,
        )

    def add_report_similar_account(
        self,
        user_id: str,
        account_id: str,
        payload: dict[str, Any],
    ) -> Report:
        """添加独立于 AI 报告快照的人工相似账号配置。"""

        try:
            self.get_account(user_id, account_id)
            record = self.session.scalar(
                select(ReportRecord)
                .where(ReportRecord.account_id == account_id)
                .with_for_update()
            )
            if record is None:
                raise KeyError(account_id)

            manual_accounts = [dict(item) for item in record.manual_similar_accounts or []]
            if len(manual_accounts) >= MAX_MANUAL_SIMILAR_ACCOUNTS:
                raise ValueError(f"最多可手动配置 {MAX_MANUAL_SIMILAR_ACCOUNTS} 个相似账号")

            candidate = {
                "platform": str(payload.get("platform") or "").strip(),
                "creatorHash": f"manual_{uuid4().hex}",
                "name": str(payload.get("name") or "").strip(),
                "profileUrl": normalize_public_profile_url(
                    str(payload.get("platform") or "").strip(),
                    str(payload.get("profileUrl") or ""),
                ),
                "similarityReason": str(payload.get("similarityReason") or "用户手动添加").strip(),
                "avatarUrl": str(payload.get("avatarUrl") or "").strip(),
                "description": str(payload.get("description") or "").strip(),
                "ipLocation": str(payload.get("ipLocation") or "").strip(),
                "metrics": {
                    "fansCount": max(int(payload.get("followers") or 0), 0),
                    "worksCount": max(int(payload.get("contentCount") or 0), 0),
                    "likedCount": max(int(payload.get("totalLikes") or 0), 0),
                },
                "representativeContents": [],
            }
            if any(
                same_similar_account(candidate, existing)
                for existing in effective_similar_accounts(record)
            ):
                raise ValueError("该相似账号已存在")

            manual_accounts.append(candidate)
            record.manual_similar_accounts = manual_accounts
            record.report_version += 1
            self.session.commit()
            return self._report_from_record(record)
        except Exception:
            self.session.rollback()
            raise

    def delete_report_similar_account(
        self,
        user_id: str,
        account_id: str,
        configuration_key: str,
    ) -> Report:
        """删除人工配置；对 AI 推荐写入排除键，避免下次生成后立即恢复。"""

        try:
            self.get_account(user_id, account_id)
            record = self.session.get(ReportRecord, account_id)
            if record is None:
                raise KeyError(account_id)

            requested_key = str(configuration_key or "").strip()
            manual_accounts = [dict(item) for item in record.manual_similar_accounts or []]
            remaining_manual = [
                item for item in manual_accounts if similar_account_key(item) != requested_key
            ]
            if len(remaining_manual) != len(manual_accounts):
                record.manual_similar_accounts = remaining_manual
            else:
                generated_keys = {
                    similar_account_key(dict(item))
                    for item in record.similar_accounts or []
                }
                if requested_key not in generated_keys:
                    raise KeyError(requested_key)
                excluded = list(dict.fromkeys(record.excluded_similar_account_keys or []))
                if requested_key not in excluded:
                    excluded.append(requested_key)
                record.excluded_similar_account_keys = excluded

            record.report_version += 1
            self.session.commit()
            return self._report_from_record(record)
        except Exception:
            self.session.rollback()
            raise

    def replace_structured_report(self, user_id: str, account_id: str, payload: dict[str, Any]) -> Report:
        try:
            self.get_account(user_id, account_id)
            record = self.session.get(ReportRecord, account_id)
            if record is None:
                raise KeyError(account_id)

            text_values = {column: payload[key] for key, column in REPORT_SECTION_COLUMNS.items()}
            structured_values = {column: payload[key] for key, column in STRUCTURED_REPORT_COLUMNS.items()}

            for column, value in text_values.items():
                setattr(record, column, value)
            for column, value in structured_values.items():
                setattr(record, column, value)
            # 旧列暂时保留以兼容现有数据库结构，但新报告不再保存已下线板块。
            record.top_bloggers = ""
            record.top_blogger_details = []
            record.content_strategy = {}
            record.report_version += 1
            record.generated_at = datetime.now(UTC)
            self.session.commit()
            return self._report_from_record(record)
        except Exception:
            self.session.rollback()
            raise

    def update_structured_report_sections(
        self,
        user_id: str,
        account_id: str,
        payload: dict[str, Any],
    ) -> Report:
        """原子合并一个或多个结构化报告板块，不清空未包含的板块。"""

        allowed_keys = {
            "similarAccounts",
            "complianceRules",
            "targetUserProfile",
            "hotContents",
            "sourceMeta",
            "competitors",
            "prohibitedWords",
            "targetUsers",
            "hotContent",
        }
        unknown_keys = set(payload) - allowed_keys
        if unknown_keys:
            raise ValueError(f"不支持更新账号报告字段：{sorted(unknown_keys)}")
        if not (set(payload) & {"similarAccounts", "complianceRules", "targetUserProfile", "hotContents"}):
            raise ValueError("账号报告板块更新不能为空")

        try:
            self.get_account(user_id, account_id)
            record = self.session.scalar(
                select(ReportRecord)
                .where(ReportRecord.account_id == account_id)
                .with_for_update()
            )
            if record is None:
                raise KeyError(account_id)
            for key, column in REPORT_SECTION_COLUMNS.items():
                if key in payload:
                    setattr(record, column, payload[key])
            for key, column in STRUCTURED_REPORT_COLUMNS.items():
                if key in payload:
                    setattr(record, column, payload[key])
            record.report_version += 1
            record.generated_at = datetime.now(UTC)
            self.session.commit()
            return self._report_from_record(record)
        except Exception:
            self.session.rollback()
            raise

    def update_report_section(self, user_id: str, account_id: str, section_key: str, content: str) -> Report:
        self.get_account(user_id, account_id)
        column = REPORT_SECTION_COLUMNS[section_key]
        record = self.session.get(ReportRecord, account_id)
        if record is None:
            raise KeyError(account_id)
        setattr(record, column, content)
        self.session.commit()
        return self.get_report(user_id, account_id)
