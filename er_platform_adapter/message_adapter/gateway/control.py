from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any
from uuid import uuid4

import httpx

from message_adapter import __version__
from message_adapter.config import AdapterConfig
from message_adapter.storage import CredentialStore


CONTROL_CREDENTIAL_SLOT = "control_gateway"
logger = logging.getLogger(__name__)


def explain_control_failure(status_code: int, body: dict[str, Any]) -> str:
    """Turn a gateway error into one sentence for the local page."""
    error = str(body.get("error") or body.get("detail") or "")
    grpc_code = str(body.get("grpc_code") or "")
    if status_code == 429 or error == "too_many_activation_attempts":
        return "操作太频繁"
    if status_code == 409 or "already bound" in error:
        return "账号已绑在其他电脑"
    if error == "actor_not_owned_by_device":
        return "本机尚未登记该账号"
    if error in {"missing_device_token", "invalid_device_token"}:
        return "设备凭证已失效"
    if grpc_code in {"FAILED_PRECONDITION", "ALREADY_EXISTS"}:
        return "账号已在轻回绑定"
    if error == "im_unavailable" or status_code == 503 or grpc_code in {"UNAVAILABLE", "DEADLINE_EXCEEDED"}:
        return "暂时连不上轻回"
    if grpc_code == "INVALID_ARGUMENT":
        return "账号信息未被接受"
    if error == "im_rejected":
        return "轻回拒绝了这次登记"
    if error and re.search(r"[\u4e00-\u9fff]", error):
        return error[:15]
    return "同步轻回失败"


class ControlGatewayError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class ControlGatewayNotActivated(ControlGatewayError):
    pass


class ControlGatewayClient:
    """Public HTTPS client for the private IM control-plane gateway."""

    def __init__(
        self,
        config: AdapterConfig,
        credentials: CredentialStore,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not config.control_gateway_url:
            raise ValueError("ADAPTER_GATEWAY_URL is not configured")
        self.config = config
        self.credentials = credentials
        self.base_url = config.control_gateway_url.rstrip("/")
        self._transport = transport
        self._registered_audiences: set[tuple[str, str, str]] = set()

    async def _request(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        token: str = "",
    ) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "User-Agent": f"message-adapter/{__version__}",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            async with httpx.AsyncClient(
                timeout=self.config.control_gateway_timeout_seconds,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                response = await client.post(f"{self.base_url}{path}", json=payload, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning("control gateway connection failed error=%s", type(exc).__name__)
            raise ControlGatewayError("网络连不上轻回", retryable=True) from exc
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = {}
            if not isinstance(body, dict):
                body = {}
            logger.warning(
                "control gateway request failed status=%s operation=%s grpc_code=%s error=%s",
                response.status_code,
                body.get("operation") or "",
                body.get("grpc_code") or "",
                body.get("error") or body.get("detail") or "",
            )
            if response.status_code == 401:
                raise ControlGatewayNotActivated("尚未激活或凭证失效")
            remote_retryable = body.get("retryable")
            retryable = (
                remote_retryable
                if isinstance(remote_retryable, bool)
                else response.status_code == 429 or response.status_code >= 500
            )
            raise ControlGatewayError(
                explain_control_failure(response.status_code, body),
                retryable=retryable,
            )
        try:
            result = response.json()
        except ValueError as exc:
            raise ControlGatewayError("轻回返回内容异常") from exc
        if not isinstance(result, dict):
            raise ControlGatewayError("轻回返回格式异常")
        return result

    def _state(self) -> dict[str, Any]:
        return self.credentials.get(CONTROL_CREDENTIAL_SLOT) or {}

    async def activate(
        self,
        activation_code: str,
        accounts: list[dict[str, Any]],
        *,
        device_id: str = "",
    ) -> dict[str, Any]:
        state = await asyncio.to_thread(self._state)
        resolved_device_id = str(device_id or state.get("device_id") or uuid4())
        if state.get("device_id") != resolved_device_id:
            await asyncio.to_thread(
                self.credentials.save,
                CONTROL_CREDENTIAL_SLOT,
                {**state, "device_id": resolved_device_id},
            )
        payload = {
            "device_id": resolved_device_id,
            "activation_code": activation_code,
            "accounts": [
                {
                    "platform": str(item.get("platform") or ""),
                    "platform_actor_id": str(item.get("platform_actor_id") or ""),
                    "nickname": str(item.get("nickname") or ""),
                    "avatar_url": str(item.get("avatar_url") or ""),
                    "profile": item.get("profile") if isinstance(item.get("profile"), dict) else {},
                }
                for item in accounts
            ],
        }
        result = await self._request("/v1/activate", payload)
        token = str(result.get("device_token") or "")
        if not token:
            raise ControlGatewayError("未拿到设备凭证")
        saved = {
            "device_id": resolved_device_id,
            "device_token": token,
            "activation_code": activation_code,
            "accounts": result.get("accounts") if isinstance(result.get("accounts"), list) else [],
        }
        await asyncio.to_thread(self.credentials.save, CONTROL_CREDENTIAL_SLOT, saved)
        return result

    async def ensure_audience(self, account: dict[str, Any]) -> dict[str, Any]:
        key = (
            str(account.get("platform") or ""),
            str(account.get("platform_actor_id") or ""),
            str(account.get("platform_audience_id") or ""),
        )
        if key in self._registered_audiences:
            return {"cached": True}
        state = await asyncio.to_thread(self._state)
        token = str(state.get("device_token") or "")
        if not token:
            raise ControlGatewayNotActivated("请先输入激活码")
        result = await self._request("/v1/audiences/ensure", account, token=token)
        self._registered_audiences.add(key)
        return result

    async def ensure_audience_from_mq(self, payload: dict[str, Any]) -> None:
        if str(payload.get("func") or "") != "push_message_v2":
            return
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        profile: dict[str, Any] = {}
        encoded_profile = data.get("ex")
        if isinstance(encoded_profile, str):
            try:
                decoded = json.loads(encoded_profile)
                if isinstance(decoded, dict):
                    profile = decoded
            except json.JSONDecodeError:
                pass
        await self.ensure_audience(
            {
                "platform": str(payload.get("platform") or data.get("platform") or ""),
                "platform_actor_id": str(data.get("actorPlatformID") or ""),
                "platform_audience_id": str(data.get("audiencePlatformID") or ""),
                "nickname": str(data.get("audienceNickname") or ""),
                "avatar_url": str(data.get("audienceFaceURL") or ""),
                "profile": profile,
            }
        )


def registration_handler_from_dotenv(dotenv: str):
    """Create the web activation handler only when a gateway URL is configured."""
    config = AdapterConfig.load(platform="boss", dotenv=dotenv)
    if not config.control_gateway_url:
        return None

    async def register(
        activation_code: str,
        accounts: list[dict[str, Any]],
        device_id: str = "",
        data_root: str = "",
    ) -> dict[str, Any]:
        selected_config = AdapterConfig.load(
            platform="boss",
            dotenv=dotenv,
            data_root=data_root or None,
        )
        credentials = CredentialStore(selected_config.credential_db)
        try:
            result = await ControlGatewayClient(selected_config, credentials).activate(
                activation_code,
                accounts,
                device_id=device_id,
            )
        finally:
            credentials.close()
        registrations = result.get("accounts") if isinstance(result.get("accounts"), list) else []
        actor_id = str(registrations[0].get("actor_id") or "") if registrations else ""
        return {"actor_id": actor_id, "accounts": registrations}

    return register
