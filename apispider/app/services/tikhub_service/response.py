from __future__ import annotations

import base64
import json
from typing import Any

from pydantic import BaseModel

from app.services.tikhub_service.errors import TikHubBusinessRequestError


def mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python")
    if not isinstance(value, dict):
        raise TikHubBusinessRequestError("TikHub returned an invalid response")
    code = value.get("code")
    if code not in (None, 0, 200, "0", "200"):
        raise TikHubBusinessRequestError(
            "TikHub returned an unsuccessful business response"
        )
    data = value.get("data")
    return data if isinstance(data, dict) else value


def unwrap_item(item: dict[str, Any]) -> dict[str, Any]:
    # Douyin search V2 wraps every result as
    # business_data[] -> data -> aweme_info. Keep the card metadata while
    # exposing the actual aweme fields to the normalizer.
    payload = item.get("data")
    if isinstance(payload, dict):
        return {**item, **payload, **unwrap_item(payload)}
    for key in (
        "aweme_info",
        "user_info",
        "note_card",
        "note",
        "photo",
        "visionSearchPhoto",
        "visionSearchUser",
    ):
        nested = item.get(key)
        if isinstance(nested, dict):
            return {**item, **nested}
    return item


def item_list(data: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    queue = [data]
    seen: set[int] = set()
    while queue:
        node = queue.pop(0)
        if id(node) in seen:
            continue
        seen.add(id(node))
        for key in keys:
            value = node.get(key)
            if isinstance(value, list):
                return [unwrap_item(item) for item in value if isinstance(item, dict)]
        queue.extend(value for value in node.values() if isinstance(value, dict))
    return []


def first_item(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    queue = [data]
    while queue:
        node = queue.pop(0)
        for key in keys:
            value = node.get(key)
            if isinstance(value, dict):
                return unwrap_item(value)
        queue.extend(value for value in node.values() if isinstance(value, dict))
    return unwrap_item(data)


def pagination_state(data: dict[str, Any]) -> dict[str, Any]:
    state: dict[str, Any] = {}
    queue = [data]
    seen: set[int] = set()
    keys = {
        "cursor",
        "max_cursor",
        "pcursor",
        "next_cursor",
        "search_id",
        "search_session_id",
        "backtrace",
        "has_more",
        "hasMore",
    }
    while queue:
        node = queue.pop(0)
        if id(node) in seen:
            continue
        seen.add(id(node))
        for key in keys:
            if key in node and key not in state:
                state[key] = node[key]
        queue.extend(value for value in node.values() if isinstance(value, dict))
    return state


def page_state(data: dict[str, Any]) -> tuple[bool, Any]:
    state = pagination_state(data)
    has_more = bool(state.get("has_more", state.get("hasMore", False)))
    cursor = next(
        (
            state.get(key)
            for key in ("cursor", "max_cursor", "pcursor", "next_cursor")
            if state.get(key) not in (None, "")
        ),
        None,
    )
    return has_more, cursor


def encode_cursor(platform: str, **state: Any) -> str:
    payload = json.dumps(
        {"v": 1, "platform": platform, "state": state},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_cursor(value: str, platform: str) -> dict[str, Any]:
    if not value:
        return {}
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        if payload.get("v") != 1 or payload.get("platform") != platform:
            return {}
        state = payload.get("state")
        return state if isinstance(state, dict) else {}
    except (ValueError, TypeError, json.JSONDecodeError):
        return {}
