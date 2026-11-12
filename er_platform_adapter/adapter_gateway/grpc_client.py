from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
import logging
from typing import Any, Protocol
import uuid

import grpc
from google.protobuf.json_format import MessageToDict

from .config import GatewayServerConfig
from .proto import im_pb2, im_pb2_grpc

logger = logging.getLogger(__name__)


class IMCallError(RuntimeError):
    def __init__(self, operation: str, code: str, *, retryable: bool):
        super().__init__(f"IM {operation} failed ({code})")
        self.operation = operation
        self.code = code
        self.retryable = retryable


class IMClient(Protocol):
    async def ready(self, timeout: float = 2.0) -> bool: ...

    async def ensure_actor(self, account: dict[str, Any], activation_code: str) -> dict[str, Any]: ...

    async def ensure_audience(self, account: dict[str, Any]) -> dict[str, Any]: ...

    async def close(self) -> None: ...


def _as_dict(message: Any) -> dict[str, Any]:
    return MessageToDict(message, preserving_proto_field_name=False)


_SENSITIVE_LOG_KEYS = (
    "activationcode",
    "cookie",
    "ticket",
    "privatekey",
    "clientcert",
    "tssign",
    "authorization",
    "password",
    "sessionid",
    "accesskey",
)


def _redact_log_value(value: Any, *, field_name: str = "") -> Any:
    normalized = field_name.lower().replace("_", "").replace("-", "")
    if any(marker in normalized for marker in _SENSITIVE_LOG_KEYS):
        return "<redacted>"
    if isinstance(value, dict):
        return {key: _redact_log_value(item, field_name=str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_log_value(item) for item in value]
    if field_name.lower() == "profile" and isinstance(value, str):
        try:
            profile = json.loads(value)
        except (TypeError, ValueError):
            return value
        return json.dumps(_redact_log_value(profile), ensure_ascii=False, separators=(",", ":"))
    return value


def _request_for_log(message: Any) -> dict[str, Any]:
    payload = MessageToDict(
        message,
        preserving_proto_field_name=False,
        always_print_fields_with_no_presence=True,
    )
    return _redact_log_value(payload)


class IMGrpcClient:
    """Narrow, typed client for the IM RPCs exposed by the public gateway."""

    def __init__(self, config: GatewayServerConfig):
        self.config = config
        self._channel: grpc.aio.Channel | None = None
        self._stub: Any = None
        self._locks: dict[tuple[str, str, str], asyncio.Lock] = {}

    def _connect(self) -> Any:
        if self._stub is not None:
            return self._stub
        if self.config.im_grpc_tls:
            self._channel = grpc.aio.secure_channel(
                self.config.im_grpc_target,
                grpc.ssl_channel_credentials(),
            )
        else:
            self._channel = grpc.aio.insecure_channel(self.config.im_grpc_target)
        self._stub = im_pb2_grpc.csStub(self._channel)
        return self._stub

    async def ready(self, timeout: float = 2.0) -> bool:
        self._connect()
        assert self._channel is not None
        try:
            await asyncio.wait_for(self._channel.channel_ready(), timeout=max(0.1, timeout))
            return True
        except (asyncio.TimeoutError, grpc.RpcError):
            return False

    @staticmethod
    def _operation_id() -> str:
        return f"adapter_gateway_{uuid.uuid4().hex}"

    async def _call(
        self,
        operation: str,
        call: Callable[..., Awaitable[Any]],
        request: Any,
        *,
        missing_is_none: bool = False,
    ) -> Any | None:
        operation_id = self._operation_id()
        request_json = json.dumps(
            _request_for_log(request),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        logger.info(
            "IM gRPC request target=%s operation=%s operationid=%s payload=%s",
            self.config.im_grpc_target,
            operation,
            operation_id,
            request_json,
        )
        try:
            return await call(
                request,
                timeout=self.config.im_grpc_timeout_seconds,
                metadata=(("operationid", operation_id),),
            )
        except grpc.aio.AioRpcError as exc:
            code = exc.code()
            if missing_is_none and code == grpc.StatusCode.NOT_FOUND:
                return None
            retryable = code in {
                grpc.StatusCode.CANCELLED,
                grpc.StatusCode.DEADLINE_EXCEEDED,
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                grpc.StatusCode.ABORTED,
                grpc.StatusCode.INTERNAL,
                grpc.StatusCode.UNAVAILABLE,
            }
            raise IMCallError(operation, code.name, retryable=retryable) from exc

    def _lock_for(self, kind: str, platform: str, platform_id: str) -> asyncio.Lock:
        key = (kind, platform, platform_id)
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()
        return lock

    async def ensure_actor(self, account: dict[str, Any], activation_code: str) -> dict[str, Any]:
        platform = str(account["platform"])
        platform_actor_id = str(account["platform_actor_id"])
        stub = self._connect()
        async with self._lock_for("actor", platform, platform_actor_id):
            response = await self._call(
                "ActorGetAccount",
                stub.ActorGetAccount,
                im_pb2.ActorGetAccountReq(
                    platform=platform,
                    actor_platform_id=platform_actor_id,
                ),
                missing_is_none=True,
            )
            if response is not None and (response.HasField("actor") or response.HasField("account")):
                return _as_dict(response)

            response = await self._call(
                "ActorAddAccount",
                stub.ActorAddAccount,
                im_pb2.ActorAddAccountReq(
                    actor_id=platform_actor_id,
                    shop_name="",
                    business_domain="default",
                    activation_code=activation_code,
                    platform=platform,
                    openim_id="",
                    nickname=str(account.get("nickname") or platform_actor_id),
                    avatar_url=str(account.get("avatar_url") or ""),
                    profile=json.dumps(account.get("profile") or {}, ensure_ascii=False, separators=(",", ":")),
                    status="enable",
                ),
            )
            return _as_dict(response)

    async def ensure_audience(self, account: dict[str, Any]) -> dict[str, Any]:
        platform = str(account["platform"])
        platform_actor_id = str(account["platform_actor_id"])
        platform_audience_id = str(account["platform_audience_id"])
        stub = self._connect()
        async with self._lock_for("audience", platform, platform_audience_id):
            try:
                response = await self._call(
                    "AudienceGetAccount",
                    stub.AudienceGetAccount,
                    im_pb2.AudienceGetAccountReq(
                        platform=platform,
                        audience_platform_id=platform_audience_id,
                        actor_platform_id=platform_actor_id,
                    ),
                    missing_is_none=True,
                )
            except IMCallError as exc:
                if exc.operation != "AudienceGetAccount" or exc.code != "INVALID_ARGUMENT":
                    raise
                # The deployed IM currently returns INVALID_ARGUMENT for some
                # absent Audience lookups instead of the documented NOT_FOUND.
                # Only this exact compatibility case may fall through to Add.
                logger.warning(
                    "Audience lookup returned INVALID_ARGUMENT; trying create "
                    "platform=%s platform_audience_id=%s",
                    platform,
                    platform_audience_id,
                )
                response = None
            if response is not None and response.HasField("account"):
                return {"account": _as_dict(response.account), "created": False}

            response = await self._call(
                "AudienceAddAccount",
                stub.AudienceAddAccount,
                im_pb2.AudienceAddAccountReq(
                    actor_platform_id=platform_actor_id,
                    audience_platform_id=platform_audience_id,
                    platform=platform,
                    nickname=str(account.get("nickname") or platform_audience_id),
                    avatar_url=str(account.get("avatar_url") or ""),
                    profile=json.dumps(account.get("profile") or {}, ensure_ascii=False, separators=(",", ":")),
                    status="enable",
                ),
            )
            return {
                "account": {
                    "audiencePlatformID": platform_audience_id,
                    "platform": platform,
                    "nickname": str(account.get("nickname") or platform_audience_id),
                    "avatarURL": str(account.get("avatar_url") or ""),
                    "profile": json.dumps(account.get("profile") or {}, ensure_ascii=False, separators=(",", ":")),
                    "status": "enable",
                },
                "session": _as_dict(response.session) if response.HasField("session") else {},
                "created": bool(response.is_new_session),
            }

    async def close(self) -> None:
        if self._channel is not None:
            await self._channel.close()
            self._channel = None
            self._stub = None
