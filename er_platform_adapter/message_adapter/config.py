from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

def _load_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _safe_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "")).strip("._")
    return normalized[:48] or "adapter"


@dataclass(frozen=True, slots=True)
class AdapterConfig:
    platform: str
    rabbitmq_host: str
    rabbitmq_user: str
    rabbitmq_password: str
    state_db: Path
    credential_db: Path = Path("adapter_data/credentials.sqlite3")
    browser_profile_root: Path = Path("adapter_data/profiles")
    legacy_state_dbs: tuple[Path, ...] = ()
    rabbitmq_port: int = 5672
    rabbitmq_vhost: str = "/"
    edge_queue: str = "edge2im_messages"
    receive_exchange: str = "im2edge.events"
    receive_exchange_type: str = "topic"
    receive_routing_key: str = "im2edge_messages"
    receive_queue_prefix: str = "im2edge_messages.adapter"
    send_status_success: int = 0
    send_status_failed: int = 1
    prefetch_count: int = 1
    message_ttl_ms: int = 604_800_000
    single_active_consumer: bool = True
    send_min_interval_seconds: float = 4.0
    send_jitter_seconds: float = 4.0
    send_max_per_minute: int = 8
    send_max_per_hour: int = 120
    control_gateway_url: str = ""
    control_gateway_timeout_seconds: float = 15.0
    control_gateway_allow_insecure_http: bool = False

    @classmethod
    def load(
        cls,
        *,
        platform: str = "",
        dotenv: str = ".env",
        data_root: Path | str | None = None,
    ) -> "AdapterConfig":
        values = _load_dotenv(Path(dotenv))

        def get(name: str, default: str = "") -> str:
            return os.environ.get(name, values.get(name, default)).strip()

        def integer(name: str, default: int) -> int:
            return int(get(name, str(default)))

        def floating(name: str, default: float) -> float:
            return float(get(name, str(default)))

        def boolean(name: str, default: bool) -> bool:
            raw = get(name, "true" if default else "false").lower()
            return raw in {"1", "true", "yes", "on"}

        selected_platform = (platform or get("ADAPTER_PLATFORM")).strip().lower()
        platform_name = selected_platform or "adapter"
        platform_prefix = platform_name.upper()

        def platform_integer(name: str, default: int) -> int:
            global_value = integer(f"ADAPTER_{name}", default)
            return integer(f"{platform_prefix}_{name}", global_value)

        def platform_float(name: str, default: float) -> float:
            global_value = floating(f"ADAPTER_{name}", default)
            return floating(f"{platform_prefix}_{name}", global_value)

        if data_root is None:
            from message_adapter.workspaces import active_workspace_root

            selected_root = active_workspace_root() or Path("adapter_data")
        else:
            selected_root = Path(data_root)
        db_default = str(selected_root / f"{platform_name}.sqlite3")
        return cls(
            platform=selected_platform,
            rabbitmq_host=get("RABBITMQ_HOST"),
            rabbitmq_user=get("RABBITMQ_USER"),
            rabbitmq_password=get("RABBITMQ_PASSWORD"),
            rabbitmq_port=integer("RABBITMQ_PORT", 5672),
            rabbitmq_vhost=get("RABBITMQ_VHOST", "/"),
            edge_queue=get("MQ_EDGE2IM_MESSAGE_QUEUE", "edge2im_messages"),
            receive_exchange=get("IM2EDGE_RECEIVE_EXCHANGE", "im2edge.events"),
            receive_exchange_type=get("IM2EDGE_RECEIVE_EXCHANGE_TYPE", "topic"),
            receive_routing_key=get("IM2EDGE_RECEIVE_ROUTING_KEY", "im2edge_messages"),
            receive_queue_prefix=get("IM2EDGE_RECEIVE_QUEUE", "im2edge_messages") + ".adapter",
            send_status_success=integer("SEND_STATUS_SUCCESS", 0),
            send_status_failed=integer("SEND_STATUS_FAILED", 1),
            state_db=Path(db_default),
            credential_db=selected_root / "credentials.sqlite3",
            browser_profile_root=selected_root / "profiles",
            legacy_state_dbs=tuple(selected_root.glob(f"{platform_name}-*.sqlite3")),
            prefetch_count=integer("ADAPTER_PREFETCH_COUNT", 1),
            message_ttl_ms=integer("ADAPTER_MESSAGE_TTL_MS", 604_800_000),
            single_active_consumer=boolean("ADAPTER_SINGLE_ACTIVE_CONSUMER", True),
            send_min_interval_seconds=platform_float("SEND_MIN_INTERVAL_SECONDS", 4.0),
            send_jitter_seconds=platform_float("SEND_JITTER_SECONDS", 4.0),
            send_max_per_minute=platform_integer("SEND_MAX_PER_MINUTE", 8),
            send_max_per_hour=platform_integer("SEND_MAX_PER_HOUR", 120),
            control_gateway_url=get("ADAPTER_GATEWAY_URL"),
            control_gateway_timeout_seconds=floating("ADAPTER_GATEWAY_TIMEOUT_SECONDS", 15.0),
            control_gateway_allow_insecure_http=boolean("ADAPTER_GATEWAY_ALLOW_INSECURE_HTTP", False),
        )

    def validate(self, *, require_gateway: bool = True, require_send_status: bool = True) -> list[str]:
        errors: list[str] = []
        if self.platform not in {"boss", "douyin", "rednote"}:
            errors.append("ADAPTER_PLATFORM must be boss, douyin, or rednote")
        if require_gateway:
            for name, value in (
                ("RABBITMQ_HOST", self.rabbitmq_host),
                ("RABBITMQ_USER", self.rabbitmq_user),
                ("RABBITMQ_PASSWORD", self.rabbitmq_password),
                ("MQ_EDGE2IM_MESSAGE_QUEUE", self.edge_queue),
                ("IM2EDGE_RECEIVE_EXCHANGE", self.receive_exchange),
                ("IM2EDGE_RECEIVE_ROUTING_KEY", self.receive_routing_key),
            ):
                if not value:
                    errors.append(f"{name} is required")
            if not 1 <= self.rabbitmq_port <= 65535:
                errors.append("RABBITMQ_PORT must be between 1 and 65535")
            if self.receive_exchange_type != "topic":
                errors.append("IM2EDGE_RECEIVE_EXCHANGE_TYPE must be topic")
        if require_send_status and (
            self.send_status_success != 0 or self.send_status_failed != 1
        ):
            errors.append(
                "MQ 发送状态配置不兼容：请设置 "
                "SEND_STATUS_SUCCESS=0、SEND_STATUS_FAILED=1"
            )
        if self.prefetch_count <= 0:
            errors.append("ADAPTER_PREFETCH_COUNT must be positive")
        if self.message_ttl_ms <= 0:
            errors.append("ADAPTER_MESSAGE_TTL_MS must be positive")
        if self.send_min_interval_seconds <= 0:
            errors.append("SEND_MIN_INTERVAL_SECONDS must be positive")
        if self.send_jitter_seconds <= 0:
            errors.append("SEND_JITTER_SECONDS must be positive")
        if self.send_max_per_minute <= 0:
            errors.append("SEND_MAX_PER_MINUTE must be positive")
        if self.send_max_per_hour <= 0:
            errors.append("SEND_MAX_PER_HOUR must be positive")
        if self.send_max_per_hour < self.send_max_per_minute:
            errors.append("SEND_MAX_PER_HOUR cannot be lower than SEND_MAX_PER_MINUTE")
        if self.control_gateway_timeout_seconds <= 0:
            errors.append("ADAPTER_GATEWAY_TIMEOUT_SECONDS must be positive")
        if self.control_gateway_url:
            local_http = self.control_gateway_url.startswith(("http://127.0.0.1:", "http://localhost:"))
            secure = self.control_gateway_url.startswith("https://")
            explicitly_insecure = self.control_gateway_url.startswith("http://") and self.control_gateway_allow_insecure_http
            if not (secure or local_http or explicitly_insecure):
                errors.append(
                    "ADAPTER_GATEWAY_URL must use HTTPS; set "
                    "ADAPTER_GATEWAY_ALLOW_INSECURE_HTTP=true to explicitly allow remote HTTP"
                )
        return errors

    def receive_queue_name(self, platform_actor_id: str) -> str:
        digest = hashlib.sha256(f"{self.platform}:{platform_actor_id}".encode()).hexdigest()[:24]
        return f"{_safe_name(self.receive_queue_prefix)}.{self.platform}.{digest}"

    @property
    def owner_lock_path(self) -> Path:
        return self.state_db.parent / ".locks" / f"{self.platform}-worker.lock"

    @staticmethod
    def owner_lock_for(platform: str, data_dir: Path = Path("adapter_data")) -> Path:
        return data_dir / ".locks" / f"{str(platform).strip().lower()}-worker.lock"
