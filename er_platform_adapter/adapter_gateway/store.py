from __future__ import annotations

import hashlib
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from typing import Any


class DeviceOwnershipError(RuntimeError):
    pass


class GatewayStore:
    """SQLite device registry. Raw device tokens are never persisted."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=FULL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")
            version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
            if version not in {0, 1}:
                self._conn.close()
                raise RuntimeError(f"unsupported gateway database schema {version}; expected 1")
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_seen_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS device_accounts (
                    device_id TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
                    platform TEXT NOT NULL,
                    platform_actor_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    openim_id TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (device_id, platform, platform_actor_id),
                    UNIQUE (platform, platform_actor_id)
                );
                CREATE INDEX IF NOT EXISTS device_accounts_device ON device_accounts(device_id);
                """
            )
            if version == 0:
                self._conn.execute("PRAGMA user_version=1")
        self._secure_files()

    def _secure_files(self) -> None:
        for candidate in (self.path, Path(f"{self.path}-wal"), Path(f"{self.path}-shm")):
            if candidate.exists():
                try:
                    os.chmod(candidate, 0o600)
                except OSError:
                    pass

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def assert_claimable(self, device_id: str, accounts: list[dict[str, Any]]) -> None:
        with self._lock:
            for account in accounts:
                row = self._conn.execute(
                    "SELECT device_id FROM device_accounts WHERE platform=? AND platform_actor_id=?",
                    (account["platform"], account["platform_actor_id"]),
                ).fetchone()
                if row is not None and str(row["device_id"]) != device_id:
                    raise DeviceOwnershipError(
                        f"{account['platform']} platform UID is already bound to another device"
                    )

    def register_device(self, device_id: str, accounts: list[dict[str, Any]]) -> str:
        """Atomically claim accounts and rotate the device bearer token."""
        token = f"dvc_{secrets.token_urlsafe(32)}"
        digest = self._token_hash(token)
        now = time.time()
        with self._lock, self._conn:
            self.assert_claimable(device_id, accounts)
            self._conn.execute(
                """INSERT INTO devices(device_id, token_hash, created_at, updated_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(device_id) DO UPDATE SET token_hash=excluded.token_hash,
                     updated_at=excluded.updated_at, last_seen_at=excluded.last_seen_at""",
                (device_id, digest, now, now, now),
            )
            self._conn.execute("DELETE FROM device_accounts WHERE device_id=?", (device_id,))
            for account in accounts:
                self._conn.execute(
                    """INSERT INTO device_accounts
                       (device_id, platform, platform_actor_id, actor_id, openim_id, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(device_id, platform, platform_actor_id) DO UPDATE SET
                         actor_id=excluded.actor_id, openim_id=excluded.openim_id,
                         updated_at=excluded.updated_at""",
                    (
                        device_id,
                        account["platform"],
                        account["platform_actor_id"],
                        account["actor_id"],
                        account.get("openim_id", ""),
                        now,
                        now,
                    ),
                )
        self._secure_files()
        return token

    def authenticate(self, token: str) -> str:
        digest = self._token_hash(token)
        now = time.time()
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT device_id FROM devices WHERE token_hash=?",
                (digest,),
            ).fetchone()
            if row is None:
                return ""
            device_id = str(row["device_id"])
            self._conn.execute(
                "UPDATE devices SET last_seen_at=?, updated_at=? WHERE device_id=?",
                (now, now, device_id),
            )
            return device_id

    def owns_actor(self, device_id: str, platform: str, platform_actor_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                """SELECT 1 FROM device_accounts
                   WHERE device_id=? AND platform=? AND platform_actor_id=?""",
                (device_id, platform, platform_actor_id),
            ).fetchone()
        return row is not None

    def close(self) -> None:
        with self._lock:
            self._conn.close()
