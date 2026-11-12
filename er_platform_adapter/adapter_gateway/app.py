from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager
import logging
import time
from typing import Any, Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from .config import GatewayServerConfig
from .grpc_client import IMCallError, IMClient, IMGrpcClient
from .store import DeviceOwnershipError, GatewayStore

logger = logging.getLogger(__name__)


class PlatformAccountInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str = Field(pattern="^(boss|douyin|rednote|wechat|wecom)$")
    platform_actor_id: str = Field(min_length=1, max_length=256)
    nickname: str = Field(default="", max_length=256)
    avatar_url: str = Field(default="", max_length=4096)
    profile: dict[str, Any] = Field(default_factory=dict)


class ActivationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: UUID
    activation_code: SecretStr = Field(min_length=4, max_length=256)
    accounts: list[PlatformAccountInput] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def unique_platforms(self) -> "ActivationInput":
        keys = {(item.platform, item.platform_actor_id) for item in self.accounts}
        platforms = {item.platform for item in self.accounts}
        if len(keys) != len(self.accounts) or len(platforms) != len(self.accounts):
            raise ValueError("accounts must contain at most one unique UID per platform")
        return self


class AudienceEnsureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str = Field(pattern="^(boss|douyin|rednote|wechat|wecom)$")
    platform_actor_id: str = Field(min_length=1, max_length=256)
    platform_audience_id: str = Field(min_length=1, max_length=256)
    nickname: str = Field(default="", max_length=256)
    avatar_url: str = Field(default="", max_length=4096)
    profile: dict[str, Any] = Field(default_factory=dict)


class ActivationLimiter:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, source: str) -> None:
        now = time.monotonic()
        async with self._lock:
            attempts = self._attempts[source]
            while attempts and attempts[0] <= now - self.window_seconds:
                attempts.popleft()
            if len(attempts) >= self.limit:
                raise HTTPException(status_code=429, detail="too_many_activation_attempts")
            attempts.append(now)


def _account_registration(source: PlatformAccountInput, result: dict[str, Any]) -> dict[str, str]:
    actor = result.get("actor") if isinstance(result.get("actor"), dict) else {}
    account = result.get("account") if isinstance(result.get("account"), dict) else {}
    actor_id = str(actor.get("actorID") or account.get("actorID") or source.platform_actor_id)
    return {
        "platform": source.platform,
        "platform_actor_id": source.platform_actor_id,
        "actor_id": actor_id,
        "openim_id": str(account.get("openIMID") or ""),
    }


def create_app(
    config: GatewayServerConfig,
    *,
    im_client: IMClient | None = None,
    store: GatewayStore | None = None,
) -> FastAPI:
    errors = config.validate()
    if errors:
        raise ValueError("; ".join(errors))
    owns_im_client = im_client is None
    owns_store = store is None
    im = im_client or IMGrpcClient(config)
    registry = store or GatewayStore(config.database)
    limiter = ActivationLimiter(config.activation_limit, config.activation_window_seconds)
    started_at = time.monotonic()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            if owns_im_client:
                await im.close()
            if owns_store:
                await asyncio.to_thread(registry.close)

    app = FastAPI(
        title="Adapter Control Gateway",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_boundary(request: Request, call_next):
        request_id = uuid4().hex
        try:
            content_length = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "invalid_content_length"})
        if content_length > 65_536:
            return JSONResponse(status_code=413, content={"error": "request_too_large"})
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("gateway request failed request_id=%s path=%s", request_id, request.url.path)
            return JSONResponse(status_code=500, content={"error": "internal_error", "request_id": request_id})
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(DeviceOwnershipError)
    async def ownership_error(_: Request, exc: DeviceOwnershipError):
        return JSONResponse(status_code=409, content={"error": str(exc)})

    @app.exception_handler(IMCallError)
    async def im_error(request: Request, exc: IMCallError):
        status = 503 if exc.retryable else 502
        logger.warning(
            "IM gRPC call failed path=%s operation=%s grpc_code=%s retryable=%s",
            request.url.path,
            exc.operation,
            exc.code,
            exc.retryable,
        )
        return JSONResponse(
            status_code=status,
            content={
                "error": "im_unavailable" if exc.retryable else "im_rejected",
                "operation": exc.operation,
                "grpc_code": exc.code,
                "retryable": exc.retryable,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        # FastAPI's default body includes the rejected input. Strip it so an
        # invalid activation code cannot be reflected into logs or clients.
        errors = [
            {
                "type": item.get("type", "validation_error"),
                "loc": item.get("loc", ()),
                "message": item.get("msg", "invalid value"),
            }
            for item in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"error": "validation_error", "fields": errors})

    async def authenticated_device(
        authorization: Annotated[str | None, Header()] = None,
    ) -> str:
        scheme, _, token = str(authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=401, detail="missing_device_token")
        device_id = await asyncio.to_thread(registry.authenticate, token)
        if not device_id:
            raise HTTPException(status_code=401, detail="invalid_device_token")
        return device_id

    @app.get("/health/live")
    async def live() -> dict[str, Any]:
        return {"status": "live", "uptime_seconds": round(time.monotonic() - started_at, 3)}

    @app.get("/health/ready")
    async def ready() -> JSONResponse:
        available = await im.ready()
        return JSONResponse(
            status_code=200 if available else 503,
            content={"status": "ready" if available else "unavailable", "im_grpc": available},
        )

    @app.post("/v1/activate")
    async def activate(body: ActivationInput, request: Request) -> dict[str, Any]:
        source = request.client.host if request.client else "unknown"
        await limiter.check(source)
        device_id = str(body.device_id)
        account_values = [item.model_dump() for item in body.accounts]
        await asyncio.to_thread(registry.assert_claimable, device_id, account_values)
        activation_code = body.activation_code.get_secret_value()
        registrations: list[dict[str, str]] = []
        for account in body.accounts:
            result = await im.ensure_actor(account.model_dump(), activation_code)
            registrations.append(_account_registration(account, result))
        token = await asyncio.to_thread(registry.register_device, device_id, registrations)
        return {
            "device_id": device_id,
            "device_token": token,
            "accounts": registrations,
        }

    @app.post("/v1/audiences/ensure")
    async def ensure_audience(
        body: AudienceEnsureInput,
        device_id: str = Depends(authenticated_device),
    ) -> dict[str, Any]:
        owns_actor = await asyncio.to_thread(
            registry.owns_actor,
            device_id,
            body.platform,
            body.platform_actor_id,
        )
        if not owns_actor:
            raise HTTPException(status_code=403, detail="actor_not_owned_by_device")
        return await im.ensure_audience(body.model_dump())

    return app
