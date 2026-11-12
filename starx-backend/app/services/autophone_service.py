from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import secrets
import time
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import settings


class AutophoneConfigError(RuntimeError):
    pass


class AutophoneRequestError(RuntimeError):
    pass


class AutophoneSubmissionRejectedError(AutophoneRequestError):
    pass


class AutophoneUncertainError(AutophoneRequestError):
    pass


class AutophoneConflictError(AutophoneUncertainError):
    pass


class AutophoneNotFoundError(AutophoneSubmissionRejectedError):
    pass


def validate_autophone_publish_result(
    data: dict[str, Any],
    *,
    expected_external_id: str,
) -> dict[str, Any]:
    external_id = data.get("external_id")
    if not isinstance(external_id, str) or not external_id.strip():
        raise AutophoneUncertainError(
            "autophone success response missing external_id"
        )
    if external_id != expected_external_id:
        raise AutophoneUncertainError(
            "autophone success response external_id mismatch"
        )
    status = data.get("status")
    if not isinstance(status, str) or not status.strip():
        raise AutophoneUncertainError("autophone success response missing status")
    return data


@dataclass(frozen=True)
class AutophonePublishRequest:
    external_id: str
    platform: str
    android_id: str
    asset_list: list[str]
    filename: str = ""
    title: str = ""
    description: str = ""
    visibility: str = "0"
    copy_to_album: bool = True
    sha256: str = ""
    size_bytes: int | None = None


def sha256_hex(body: str) -> str:
    return hashlib.sha256((body or "").encode("utf-8")).hexdigest()


def sign_autophone_request(
    *,
    method: str,
    path: str,
    timestamp: int,
    nonce: str,
    body: str,
    secret: str,
) -> str:
    body_hash = sha256_hex(body)
    text = "\n".join([method.upper(), path, str(timestamp), nonce, body_hash])
    return hmac.new(secret.encode("utf-8"), text.encode("utf-8"), hashlib.sha256).hexdigest()


class AutophoneService:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.base_url = (base_url or settings.autophone_base_url).rstrip("/")
        self.client_id = client_id if client_id is not None else settings.autophone_client_id
        self.client_secret = client_secret if client_secret is not None else settings.autophone_client_secret
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else settings.autophone_timeout

    def _require_credentials(self) -> None:
        if not self.client_id or not self.client_secret:
            raise AutophoneConfigError("autophone client credentials are not configured")

    def _headers(self, *, method: str, path: str, body: str) -> dict[str, str]:
        self._require_credentials()
        timestamp = int(time.time())
        nonce = secrets.token_hex(16)
        return {
            "Content-Type": "application/json",
            "X-Client-Id": self.client_id,
            "X-Timestamp": str(timestamp),
            "X-Nonce": nonce,
            "X-Signature": sign_autophone_request(
                method=method,
                path=path,
                timestamp=timestamp,
                nonce=nonce,
                body=body,
                secret=self.client_secret,
            ),
        }

    def publish(self, request: AutophonePublishRequest) -> dict[str, Any]:
        path = "/api/external/publish"
        payload: dict[str, Any] = {
            "external_id": request.external_id,
            "platform": request.platform,
            "android_id": request.android_id,
            "assert_list": request.asset_list,
            "visibility": request.visibility,
            "copy_to_album": request.copy_to_album,
        }
        optional_values: dict[str, Any] = {
            "filename": request.filename,
            "title": request.title,
            "description": request.description,
            "sha256": request.sha256,
            "size_bytes": request.size_bytes,
        }
        payload.update({key: value for key, value in optional_values.items() if value not in ("", None)})
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        try:
            response = httpx.post(
                f"{self.base_url}{path}",
                content=body.encode("utf-8"),
                headers=self._headers(method="POST", path=path, body=body),
                timeout=self.timeout_seconds,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise AutophoneSubmissionRejectedError(
                f"autophone request failed: {exc}"
            ) from exc
        except httpx.RequestError as exc:
            raise AutophoneUncertainError(f"autophone request failed: {exc}") from exc
        return validate_autophone_publish_result(
            self._parse_response(response),
            expected_external_id=request.external_id,
        )

    def get_publish_status(self, external_id: str) -> dict[str, Any]:
        path = f"/api/external/publish/{quote(external_id, safe='')}"
        try:
            response = httpx.get(
                f"{self.base_url}{path}",
                headers=self._headers(method="GET", path=path, body=""),
                timeout=self.timeout_seconds,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise AutophoneSubmissionRejectedError(
                f"autophone request failed: {exc}"
            ) from exc
        except httpx.RequestError as exc:
            raise AutophoneUncertainError(f"autophone request failed: {exc}") from exc
        return validate_autophone_publish_result(
            self._parse_response(response),
            expected_external_id=external_id,
        )

    def _parse_response(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            message = f"autophone returned non-json response: {response.status_code}"
            if response.status_code == 404:
                raise AutophoneNotFoundError(message) from exc
            if response.status_code == 409:
                raise AutophoneConflictError(message) from exc
            if 400 <= response.status_code < 500:
                raise AutophoneSubmissionRejectedError(message) from exc
            raise AutophoneUncertainError(message) from exc

        if not isinstance(payload, dict):
            raise AutophoneUncertainError("autophone returned invalid json response")

        if response.status_code == 404:
            raise AutophoneNotFoundError(
                str(payload.get("detail") or payload.get("message") or "autophone publish job not found")
            )
        if response.status_code == 409:
            raise AutophoneConflictError(str(payload.get("detail") or payload.get("message") or "autophone publish conflict"))
        if 400 <= response.status_code < 500:
            raise AutophoneSubmissionRejectedError(
                str(
                    payload.get("detail")
                    or payload.get("message")
                    or f"autophone error {response.status_code}"
                )
            )
        if response.status_code >= 500:
            raise AutophoneUncertainError(
                str(
                    payload.get("detail")
                    or payload.get("message")
                    or f"autophone error {response.status_code}"
                )
            )
        if payload.get("success") is not True:
            raise AutophoneSubmissionRejectedError(
                str(
                    payload.get("message")
                    or payload.get("error")
                    or "autophone publish failed"
                )
            )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise AutophoneUncertainError("autophone response missing data")
        return data


default_autophone_service = AutophoneService()
