from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _dotenv(path: str | Path) -> dict[str, str]:
    target = Path(path)
    if not target.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in target.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@dataclass(frozen=True, slots=True)
class GatewayServerConfig:
    host: str = "127.0.0.1"
    port: int = 8080
    database: Path = Path("adapter_gateway_data/gateway.sqlite3")
    im_grpc_target: str = ""
    im_grpc_tls: bool = False
    im_grpc_timeout_seconds: float = 10.0
    activation_limit: int = 10
    activation_window_seconds: int = 600

    @classmethod
    def load(cls, dotenv: str | Path = ".env.server") -> "GatewayServerConfig":
        values = _dotenv(dotenv)

        def get(name: str, default: str = "") -> str:
            return os.environ.get(name, values.get(name, default)).strip()

        def boolean(name: str, default: bool) -> bool:
            return get(name, "true" if default else "false").lower() in {"1", "true", "yes", "on"}

        return cls(
            host=get("ADAPTER_GATEWAY_HOST", "127.0.0.1"),
            port=int(get("ADAPTER_GATEWAY_PORT", "8080")),
            database=Path(get("ADAPTER_GATEWAY_DB", "adapter_gateway_data/gateway.sqlite3")),
            im_grpc_target=get("IM_GRPC_TARGET"),
            im_grpc_tls=boolean("IM_GRPC_TLS", False),
            im_grpc_timeout_seconds=float(get("IM_GRPC_TIMEOUT_SECONDS", "10")),
            activation_limit=int(get("ADAPTER_GATEWAY_ACTIVATION_LIMIT", "10")),
            activation_window_seconds=int(get("ADAPTER_GATEWAY_ACTIVATION_WINDOW_SECONDS", "600")),
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.im_grpc_target:
            errors.append("IM_GRPC_TARGET is required")
        if not 1 <= self.port <= 65535:
            errors.append("ADAPTER_GATEWAY_PORT must be between 1 and 65535")
        if self.im_grpc_timeout_seconds <= 0:
            errors.append("IM_GRPC_TIMEOUT_SECONDS must be positive")
        if self.activation_limit <= 0:
            errors.append("ADAPTER_GATEWAY_ACTIVATION_LIMIT must be positive")
        if self.activation_window_seconds <= 0:
            errors.append("ADAPTER_GATEWAY_ACTIVATION_WINDOW_SECONDS must be positive")
        return errors
