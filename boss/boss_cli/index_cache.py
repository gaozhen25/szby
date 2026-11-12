"""Search result index cache for short-index navigation.

Stores the last search/recommend result set so that users can quickly
access a job by its 1-based index number (e.g., `boss show 3`).

Cache file: <project>/index_cache.json
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from .constants import CONFIG_DIR

logger = logging.getLogger(__name__)

INDEX_CACHE_FILE = CONFIG_DIR / "index_cache.json"


def save_index(jobs: list[dict[str, Any]], source: str = "search") -> None:
    """Persist an ordered list of jobs for short-index navigation.

    Each entry stores the minimum metadata needed for `show` and `detail`:
    securityId, jobName, brandName, salaryDesc, lid.
    """
    if not jobs:
        return

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    entries = []
    for job in jobs:
        entry = {
            "securityId": job.get("securityId", ""),
            "jobName": job.get("jobName", ""),
            "brandName": job.get("brandName", ""),
            "salaryDesc": job.get("salaryDesc", ""),
            "cityName": job.get("cityName", ""),
            "areaDistrict": job.get("areaDistrict", ""),
            "jobExperience": job.get("jobExperience", ""),
            "jobDegree": job.get("jobDegree", ""),
            "skills": job.get("skills", []),
            "lid": job.get("lid", ""),
        }
        if entry["securityId"]:
            entries.append(entry)

    payload = {
        "source": source,
        "saved_at": time.time(),
        "count": len(entries),
        "items": entries,
    }

    INDEX_CACHE_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    INDEX_CACHE_FILE.chmod(0o600)
    logger.debug("Saved index cache with %d entries from %s", len(entries), source)


def get_job_by_index(index: int) -> dict[str, Any] | None:
    """Resolve a 1-based short index to a cached job reference.

    Returns the job entry dict or None if index is out of range.
    """
    if index <= 0:
        return None

    if not INDEX_CACHE_FILE.exists():
        return None

    try:
        data = json.loads(INDEX_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    items = data.get("items", [])
    if index > len(items):
        return None

    return items[index - 1]


def get_index_info() -> dict[str, Any]:
    """Get metadata about the current index cache."""
    if not INDEX_CACHE_FILE.exists():
        return {"exists": False, "count": 0}

    try:
        data = json.loads(INDEX_CACHE_FILE.read_text(encoding="utf-8"))
        return {
            "exists": True,
            "source": data.get("source", "unknown"),
            "count": data.get("count", 0),
            "saved_at": data.get("saved_at", 0),
        }
    except (OSError, json.JSONDecodeError):
        return {"exists": False, "count": 0}


CHAT_INDEX_FILE = CONFIG_DIR / "chat_index.json"


def save_chat_index(friends: list[dict[str, Any]]) -> None:
    """Persist geek chat list for `boss messages <index>`."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for i, friend in enumerate(friends, 1):
        entries.append({
            "index": i,
            "name": friend.get("name") or friend.get("bossName") or "",
            "company": friend.get("brandName") or friend.get("companyName") or "",
            "job": friend.get("jobName") or "",
            "encryptBossId": (
                friend.get("encryptBossId")
                or friend.get("encryptFriendId")
                or friend.get("encryptUid")
                or ""
            ),
            "securityId": friend.get("securityId") or "",
            "uid": friend.get("uid") or friend.get("friendId"),
        })
    payload = {
        "saved_at": time.time(),
        "count": len(entries),
        "items": entries,
    }
    CHAT_INDEX_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    CHAT_INDEX_FILE.chmod(0o600)


def load_chat_items() -> list[dict[str, Any]]:
    if not CHAT_INDEX_FILE.exists():
        return []
    try:
        data = json.loads(CHAT_INDEX_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = data.get("items") or []
    return items if isinstance(items, list) else []


def find_chat_by_uid(uid: int | str) -> dict[str, Any] | None:
    target = str(uid)
    for item in load_chat_items():
        if str(item.get("uid") or "") == target:
            return item
    return None


def get_chat_by_index(index: int) -> dict[str, Any] | None:
    if index <= 0 or not CHAT_INDEX_FILE.exists():
        return None
    try:
        data = json.loads(CHAT_INDEX_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    items = data.get("items", [])
    if index > len(items):
        return None
    return items[index - 1]


def find_chat(target: str) -> dict[str, Any] | None:
    """Resolve a chat by 1-based index, numeric uid, or encryptBossId."""
    if not target or not CHAT_INDEX_FILE.exists():
        return None
    try:
        data = json.loads(CHAT_INDEX_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    items = data.get("items") or []
    if target.isdigit():
        idx = int(target)
        if 1 <= idx <= len(items):
            return items[idx - 1]
        for item in items:
            if str(item.get("uid") or "") == target:
                return item
        return None
    for item in items:
        if item.get("encryptBossId") == target:
            return item
    return None


RECRUITER_INDEX_FILE = CONFIG_DIR / "recruiter_index.json"


def save_recruiter_index(friends: list[dict[str, Any]]) -> None:
    """Persist recruiter inbox for `boss recruiter messages/reply <index>`."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for i, friend in enumerate(friends, 1):
        entries.append({
            "index": i,
            "name": friend.get("name") or "",
            "job": friend.get("jobName") or friend.get("job") or "",
            "uid": friend.get("uid") or friend.get("friendId"),
            "friendId": friend.get("friendId") or friend.get("uid"),
            "jobId": friend.get("jobId") or 0,
            "encryptGeekId": (
                friend.get("encryptGeekId")
                or friend.get("encryptUid")
                or friend.get("encryptFriendId")
                or ""
            ),
            "securityId": friend.get("securityId") or "",
        })
    payload = {
        "saved_at": time.time(),
        "count": len(entries),
        "items": entries,
    }
    RECRUITER_INDEX_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    RECRUITER_INDEX_FILE.chmod(0o600)


def load_recruiter_items() -> list[dict[str, Any]]:
    if not RECRUITER_INDEX_FILE.exists():
        return []
    try:
        data = json.loads(RECRUITER_INDEX_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = data.get("items") or []
    return items if isinstance(items, list) else []


def find_recruiter_by_uid(uid: int | str) -> dict[str, Any] | None:
    target = str(uid)
    for item in load_recruiter_items():
        if str(item.get("uid") or "") == target or str(item.get("friendId") or "") == target:
            return item
    return None


def find_recruiter(target: str) -> dict[str, Any] | None:
    """Resolve recruiter inbox by 1-based index, friendId/uid, encryptGeekId, or name.

    Matching order for non-numeric targets:
      1. exact encryptGeekId
      2. exact nickname (name field)
      3. substring nickname (name contains target)
    """
    if not target:
        return None
    items = load_recruiter_items()
    if not items:
        return None
    if target.isdigit():
        idx = int(target)
        if 1 <= idx <= len(items):
            return items[idx - 1]
        for item in items:
            if str(item.get("friendId") or "") == target or str(item.get("uid") or "") == target:
                return item
        return None
    for item in items:
        if item.get("encryptGeekId") == target:
            return item
    for item in items:
        if (item.get("name") or "") == target:
            return item
    for item in items:
        if target in (item.get("name") or ""):
            return item
    return None
