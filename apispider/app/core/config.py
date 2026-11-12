from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BASE_DIR / ".env"
PARENT_CHECKOUT_ENV_FILE = BASE_DIR.parent.parent / ".env" if BASE_DIR.parent.name == ".worktrees" else BASE_DIR / ".env"
ENV_FILES = tuple(dict.fromkeys([str(PARENT_CHECKOUT_ENV_FILE), str(ENV_FILE)]))

_MEDIASPIDER_PLATFORMS = frozenset({"xhs", "dy", "ks"})


class Settings(BaseSettings):
    app_name: str = "StarX Backend"
    api_prefix: str = "/api/v1"
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    database_url: str = Field(
        default="postgresql+psycopg://starx:starx@localhost:5432/starx"
    )
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800
    db_pool_pre_ping: bool = True
    db_search_path: str = "public"
    redis_url: str = "redis://localhost:6379/0"
    object_storage_provider: str = Field(
        default="minio",
        validation_alias=AliasChoices("STARX_OBJECT_STORAGE_PROVIDER", "OSS_PROVIDER"),
    )
    object_storage_endpoint: str = Field(
        default="localhost:9000",
        validation_alias=AliasChoices("STARX_OBJECT_STORAGE_ENDPOINT", "OSS_ENDPOINT"),
    )
    object_storage_public_base_url: str = Field(
        default="http://localhost:9000",
        validation_alias=AliasChoices("STARX_OBJECT_STORAGE_PUBLIC_BASE_URL", "OSS_PUBLIC_BASE_URL"),
    )
    object_storage_access_key: str = Field(
        default="starx",
        validation_alias=AliasChoices("STARX_OBJECT_STORAGE_ACCESS_KEY", "OSS_ACCESS_KEY_ID"),
    )
    object_storage_secret_key: str = Field(
        default="starx123",
        validation_alias=AliasChoices("STARX_OBJECT_STORAGE_SECRET_KEY", "OSS_ACCESS_KEY_SECRET"),
    )
    object_storage_bucket: str = Field(
        default="starx-assets",
        validation_alias=AliasChoices("STARX_OBJECT_STORAGE_BUCKET", "OSS_BUCKET"),
    )
    object_storage_secure: bool = Field(
        default=False,
        validation_alias=AliasChoices("STARX_OBJECT_STORAGE_SECURE", "OSS_SECURE"),
    )
    object_storage_region: str = Field(
        default="",
        validation_alias=AliasChoices("STARX_OBJECT_STORAGE_REGION", "OSS_REGION"),
    )
    object_storage_upload_dir: str = Field(
        default="",
        validation_alias=AliasChoices("STARX_OBJECT_STORAGE_UPLOAD_DIR", "OSS_UPLOAD_DIR"),
    )
    object_storage_use_cname: bool = Field(
        default=False,
        validation_alias=AliasChoices("STARX_OBJECT_STORAGE_USE_CNAME", "OSS_USE_CNAME"),
    )
    model_config = SettingsConfigDict(
        env_prefix="STARX_",
        extra="ignore",
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
    )
    # ai
    DEFAULT_LLM_MODEL: str = Field(
        default="qwen-plus",
        validation_alias=AliasChoices("STARX_DEFAULT_LLM_MODEL", "DEFAULT_LLM_MODEL"),
    )
    DEFAULT_IMAGE_DISCERN_MODEL: str = Field(
        default="qwen3-vl-plus",
        validation_alias=AliasChoices("STARX_DEFAULT_IMAGE_DISCERN_MODEL", "DEFAULT_IMAGE_DISCERN_MODEL"),
    )
    DEFAULT_IMAGE_GENERATE_MODEL: str = Field(
        default="gpt-image-2",
        validation_alias=AliasChoices("STARX_DEFAULT_IMAGE_GENERATE_MODEL", "DEFAULT_IMAGE_GENERATE_MODEL"),
    )
    DEFAULT_VIDEO_DISCERN_MODEL: str = Field(
        default="qwen3-vl-plus",
        validation_alias=AliasChoices("STARX_DEFAULT_VIDEO_DISCERN_MODEL", "DEFAULT_VIDEO_DISCERN_MODEL"),
    )
    
    DEFAULT_VOICE_GENERATE_MODEL: str = Field(
        default="speech-02-hd",
        validation_alias=AliasChoices("STARX_DEFAULT_VOICE_GENERATE_MODEL", "DEFAULT_VOICE_GENERATE_MODEL"),
    )
    DEFAULT_VOICE_DISCERN_MODEL: str = Field(
        default="qwen3-asr-flash",
        validation_alias=AliasChoices("STARX_DEFAULT_VOICE_DISCERN_MODEL", "DEFAULT_VOICE_DISCERN_MODEL"),
    )

    DEFAULT_BASE_URL: str = Field(
        default="https://lingyao.world",
        validation_alias=AliasChoices("STARX_DEFAULT_BASE_URL", "DEFAULT_BASE_URL", "AI_BASE_URL", "OPENAI_BASE_URL"),
    )
    DEFAULT_TOKEN: str = Field(
        default="",
        validation_alias=AliasChoices(
            "STARX_DEFAULT_TOKEN",
            "DEFAULT_TOKEN",
            "AI_API_TOKEN",
            "OPENAI_API_KEY",
            "DASHSCOPE_API_KEY",
            "LINGYAO_API_TOKEN",
        ),
    )
    DEFAULT_TIMEOUT: int = Field(
        default=360,
        validation_alias=AliasChoices("STARX_DEFAULT_TIMEOUT", "DEFAULT_TIMEOUT"),
    )
    DEFAULT_IMAGE_GENERATION_TIMEOUT: int = Field(
        default=360,
        validation_alias=AliasChoices("STARX_DEFAULT_IMAGE_GENERATION_TIMEOUT", "IMAGE_GENERATION_TIMEOUT"),
    )
    DEFAULT_REMOTE_EMBEDDING_MODEL: str = Field(
        default="text-embedding-3-large",
        validation_alias=AliasChoices("STARX_DEFAULT_REMOTE_EMBEDDING_MODEL", "DEFAULT_REMOTE_EMBEDDING_MODEL"),
    )
    DEFAULT_OLLAMA_BASE_URL: str = Field(
        default="http://localhost:11434",
        validation_alias=AliasChoices("STARX_DEFAULT_OLLAMA_BASE_URL", "DEFAULT_OLLAMA_BASE_URL", "OLLAMA_BASE_URL"),
    )
    DEFAULT_LOCAL_EMBEDDING_MODEL: str = Field(
        default="qwen3-embedding:8b",
        validation_alias=AliasChoices("STARX_DEFAULT_LOCAL_EMBEDDING_MODEL", "DEFAULT_LOCAL_EMBEDDING_MODEL", "LOCAL_EMBEDDING_MODEL"),
    )

    image_generation_sub_job_concurrency: int = Field(
        default=5,
        validation_alias=AliasChoices("STARX_IMAGE_GENERATION_SUB_JOB_CONCURRENCY", "IMAGE_GENERATION_SUB_JOB_CONCURRENCY"),
    )   
    autophone_base_url: str = Field(
        default="http://autophone.lingyao.info",
        validation_alias=AliasChoices("STARX_AUTOPHONE_BASE_URL", "AUTOPHONE_BASE_URL"),
    )
    autophone_client_id: str = Field(
        default="",
        validation_alias=AliasChoices("STARX_AUTOPHONE_CLIENT_ID", "AUTOPHONE_CLIENT_ID"),
    )
    autophone_client_secret: str = Field(
        default="",
        validation_alias=AliasChoices("STARX_AUTOPHONE_CLIENT_SECRET", "AUTOPHONE_CLIENT_SECRET"),
    )
    autophone_timeout: int = Field(
        default=30,
        validation_alias=AliasChoices("STARX_AUTOPHONE_TIMEOUT", "AUTOPHONE_TIMEOUT"),
    )
    doubao_search_api_url: str = Field(
        default="https://open.feedcoopapi.com/search_api/web_search",
        validation_alias=AliasChoices("STARX_DOUBAO_SEARCH_API_URL", "DOUBAO_SEARCH_API_URL"),
    )
    doubao_search_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("STARX_DOUBAO_SEARCH_API_KEY", "DOUBAO_SEARCH_API_KEY"),
    )
    doubao_search_timeout: int = Field(
        default=30,
        validation_alias=AliasChoices("STARX_DOUBAO_SEARCH_TIMEOUT", "DOUBAO_SEARCH_TIMEOUT"),
    )
    redfox_base_url: str = Field(
        default="https://redfox.hk",
        validation_alias=AliasChoices("STARX_REDFOX_BASE_URL", "REDFOX_BASE_URL"),
    )
    redfox_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("STARX_REDFOX_API_KEY", "REDFOX_API_KEY"),
    )
    redfox_timeout: int = Field(
        default=30,
        validation_alias=AliasChoices("STARX_REDFOX_TIMEOUT", "REDFOX_TIMEOUT"),
    )
    tikhub_base_url: str = Field(
        default="https://api.tikhub.io",
        validation_alias=AliasChoices("STARX_TIKHUB_BASE_URL", "TIKHUB_BASE_URL"),
    )
    tikhub_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("STARX_TIKHUB_API_KEY", "TIKHUB_API_KEY"),
    )
    tikhub_timeout: int = Field(
        default=30,
        validation_alias=AliasChoices("STARX_TIKHUB_TIMEOUT", "TIKHUB_TIMEOUT"),
    )
    tikhub_max_retries: int = Field(
        default=3,
        validation_alias=AliasChoices(
            "STARX_TIKHUB_MAX_RETRIES",
            "TIKHUB_MAX_RETRIES",
        ),
    )
    social_retrieval_provider: str = Field(
        default="tikhub",
        validation_alias=AliasChoices(
            "STARX_SOCIAL_RETRIEVAL_PROVIDER",
            "SOCIAL_RETRIEVAL_PROVIDER",
        ),
    )
    tikhub_max_in_flight: int = Field(
        default=16,
        ge=1,
        le=100,
        validation_alias=AliasChoices(
            "STARX_TIKHUB_MAX_IN_FLIGHT",
            "TIKHUB_MAX_IN_FLIGHT",
        ),
    )
    tikhub_qps: int = Field(
        default=8,
        ge=1,
        le=10,
        validation_alias=AliasChoices("STARX_TIKHUB_QPS", "TIKHUB_QPS"),
    )
    workflow_max_concurrent: int = Field(
        default=3,
        validation_alias=AliasChoices("STARX_WORKFLOW_MAX_CONCURRENT", "WORKFLOW_MAX_CONCURRENT"),
    )
    COMPETITOR_REFRESH_INTERVAL_SECONDS: int = Field(default=21600, ge=60)
    COMPETITOR_SCHEDULER_SCAN_SECONDS: int = Field(default=60, ge=1)
    COMPETITOR_SCHEDULER_BATCH_SIZE: int = Field(default=20, ge=1, le=100)
    COMPETITOR_WORKFLOW_STALE_SECONDS: int = Field(default=7200, ge=300)
    COMPETITOR_WORKFLOW_HEARTBEAT_SECONDS: int = Field(default=60, ge=10)
    COMPETITOR_CRAWL_MAX_ATTEMPTS: int = Field(default=3, ge=1, le=5)
    COMPETITOR_CRAWL_RETRY_BACKOFF_SECONDS: float = Field(default=1.0, ge=0, le=30)
    max_upload_image_bytes: int = Field(
        default=10 * 1024 * 1024,
        validation_alias=AliasChoices("STARX_MAX_UPLOAD_IMAGE_BYTES", "MAX_UPLOAD_IMAGE_BYTES"),
    )
    max_extract_media_bytes: int = Field(
        default=80 * 1024 * 1024,
        validation_alias=AliasChoices("STARX_MAX_EXTRACT_MEDIA_BYTES", "MAX_EXTRACT_MEDIA_BYTES"),
    )
    max_extract_media_items: int = Field(
        default=12,
        validation_alias=AliasChoices("STARX_MAX_EXTRACT_MEDIA_ITEMS", "MAX_EXTRACT_MEDIA_ITEMS"),
    )
    max_generated_image_bytes: int = Field(
        default=25 * 1024 * 1024,
        validation_alias=AliasChoices("STARX_MAX_GENERATED_IMAGE_BYTES", "MAX_GENERATED_IMAGE_BYTES"),
    )
    MEDIASPIDER_HEADLESS: bool = True
    MEDIASPIDER_ENABLE_CDP_MODE: bool = False
    MEDIASPIDER_CDP_CONNECT_EXISTING: bool = False
    MEDIASPIDER_CDP_DEBUG_PORT: int = 9222
    MEDIASPIDER_CUSTOM_BROWSER_PATH: str = ""
    MEDIASPIDER_MAX_NOTES_COUNT: int = 30
    MEDIASPIDER_MAX_COMMENTS_COUNT: int = 20
    MEDIASPIDER_MAX_CONCURRENCY: int = 3
    ACCOUNT_REPORT_MAX_NOTES_PER_KEYWORD: int = Field(default=10, ge=1)
    MEDIASPIDER_ENABLE_COMMENTS: bool = True
    MEDIASPIDER_ENABLE_SUB_COMMENTS: bool = False
    MEDIASPIDER_ENABLE_IP_PROXY: bool = False
    MEDIASPIDER_IP_PROXY_PROVIDER: str = "kuaidaili"
    MEDIASPIDER_STATIC_PROXY_URL: str = ""

    @model_validator(mode="after")
    def _derive_object_storage_settings(self) -> "Settings":
        self.object_storage_provider = self.object_storage_provider.lower()

        if (
            self.object_storage_provider == "minio"
            and (
                self.object_storage_region
                or self.object_storage_use_cname
                or self.object_storage_endpoint != "localhost:9000"
            )
        ):
            self.object_storage_provider = "oss"

        if self.object_storage_provider == "oss" and not self.object_storage_secure:
            self.object_storage_secure = True

        if (
            self.object_storage_public_base_url == "http://localhost:9000"
            and self.object_storage_endpoint != "localhost:9000"
        ):
            scheme = "https" if self.object_storage_secure else "http"
            self.object_storage_public_base_url = f"{scheme}://{self.object_storage_endpoint}"

        self.object_storage_upload_dir = self.object_storage_upload_dir.strip("/")
        self.image_generation_sub_job_concurrency = max(int(self.image_generation_sub_job_concurrency or 1), 1)
        self.workflow_max_concurrent = max(int(self.workflow_max_concurrent or 1), 1)
        if self.COMPETITOR_WORKFLOW_HEARTBEAT_SECONDS * 3 > self.COMPETITOR_WORKFLOW_STALE_SECONDS:
            raise ValueError(
                "COMPETITOR_WORKFLOW_HEARTBEAT_SECONDS must not exceed one third of COMPETITOR_WORKFLOW_STALE_SECONDS"
            )
        self.max_upload_image_bytes = max(int(self.max_upload_image_bytes or 1), 1)
        self.max_extract_media_bytes = max(int(self.max_extract_media_bytes or 1), 1)
        self.max_extract_media_items = max(int(self.max_extract_media_items or 1), 1)
        self.max_generated_image_bytes = max(int(self.max_generated_image_bytes or 1), 1)
        self.autophone_base_url = self.autophone_base_url.rstrip("/")
        self.autophone_timeout = max(int(self.autophone_timeout or 1), 1)
        self.doubao_search_api_url = self.doubao_search_api_url.strip()
        self.doubao_search_timeout = max(int(self.doubao_search_timeout or 1), 1)
        self.redfox_base_url = self.redfox_base_url.rstrip("/")
        self.redfox_timeout = max(int(self.redfox_timeout or 1), 1)
        self.tikhub_base_url = self.tikhub_base_url.rstrip("/")
        self.tikhub_timeout = max(int(self.tikhub_timeout or 1), 1)
        self.tikhub_max_retries = max(int(self.tikhub_max_retries or 0), 0)
        self.social_retrieval_provider = str(
            self.social_retrieval_provider or "tikhub"
        ).strip().lower()
        if self.social_retrieval_provider not in {"tikhub", "legacy"}:
            self.social_retrieval_provider = "tikhub"
        return self



    @property
    def sync_database_url(self) -> str:
        if self.database_url.startswith("postgresql+asyncpg://"):
            return self.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
        return self.database_url

    def mediaspider_runtime_options(self, platform: str) -> dict[str, object]:
        if platform not in _MEDIASPIDER_PLATFORMS:
            raise ValueError(f"unsupported MediaSpider platform: {platform}")

        return {
            "headless": self.MEDIASPIDER_HEADLESS,
            "max_notes_count": self.MEDIASPIDER_MAX_NOTES_COUNT,
            "max_comments_count": self.MEDIASPIDER_MAX_COMMENTS_COUNT,
            "max_concurrency": self.MEDIASPIDER_MAX_CONCURRENCY,
            "enable_comments": self.MEDIASPIDER_ENABLE_COMMENTS,
            "enable_sub_comments": self.MEDIASPIDER_ENABLE_SUB_COMMENTS,
            "enable_cdp_mode": self.MEDIASPIDER_ENABLE_CDP_MODE,
            "cdp_connect_existing": self.MEDIASPIDER_CDP_CONNECT_EXISTING,
            "cdp_debug_port": self.MEDIASPIDER_CDP_DEBUG_PORT,
            "custom_browser_path": self.MEDIASPIDER_CUSTOM_BROWSER_PATH,
            "enable_ip_proxy": self.MEDIASPIDER_ENABLE_IP_PROXY,
            "ip_proxy_provider": self.MEDIASPIDER_IP_PROXY_PROVIDER,
            "static_proxy_url": self.MEDIASPIDER_STATIC_PROXY_URL,
        }


settings = Settings()
