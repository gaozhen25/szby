from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class CredentialStore:
    """SQLite-backed platform credential vault.

    Credentials live separately from delivery state so platform login tools and
    Adapter processes share one authoritative source without JSON sidecars.
    """

    def __init__(self, path: Path | str, *, read_only: bool = False):
        self.path = Path(path).expanduser().resolve()
        self.read_only = read_only
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None
        if read_only and not self.path.exists():
            self._conn = None
            return
        if read_only:
            self._conn = sqlite3.connect(
                f"{self.path.as_uri()}?mode=ro",
                uri=True,
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level="DEFERRED")
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=FULL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS credentials (
                       platform TEXT NOT NULL,
                       account_key TEXT NOT NULL,
                       payload TEXT NOT NULL,
                       updated_at REAL NOT NULL,
                       PRIMARY KEY (platform, account_key)
                   )"""
            )
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS platform_credentials (
                       platform TEXT PRIMARY KEY,
                       platform_actor_id TEXT NOT NULL DEFAULT '',
                       payload TEXT NOT NULL,
                       updated_at REAL NOT NULL
                   )"""
            )
            self._migrate_single_legacy_slots()
        self._secure_files()

    def _migrate_single_legacy_slots(self) -> None:
        """Migrate only platforms whose old account-key ownership is unambiguous."""
        assert self._conn is not None
        platforms = self._conn.execute("SELECT DISTINCT platform FROM credentials").fetchall()
        for platform_row in platforms:
            platform = str(platform_row["platform"])
            existing = self._conn.execute(
                "SELECT 1 FROM platform_credentials WHERE platform=?", (platform,)
            ).fetchone()
            if existing:
                legacy_count = self._conn.execute(
                    "SELECT COUNT(*) FROM credentials WHERE platform=?", (platform,)
                ).fetchone()[0]
                if legacy_count == 1:
                    self._conn.execute("DELETE FROM credentials WHERE platform=?", (platform,))
                continue
            rows = self._conn.execute(
                "SELECT payload, updated_at FROM credentials WHERE platform=? ORDER BY updated_at DESC",
                (platform,),
            ).fetchall()
            if len(rows) != 1:
                continue
            payload = json.loads(rows[0]["payload"])
            actor_id = self._actor_id_from_payload(platform, payload)
            self._conn.execute(
                "INSERT INTO platform_credentials(platform, platform_actor_id, payload, updated_at) VALUES (?, ?, ?, ?)",
                (platform, actor_id, rows[0]["payload"], rows[0]["updated_at"]),
            )
            self._conn.execute("DELETE FROM credentials WHERE platform=?", (platform,))

    @staticmethod
    def _actor_id_from_payload(platform: str, payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        direct = str(payload.get("platform_actor_id") or "").strip()
        if direct:
            return direct
        if platform == "douyin" and isinstance(payload.get("cookie"), dict):
            return str(payload["cookie"].get("uid") or "").strip()
        return ""

    def _secure_files(self) -> None:
        for candidate in (self.path, Path(f"{self.path}-wal"), Path(f"{self.path}-shm")):
            if candidate.exists():
                try:
                    os.chmod(candidate, 0o600)
                except OSError:
                    pass

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()

    def get(self, platform: str) -> dict[str, Any] | None:
        if self._conn is None:
            return None
        with self._lock:
            try:
                row = self._conn.execute(
                    "SELECT payload FROM platform_credentials WHERE platform=?", (platform,)
                ).fetchone()
            except sqlite3.OperationalError:
                legacy = self.list_legacy_accounts(platform)
                row = {"payload": json.dumps(legacy[0][1])} if len(legacy) == 1 else None
        if row is None:
            return None
        payload = json.loads(row["payload"])
        return payload if isinstance(payload, dict) else None

    def save(self, platform: str, payload: dict[str, Any], *, platform_actor_id: str = "") -> None:
        if self.read_only:
            raise PermissionError("credential store is read-only")
        assert self._conn is not None
        if not platform:
            raise ValueError("platform is required")
        current_actor_id = self.get_bound_actor_id(platform)
        actor_id = str(platform_actor_id or self._actor_id_from_payload(platform, payload)).strip()
        if current_actor_id and actor_id and current_actor_id != actor_id:
            raise RuntimeError(
                f"{platform} is bound to platform_actor_id={current_actor_id}; authenticated UID={actor_id}"
            )
        actor_id = current_actor_id or actor_id
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO platform_credentials(platform, platform_actor_id, payload, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(platform) DO UPDATE SET payload=excluded.payload,
                     platform_actor_id=excluded.platform_actor_id, updated_at=excluded.updated_at""",
                (platform, actor_id, encoded, time.time()),
            )
        self._secure_files()

    def update(self, platform: str, values: dict[str, Any]) -> None:
        self.save(platform, {**(self.get(platform) or {}), **values})

    def delete(self, platform: str) -> bool:
        if self.read_only:
            raise PermissionError("credential store is read-only")
        assert self._conn is not None
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "DELETE FROM platform_credentials WHERE platform=?",
                (platform,),
            )
        return cursor.rowcount > 0

    def get_bound_actor_id(self, platform: str) -> str:
        if self._conn is None:
            return ""
        with self._lock:
            try:
                row = self._conn.execute(
                    "SELECT platform_actor_id FROM platform_credentials WHERE platform=?", (platform,)
                ).fetchone()
            except sqlite3.OperationalError:
                return ""
        return str(row["platform_actor_id"] or "") if row else ""

    def bind_actor(self, platform: str, platform_actor_id: str) -> None:
        actor_id = str(platform_actor_id or "").strip()
        if not actor_id:
            raise ValueError("platform_actor_id is required")
        current = self.get_bound_actor_id(platform)
        if current and current != actor_id:
            raise RuntimeError(
                f"{platform} is bound to platform_actor_id={current}; authenticated UID={actor_id}"
            )
        payload = self.get(platform)
        if payload is None:
            raise RuntimeError(f"{platform} credential is missing")
        self.save(platform, payload, platform_actor_id=actor_id)

    def legacy_account_count(self, platform: str) -> int:
        return len(self.list_legacy_accounts(platform))

    def list_legacy_accounts(self, platform: str) -> list[tuple[str, dict[str, Any]]]:
        if self._conn is None:
            return []
        with self._lock:
            try:
                rows = self._conn.execute(
                    "SELECT account_key, payload FROM credentials WHERE platform=? ORDER BY account_key",
                    (platform,),
                ).fetchall()
            except sqlite3.OperationalError:
                return []
        result: list[tuple[str, dict[str, Any]]] = []
        for row in rows:
            payload = json.loads(row["payload"])
            if isinstance(payload, dict):
                result.append((str(row["account_key"]), payload))
        return result
