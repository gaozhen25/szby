from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from message_adapter.core.models import Actor, Conversation, SendRequest, status_event_id


SCHEMA_VERSION = 6


def inspect_database(path: Path | str) -> dict[str, Any]:
    """Inspect Adapter state without creating or mutating a database."""
    target = Path(path).expanduser().resolve()
    if not target.exists():
        parent = target.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        creatable = parent.is_dir() and os.access(parent, os.W_OK)
        return {
            "path": str(target),
            "exists": False,
            "creatable": creatable,
            "schema_version": 0,
            "journal_mode": "",
            "integrity": "not_created",
        }
    try:
        uri = f"{target.as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        try:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
            integrity = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        finally:
            connection.close()
        return {
            "path": str(target),
            "exists": True,
            "creatable": True,
            "schema_version": version,
            "journal_mode": journal_mode,
            "integrity": integrity,
        }
    except (OSError, sqlite3.Error) as exc:
        return {
            "path": str(target),
            "exists": True,
            "creatable": False,
            "schema_version": None,
            "journal_mode": "",
            "integrity": f"error:{type(exc).__name__}",
        }


def inspect_actor_binding(path: Path | str, platform: str) -> str:
    """Read a platform UID without creating or migrating the state database."""
    target = Path(path).expanduser().resolve()
    if not target.exists():
        return ""
    connection = sqlite3.connect(f"{target.as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        try:
            row = connection.execute(
                "SELECT platform_actor_id FROM account_state WHERE platform=? ORDER BY updated_at DESC LIMIT 1",
                (platform,),
            ).fetchone()
        except sqlite3.OperationalError:
            return ""
        return str(row[0] or "") if row else ""
    finally:
        connection.close()


def clear_actor_binding(path: Path | str, platform: str) -> bool:
    """Drop the platform UID row so a fresh login can bind a different account.

    Conversations / outbox rows are left in place; only the identity slot is cleared.
    """
    selected = str(platform or "").strip().lower()
    if not selected:
        return False
    target = Path(path).expanduser().resolve()
    if not target.exists():
        return False
    connection = sqlite3.connect(str(target), timeout=30)
    try:
        try:
            with connection:
                cursor = connection.execute(
                    "DELETE FROM account_state WHERE platform=?",
                    (selected,),
                )
        except sqlite3.OperationalError:
            return False
        return cursor.rowcount > 0
    finally:
        connection.close()


def inspect_state_slot_count(path: Path | str, platform: str) -> int:
    """Count legacy/current identity rows without mutating the database."""
    target = Path(path).expanduser().resolve()
    if not target.exists():
        return 0
    connection = sqlite3.connect(f"{target.as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        try:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM account_state WHERE platform=?", (platform,)
                ).fetchone()[0]
            )
        except sqlite3.OperationalError:
            return 0
    finally:
        connection.close()


def inspect_unowned_outbox_count(path: Path | str) -> int:
    """Count legacy outbox rows that cannot safely be assigned to an Actor."""
    target = Path(path).expanduser().resolve()
    if not target.exists():
        return 0
    connection = sqlite3.connect(f"{target.as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(outbox)").fetchall()
        }
        if not {"platform", "platform_actor_id"}.issubset(columns):
            unresolved = 0
            for row in connection.execute("SELECT payload FROM outbox").fetchall():
                try:
                    payload = json.loads(row[0])
                except (TypeError, json.JSONDecodeError):
                    unresolved += 1
                    continue
                if not isinstance(payload, dict):
                    unresolved += 1
                    continue
                data = payload.get("data")
                data = data if isinstance(data, dict) else {}
                platform = str(payload.get("platform") or data.get("platform") or "")
                actor_id = str(
                    payload.get("platform_actor_id")
                    or data.get("actorPlatformID")
                    or ""
                )
                client_msg_id = str(
                    payload.get("clientMsgID")
                    or payload.get("client_msg_id")
                    or data.get("clientMsgID")
                    or data.get("client_msg_id")
                    or ""
                )
                if client_msg_id and (not platform or not actor_id):
                    try:
                        owner = connection.execute(
                            "SELECT platform, platform_actor_id FROM downlink_requests "
                            "WHERE client_msg_id=?",
                            (client_msg_id,),
                        ).fetchone()
                    except sqlite3.OperationalError:
                        owner = None
                    if owner is not None:
                        platform = platform or str(owner[0] or "")
                        actor_id = actor_id or str(owner[1] or "")
                if not platform or not actor_id:
                    unresolved += 1
            return unresolved
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM outbox WHERE platform='' OR platform_actor_id=''"
            ).fetchone()[0]
        )
    except sqlite3.OperationalError:
        return 0
    finally:
        connection.close()


@dataclass(frozen=True, slots=True)
class OutboxItem:
    event_id: str
    payload: dict[str, Any]
    attempts: int
    next_attempt_at: float
    platform: str = ""
    platform_actor_id: str = ""


@dataclass(frozen=True, slots=True)
class ConversationRecord:
    routing_conversation_id: str
    platform_conversation_id: str
    platform_audience_id: str
    audience_name: str
    audience_avatar: str
    platform_data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DownlinkRecord:
    client_msg_id: str
    platform: str
    platform_actor_id: str
    platform_audience_id: str
    content_type: int
    content: str
    state: str
    attempts: int
    next_attempt_at: float
    status: int | None
    status_event: dict[str, Any] | None


class SQLiteStore:
    """Crash-safe local state for one adapter process.

    Methods are synchronous and serialized by a lock. Async callers must invoke
    them through ``asyncio.to_thread`` so filesystem I/O never blocks the loop.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        # Keep sqlite3's DEFERRED transaction mode. Repository methods use the
        # connection context manager so multi-statement outbox/ACK transitions
        # commit atomically instead of silently autocommitting each statement.
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level="DEFERRED")
        self._conn.row_factory = sqlite3.Row
        self._configure()
        self._migrate()
        self.prune()
        self._secure_files()

    def _secure_files(self) -> None:
        for candidate in (self.path, Path(f"{self.path}-wal"), Path(f"{self.path}-shm")):
            if not candidate.exists():
                continue
            try:
                os.chmod(candidate, 0o600)
            except OSError:
                pass

    def _configure(self) -> None:
        with self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=FULL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")

    def _migrate(self) -> None:
        with self._lock, self._conn:
            version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
            if version not in {0, 3, 4, 5, SCHEMA_VERSION}:
                raise RuntimeError(
                    f"unsupported adapter database schema {version}; expected {SCHEMA_VERSION}"
                )
            if version == 0:
                self._conn.executescript(
                    """
                    CREATE TABLE account_state (
                        platform TEXT NOT NULL,
                        platform_actor_id TEXT NOT NULL DEFAULT '',
                        actor_name TEXT NOT NULL DEFAULT '',
                        actor_avatar TEXT NOT NULL DEFAULT '',
                        cursor TEXT NOT NULL DEFAULT '',
                        initialized INTEGER NOT NULL DEFAULT 0,
                        updated_at REAL NOT NULL,
                        PRIMARY KEY (platform)
                    );
                    CREATE TABLE conversations (
                        platform TEXT NOT NULL,
                        platform_actor_id TEXT NOT NULL,
                        routing_conversation_id TEXT NOT NULL,
                        platform_conversation_id TEXT NOT NULL,
                        platform_audience_id TEXT NOT NULL,
                        audience_name TEXT NOT NULL DEFAULT '',
                        audience_avatar TEXT NOT NULL DEFAULT '',
                        platform_data TEXT NOT NULL DEFAULT '{}',
                        updated_at REAL NOT NULL,
                        PRIMARY KEY (platform, platform_actor_id, routing_conversation_id),
                        UNIQUE (platform, platform_actor_id, platform_conversation_id)
                    );
                    CREATE TABLE outbox (
                        event_id TEXT PRIMARY KEY,
                        platform TEXT NOT NULL DEFAULT '',
                        platform_actor_id TEXT NOT NULL DEFAULT '',
                        payload TEXT NOT NULL,
                        attempts INTEGER NOT NULL DEFAULT 0,
                        next_attempt_at REAL NOT NULL DEFAULT 0,
                        created_at REAL NOT NULL,
                        last_error TEXT NOT NULL DEFAULT ''
                    );
                    CREATE TABLE event_tombstones (
                        event_id TEXT PRIMARY KEY,
                        acknowledged_at REAL NOT NULL
                    );
                    CREATE TABLE downlink_requests (
                        client_msg_id TEXT PRIMARY KEY,
                        state TEXT NOT NULL,
                        status INTEGER,
                        status_event TEXT,
                        platform_message_id TEXT NOT NULL DEFAULT '',
                        error TEXT NOT NULL DEFAULT '',
                        updated_at REAL NOT NULL,
                        platform TEXT NOT NULL DEFAULT '',
                        platform_actor_id TEXT NOT NULL DEFAULT '',
                        platform_audience_id TEXT NOT NULL DEFAULT '',
                        content_type INTEGER NOT NULL DEFAULT 0,
                        content TEXT NOT NULL DEFAULT '',
                        payload TEXT NOT NULL DEFAULT '{}',
                        attempts INTEGER NOT NULL DEFAULT 0,
                        next_attempt_at REAL NOT NULL DEFAULT 0,
                        created_at REAL NOT NULL DEFAULT 0
                    );
                    CREATE TABLE echo_suppressions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        platform TEXT NOT NULL,
                        platform_actor_id TEXT NOT NULL,
                        platform_conversation_id TEXT NOT NULL,
                        platform_message_id TEXT NOT NULL DEFAULT '',
                        fingerprint TEXT NOT NULL DEFAULT '',
                        expires_at REAL NOT NULL,
                        consumed_at REAL
                    );
                    CREATE INDEX echo_lookup_mid ON echo_suppressions
                        (platform, platform_actor_id, platform_message_id, expires_at);
                    CREATE INDEX echo_lookup_fingerprint ON echo_suppressions
                        (platform, platform_actor_id, platform_conversation_id, fingerprint, expires_at);
                    CREATE INDEX downlink_due
                        ON downlink_requests(state, next_attempt_at, created_at);
                    CREATE INDEX conversation_audience
                        ON conversations(platform, platform_actor_id, platform_audience_id);
                    CREATE TABLE IF NOT EXISTS outbound_rate_slots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        client_msg_id TEXT NOT NULL,
                        platform TEXT NOT NULL,
                        platform_actor_id TEXT NOT NULL,
                        scheduled_at REAL NOT NULL,
                        attempted_at REAL,
                        state TEXT NOT NULL,
                        created_at REAL NOT NULL
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS outbound_rate_active_client
                        ON outbound_rate_slots(client_msg_id) WHERE state='reserved';
                    CREATE INDEX IF NOT EXISTS outbound_rate_timeline
                        ON outbound_rate_slots(platform, platform_actor_id, scheduled_at);
                    CREATE INDEX outbox_due_actor
                        ON outbox(platform, platform_actor_id, next_attempt_at, created_at);
                    PRAGMA user_version=6;
                    """
                )
            elif version == 3:
                rows = self._conn.execute(
                    "SELECT platform, account_key, platform_actor_id, actor_name, actor_avatar, "
                    "cursor, initialized, updated_at FROM account_state ORDER BY updated_at DESC"
                ).fetchall()
                platforms = {str(row["platform"]) for row in rows}
                if len(rows) > 1 or len(platforms) > 1:
                    raise RuntimeError(
                        "legacy state contains multiple account_key slots; run doctor and reset explicitly"
                    )
                self._conn.execute("ALTER TABLE account_state RENAME TO account_state_v3")
                self._conn.execute(
                    """CREATE TABLE account_state (
                           platform TEXT PRIMARY KEY,
                           platform_actor_id TEXT NOT NULL DEFAULT '',
                           actor_name TEXT NOT NULL DEFAULT '',
                           actor_avatar TEXT NOT NULL DEFAULT '',
                           cursor TEXT NOT NULL DEFAULT '',
                           initialized INTEGER NOT NULL DEFAULT 0,
                           updated_at REAL NOT NULL
                       )"""
                )
                if rows:
                    row = rows[0]
                    self._conn.execute(
                        """INSERT INTO account_state
                           (platform, platform_actor_id, actor_name, actor_avatar, cursor, initialized, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            row["platform"],
                            row["platform_actor_id"],
                            row["actor_name"],
                            row["actor_avatar"],
                            row["cursor"],
                            row["initialized"],
                            row["updated_at"],
                        ),
                    )
                self._conn.execute("DROP TABLE account_state_v3")
            if version in {3, 4}:
                self._conn.execute(
                    """CREATE TABLE IF NOT EXISTS outbound_rate_slots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        client_msg_id TEXT NOT NULL,
                        platform TEXT NOT NULL,
                        platform_actor_id TEXT NOT NULL,
                        scheduled_at REAL NOT NULL,
                        attempted_at REAL,
                        state TEXT NOT NULL,
                        created_at REAL NOT NULL
                    )"""
                )
                self._conn.execute(
                    """CREATE UNIQUE INDEX IF NOT EXISTS outbound_rate_active_client
                       ON outbound_rate_slots(client_msg_id) WHERE state='reserved'"""
                )
                self._conn.execute(
                    """CREATE INDEX IF NOT EXISTS outbound_rate_timeline
                       ON outbound_rate_slots(platform, platform_actor_id, scheduled_at)"""
                )
                self._conn.execute("PRAGMA user_version=5")
            if version in {3, 4, 5}:
                columns = {
                    str(row[1])
                    for row in self._conn.execute("PRAGMA table_info(outbox)").fetchall()
                }
                if "platform" not in columns:
                    self._conn.execute(
                        "ALTER TABLE outbox ADD COLUMN platform TEXT NOT NULL DEFAULT ''"
                    )
                if "platform_actor_id" not in columns:
                    self._conn.execute(
                        "ALTER TABLE outbox ADD COLUMN platform_actor_id TEXT NOT NULL DEFAULT ''"
                    )
                rows = self._conn.execute(
                    "SELECT event_id, payload FROM outbox "
                    "WHERE platform='' OR platform_actor_id=''"
                ).fetchall()
                for row in rows:
                    try:
                        payload = json.loads(row["payload"])
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if not isinstance(payload, dict):
                        continue
                    data = payload.get("data")
                    data = data if isinstance(data, dict) else {}
                    platform = str(payload.get("platform") or data.get("platform") or "")
                    actor_id = str(
                        payload.get("platform_actor_id")
                        or data.get("actorPlatformID")
                        or ""
                    )
                    client_msg_id = str(
                        payload.get("clientMsgID")
                        or payload.get("client_msg_id")
                        or data.get("clientMsgID")
                        or data.get("client_msg_id")
                        or ""
                    )
                    if client_msg_id and (not platform or not actor_id):
                        downlink = self._conn.execute(
                            "SELECT platform, platform_actor_id FROM downlink_requests "
                            "WHERE client_msg_id=?",
                            (client_msg_id,),
                        ).fetchone()
                        if downlink is not None:
                            platform = platform or str(downlink["platform"] or "")
                            actor_id = actor_id or str(downlink["platform_actor_id"] or "")
                    self._conn.execute(
                        "UPDATE outbox SET platform=?, platform_actor_id=? WHERE event_id=?",
                        (platform, actor_id, row["event_id"]),
                    )
                self._conn.execute(
                    "CREATE INDEX IF NOT EXISTS outbox_due_actor "
                    "ON outbox(platform, platform_actor_id, next_attempt_at, created_at)"
                )
                self._conn.execute("PRAGMA user_version=6")
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS boss_wechat_exchanges (
                       platform_actor_id TEXT NOT NULL,
                       platform_audience_id TEXT NOT NULL,
                       created_at REAL NOT NULL,
                       PRIMARY KEY (platform_actor_id, platform_audience_id)
                   )"""
            )
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS boss_phone_exchanges (
                       platform_actor_id TEXT NOT NULL,
                       platform_audience_id TEXT NOT NULL,
                       created_at REAL NOT NULL,
                       PRIMARY KEY (platform_actor_id, platform_audience_id)
                   )"""
            )
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS boss_ai_reply_counts (
                       platform_actor_id TEXT NOT NULL,
                       platform_audience_id TEXT NOT NULL,
                       reply_count INTEGER NOT NULL,
                       PRIMARY KEY (platform_actor_id, platform_audience_id)
                   )"""
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def prune(self, *, tombstone_days: int = 7, downlink_days: int = 30) -> None:
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM event_tombstones WHERE acknowledged_at<?",
                (now - max(1, tombstone_days) * 86400,),
            )
            self._conn.execute(
                "DELETE FROM downlink_requests WHERE state='done' AND updated_at<?",
                (now - max(1, downlink_days) * 86400,),
            )
            self._conn.execute("DELETE FROM echo_suppressions WHERE expires_at<?", (now,))
            self._conn.execute(
                "DELETE FROM outbound_rate_slots WHERE state='attempted' AND scheduled_at<?",
                (now - 2 * 86400,),
            )

    def get_bound_actor_id(self, platform: str) -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT platform_actor_id FROM account_state WHERE platform=?", (platform,)
            ).fetchone()
        return str(row["platform_actor_id"] or "") if row else ""

    def save_actor(self, actor: Actor) -> None:
        now = time.time()
        with self._lock, self._conn:
            current = self._conn.execute(
                "SELECT platform_actor_id FROM account_state WHERE platform=?", (actor.platform,)
            ).fetchone()
            bound = str(current["platform_actor_id"] or "") if current else ""
            if bound and bound != actor.platform_actor_id:
                raise RuntimeError(
                    f"{actor.platform} state is bound to platform_actor_id={bound}; "
                    f"authenticated UID={actor.platform_actor_id}"
                )
            self._conn.execute(
                """INSERT INTO account_state
                   (platform, platform_actor_id, actor_name, actor_avatar, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(platform) DO UPDATE SET
                     platform_actor_id=excluded.platform_actor_id, actor_name=excluded.actor_name,
                     actor_avatar=excluded.actor_avatar, updated_at=excluded.updated_at""",
                (
                    actor.platform,
                    actor.platform_actor_id,
                    actor.username,
                    actor.avatar,
                    now,
                ),
            )

    def get_bootstrap(self, platform: str) -> tuple[bool, str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT initialized, cursor FROM account_state WHERE platform=?",
                (platform,),
            ).fetchone()
        return (bool(row["initialized"]), str(row["cursor"])) if row else (False, "")

    def set_bootstrap(self, platform: str, cursor: str) -> None:
        now = time.time()
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT cursor FROM account_state WHERE platform=?",
                (platform,),
            ).fetchone()
            if row:
                previous = str(row["cursor"] or "")
                try:
                    cursor = str(max(int(previous or 0), int(cursor or 0)))
                except ValueError:
                    # Opaque platform cursors cannot be ordered; the newest
                    # successfully processed value remains authoritative.
                    pass
            self._conn.execute(
                """INSERT INTO account_state
                   (platform, cursor, initialized, updated_at)
                   VALUES (?, ?, 1, ?)
                   ON CONFLICT(platform) DO UPDATE SET
                     cursor=excluded.cursor, initialized=1, updated_at=excluded.updated_at""",
                (platform, cursor, now),
            )

    def save_conversation(self, conversation: Conversation) -> None:
        with self._lock, self._conn:
            platform_data = dict(conversation.platform_data)
            username = conversation.audience.username
            avatar = conversation.audience.avatar
            existing = self._conn.execute(
                """SELECT audience_name, audience_avatar, platform_data FROM conversations
                   WHERE platform=? AND platform_actor_id=? AND
                   (platform_conversation_id=? OR platform_audience_id=?)""",
                (
                    conversation.platform,
                    conversation.platform_actor_id,
                    conversation.platform_conversation_id,
                    conversation.audience.platform_audience_id,
                ),
            ).fetchone()
            if existing is not None:
                username = username or str(existing["audience_name"] or "")
                avatar = avatar or str(existing["audience_avatar"] or "")
                try:
                    previous = json.loads(existing["platform_data"] or "{}")
                except json.JSONDecodeError:
                    previous = {}
                if isinstance(previous, dict):
                    for key in ("encrypt_geek_id", "conversation_ticket"):
                        kept = str(previous.get(key) or "").strip()
                        if kept and not str(platform_data.get(key) or "").strip():
                            platform_data[key] = kept
                    old_short = previous.get("conversation_short_id")
                    if old_short and not platform_data.get("conversation_short_id"):
                        platform_data["conversation_short_id"] = old_short
            encoded = json.dumps(platform_data, ensure_ascii=False, separators=(",", ":"))
            now = time.time()
            updated = self._conn.execute(
                """UPDATE conversations SET platform_conversation_id=?, platform_audience_id=?,
                   audience_name=?, audience_avatar=?, platform_data=?, updated_at=?
                   WHERE platform=? AND platform_actor_id=? AND
                   (platform_conversation_id=? OR platform_audience_id=?)""",
                (
                    conversation.platform_conversation_id,
                    conversation.audience.platform_audience_id,
                    username,
                    avatar,
                    encoded,
                    now,
                    conversation.platform,
                    conversation.platform_actor_id,
                    conversation.platform_conversation_id,
                    conversation.audience.platform_audience_id,
                ),
            )
            if updated.rowcount == 0:
                routing_id = f"{conversation.platform}:{conversation.platform_actor_id}:{conversation.audience.platform_audience_id}"
                self._conn.execute(
                    """INSERT INTO conversations
                       (platform, platform_actor_id, routing_conversation_id, platform_conversation_id,
                        platform_audience_id, audience_name, audience_avatar, platform_data, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        conversation.platform,
                        conversation.platform_actor_id,
                        routing_id,
                        conversation.platform_conversation_id,
                        conversation.audience.platform_audience_id,
                        conversation.audience.username,
                        conversation.audience.avatar,
                        encoded,
                        now,
                    ),
                )

    def resolve_conversation(
        self,
        platform: str,
        platform_actor_id: str,
        platform_audience_id: str,
    ) -> ConversationRecord | None:
        with self._lock:
            row = self._conn.execute(
                """SELECT * FROM conversations
                   WHERE platform=? AND platform_actor_id=? AND platform_audience_id=?
                   ORDER BY updated_at DESC LIMIT 1""",
                (platform, platform_actor_id, platform_audience_id),
            ).fetchone()
        if not row:
            return None
        return ConversationRecord(
            routing_conversation_id=row["routing_conversation_id"],
            platform_conversation_id=row["platform_conversation_id"],
            platform_audience_id=row["platform_audience_id"],
            audience_name=row["audience_name"],
            audience_avatar=row["audience_avatar"],
            platform_data=json.loads(row["platform_data"] or "{}"),
        )

    def record_boss_ai_reply(self, platform_actor_id: str, platform_audience_id: str) -> int:
        """Count one successful AI reply. The count survives a process restart."""
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO boss_ai_reply_counts
                       (platform_actor_id, platform_audience_id, reply_count)
                   VALUES (?, ?, 1)
                   ON CONFLICT(platform_actor_id, platform_audience_id)
                   DO UPDATE SET reply_count = reply_count + 1""",
                (platform_actor_id, platform_audience_id),
            )
            row = self._conn.execute(
                """SELECT reply_count FROM boss_ai_reply_counts
                   WHERE platform_actor_id=? AND platform_audience_id=?""",
                (platform_actor_id, platform_audience_id),
            ).fetchone()
        return int(row["reply_count"])

    def has_wechat_exchange(self, platform_actor_id: str, platform_audience_id: str) -> bool:
        return self._has_contact_exchange("boss_wechat_exchanges", platform_actor_id, platform_audience_id)

    def claim_wechat_exchange(self, platform_actor_id: str, platform_audience_id: str) -> bool:
        return self._claim_contact_exchange("boss_wechat_exchanges", platform_actor_id, platform_audience_id)

    def release_wechat_exchange(self, platform_actor_id: str, platform_audience_id: str) -> None:
        self._release_contact_exchange("boss_wechat_exchanges", platform_actor_id, platform_audience_id)

    def has_phone_exchange(self, platform_actor_id: str, platform_audience_id: str) -> bool:
        return self._has_contact_exchange("boss_phone_exchanges", platform_actor_id, platform_audience_id)

    def claim_phone_exchange(self, platform_actor_id: str, platform_audience_id: str) -> bool:
        return self._claim_contact_exchange("boss_phone_exchanges", platform_actor_id, platform_audience_id)

    def release_phone_exchange(self, platform_actor_id: str, platform_audience_id: str) -> None:
        self._release_contact_exchange("boss_phone_exchanges", platform_actor_id, platform_audience_id)

    def _has_contact_exchange(self, table: str, platform_actor_id: str, platform_audience_id: str) -> bool:
        self._require_exchange_table(table)
        with self._lock:
            row = self._conn.execute(
                f"""SELECT 1 FROM {table}
                   WHERE platform_actor_id=? AND platform_audience_id=?""",
                (platform_actor_id, platform_audience_id),
            ).fetchone()
        return row is not None

    def _claim_contact_exchange(self, table: str, platform_actor_id: str, platform_audience_id: str) -> bool:
        self._require_exchange_table(table)
        with self._lock, self._conn:
            inserted = self._conn.execute(
                f"""INSERT OR IGNORE INTO {table}
                   (platform_actor_id, platform_audience_id, created_at)
                   VALUES (?, ?, ?)""",
                (platform_actor_id, platform_audience_id, time.time()),
            )
        return inserted.rowcount == 1

    def _release_contact_exchange(self, table: str, platform_actor_id: str, platform_audience_id: str) -> None:
        self._require_exchange_table(table)
        with self._lock, self._conn:
            self._conn.execute(
                f"""DELETE FROM {table}
                   WHERE platform_actor_id=? AND platform_audience_id=?""",
                (platform_actor_id, platform_audience_id),
            )

    @staticmethod
    def _require_exchange_table(table: str) -> None:
        if table not in {"boss_wechat_exchanges", "boss_phone_exchanges"}:
            raise ValueError(f"unknown exchange table: {table}")

    def enqueue(
        self,
        event_id: str,
        payload: dict[str, Any],
        *,
        force: bool = False,
        platform: str = "",
        platform_actor_id: str = "",
    ) -> bool:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        platform = str(platform or payload.get("platform") or data.get("platform") or "")
        platform_actor_id = str(
            platform_actor_id
            or payload.get("platform_actor_id")
            or data.get("actorPlatformID")
            or ""
        )
        now = time.time()
        with self._lock, self._conn:
            if self._conn.execute("SELECT 1 FROM event_tombstones WHERE event_id=?", (event_id,)).fetchone():
                if not force:
                    return False
                self._conn.execute("DELETE FROM event_tombstones WHERE event_id=?", (event_id,))
            cur = self._conn.execute(
                """INSERT OR IGNORE INTO outbox
                   (event_id, platform, platform_actor_id, payload, attempts, next_attempt_at, created_at)
                   VALUES (?, ?, ?, ?, 0, 0, ?)""",
                (event_id, platform, platform_actor_id, encoded, now),
            )
            return cur.rowcount > 0

    def due_outbox(
        self,
        now: float | None = None,
        limit: int = 100,
        *,
        platform: str = "",
        platform_actor_id: str = "",
    ) -> list[OutboxItem]:
        now = time.time() if now is None else now
        where = "next_attempt_at<=?"
        params: list[Any] = [now]
        if platform or platform_actor_id:
            if not platform or not platform_actor_id:
                raise ValueError("outbox scope requires platform and platform_actor_id")
            where += " AND platform=? AND platform_actor_id=?"
            params.extend((platform, platform_actor_id))
        params.append(max(1, int(limit)))
        with self._lock:
            rows = self._conn.execute(
                f"""SELECT event_id, platform, platform_actor_id, payload, attempts, next_attempt_at
                    FROM outbox WHERE {where} ORDER BY created_at LIMIT ?""",
                tuple(params),
            ).fetchall()
        return [
            OutboxItem(
                r["event_id"],
                json.loads(r["payload"]),
                r["attempts"],
                r["next_attempt_at"],
                r["platform"],
                r["platform_actor_id"],
            )
            for r in rows
        ]

    def mark_attempt(self, event_id: str, next_attempt_at: float, error: str = "") -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """UPDATE outbox SET attempts=attempts+1, next_attempt_at=?, last_error=?
                   WHERE event_id=?""",
                (next_attempt_at, error[:500], event_id),
            )

    def mark_published(self, event_id: str) -> bool:
        with self._lock, self._conn:
            row = self._conn.execute("SELECT 1 FROM outbox WHERE event_id=?", (event_id,)).fetchone()
            if row is None:
                return False
            self._conn.execute(
                "INSERT OR IGNORE INTO event_tombstones(event_id, acknowledged_at) VALUES (?, ?)",
                (event_id, time.time()),
            )
            self._conn.execute("DELETE FROM outbox WHERE event_id=?", (event_id,))
            return True

    acknowledge = mark_published

    @staticmethod
    def _downlink_record(row: sqlite3.Row) -> DownlinkRecord:
        return DownlinkRecord(
            client_msg_id=row["client_msg_id"],
            platform=row["platform"],
            platform_actor_id=row["platform_actor_id"],
            platform_audience_id=row["platform_audience_id"],
            content_type=int(row["content_type"] or 0),
            content=row["content"],
            state=row["state"],
            attempts=int(row["attempts"] or 0),
            next_attempt_at=float(row["next_attempt_at"] or 0),
            status=row["status"],
            status_event=json.loads(row["status_event"]) if row["status_event"] else None,
        )

    def get_downlink(self, client_msg_id: str) -> DownlinkRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM downlink_requests WHERE client_msg_id=?",
                (client_msg_id,),
            ).fetchone()
        return self._downlink_record(row) if row else None

    def put_downlink(self, request: SendRequest, payload: dict[str, Any]) -> bool:
        now = time.time()
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._conn:
            cur = self._conn.execute(
                """INSERT OR IGNORE INTO downlink_requests
                   (client_msg_id, platform, platform_actor_id, platform_audience_id, content_type, content,
                    payload, state, attempts, next_attempt_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, 0, ?, ?)""",
                (
                    request.client_msg_id,
                    request.platform,
                    request.platform_actor_id,
                    request.platform_audience_id,
                    request.content_type,
                    request.content,
                    encoded,
                    now,
                    now,
                ),
            )
            return cur.rowcount > 0

    def claim_due_downlink(
        self,
        now: float | None = None,
        *,
        platform: str = "",
        platform_actor_id: str = "",
    ) -> DownlinkRecord | None:
        now = time.time() if now is None else now
        scope = "state='pending' AND next_attempt_at<=?"
        params: list[Any] = [now]
        if platform or platform_actor_id:
            if not platform or not platform_actor_id:
                raise ValueError("downlink scope requires platform and platform_actor_id")
            scope += " AND platform=? AND platform_actor_id=?"
            params.extend((platform, platform_actor_id))
        with self._lock, self._conn:
            row = self._conn.execute(
                f"""SELECT * FROM downlink_requests WHERE {scope}
                    ORDER BY created_at, rowid LIMIT 1""",
                tuple(params),
            ).fetchone()
            if row is None:
                return None
            self._conn.execute(
                """UPDATE downlink_requests SET state='claimed', attempts=attempts+1,
                   updated_at=? WHERE client_msg_id=? AND state='pending'""",
                (time.time(), row["client_msg_id"]),
            )
            claimed = self._conn.execute(
                "SELECT * FROM downlink_requests WHERE client_msg_id=?",
                (row["client_msg_id"],),
            ).fetchone()
        return self._downlink_record(claimed)

    def reserve_downlink_send_slot(
        self,
        client_msg_id: str,
        *,
        platform: str,
        platform_actor_id: str,
        now: float,
        spacing_seconds: float,
        max_per_minute: int,
        max_per_hour: int,
    ) -> float:
        """Persist and return this attempt's earliest platform-call time.

        Reserved future slots count toward rolling limits, so a large burst is
        spread out immediately and cannot bypass the limits after a restart.
        """
        spacing_seconds = max(0.0, float(spacing_seconds))
        max_per_minute = max(1, int(max_per_minute))
        max_per_hour = max(1, int(max_per_hour))
        with self._lock, self._conn:
            existing = self._conn.execute(
                """SELECT id, scheduled_at FROM outbound_rate_slots
                   WHERE client_msg_id=? AND state='reserved'""",
                (client_msg_id,),
            ).fetchone()
            if existing is not None and float(existing["scheduled_at"]) > now:
                scheduled_at = float(existing["scheduled_at"])
            else:
                scope = "platform=? AND platform_actor_id=?"
                params: tuple[Any, ...] = (platform, platform_actor_id)
                if existing is not None:
                    # On a late restart, ignore reservations belonging to
                    # later tasks while preserving earlier queue order.
                    scope += " AND (state='attempted' OR (state='reserved' AND id<?))"
                    params = (*params, int(existing["id"]))
                latest = self._conn.execute(
                    f"SELECT MAX(scheduled_at) AS scheduled_at FROM outbound_rate_slots WHERE {scope}",
                    params,
                ).fetchone()
                latest_at = float(latest["scheduled_at"]) if latest["scheduled_at"] is not None else None
                scheduled_at = max(now, latest_at + spacing_seconds) if latest_at is not None else now
                for limit, window in (
                    (max_per_minute, 60.0),
                    (max_per_hour, 3600.0),
                ):
                    anchor = self._conn.execute(
                        f"""SELECT scheduled_at FROM outbound_rate_slots
                            WHERE {scope} ORDER BY scheduled_at DESC LIMIT 1 OFFSET ?""",
                        (*params, limit - 1),
                    ).fetchone()
                    if anchor is not None:
                        scheduled_at = max(scheduled_at, float(anchor["scheduled_at"]) + window + 0.001)
                if existing is None:
                    self._conn.execute(
                        """INSERT INTO outbound_rate_slots
                           (client_msg_id, platform, platform_actor_id, scheduled_at, state, created_at)
                           VALUES (?, ?, ?, ?, 'reserved', ?)""",
                        (client_msg_id, platform, platform_actor_id, scheduled_at, now),
                    )
                else:
                    self._conn.execute(
                        "UPDATE outbound_rate_slots SET scheduled_at=? WHERE id=?",
                        (scheduled_at, existing["id"]),
                    )

            if scheduled_at > now:
                self._conn.execute(
                    """UPDATE downlink_requests SET state='pending',
                       attempts=MAX(attempts-1, 0), next_attempt_at=?, error='rate_limited', updated_at=?
                       WHERE client_msg_id=? AND state='claimed'""",
                    (scheduled_at, now, client_msg_id),
                )
            return scheduled_at

    def mark_downlink_sending(self, client_msg_id: str, *, now: float | None = None) -> None:
        """Atomically mark that a rate-limited platform operation may begin."""
        now = time.time() if now is None else now
        with self._lock, self._conn:
            updated = self._conn.execute(
                """UPDATE downlink_requests SET state='processing', error='', updated_at=?
                   WHERE client_msg_id=? AND state='claimed'""",
                (now, client_msg_id),
            )
            if updated.rowcount != 1:
                raise RuntimeError(f"downlink {client_msg_id} is not claimed")
            slot = self._conn.execute(
                """UPDATE outbound_rate_slots SET state='attempted', scheduled_at=?, attempted_at=?
                   WHERE client_msg_id=? AND state='reserved'""",
                (now, now, client_msg_id),
            )
            if slot.rowcount != 1:
                raise RuntimeError(f"downlink {client_msg_id} has no reserved send slot")

    def recover_claimed_downlinks(self) -> int:
        """Requeue tasks that crashed before any platform operation began."""
        with self._lock, self._conn:
            updated = self._conn.execute(
                """UPDATE downlink_requests SET state='pending', attempts=MAX(attempts-1, 0),
                   next_attempt_at=COALESCE(
                     (SELECT scheduled_at FROM outbound_rate_slots
                      WHERE outbound_rate_slots.client_msg_id=downlink_requests.client_msg_id
                        AND outbound_rate_slots.state='reserved'), 0),
                   updated_at=? WHERE state='claimed'""",
                (time.time(),),
            )
            return updated.rowcount

    def retry_downlink(self, client_msg_id: str, next_attempt_at: float, error: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """UPDATE downlink_requests SET state='pending', next_attempt_at=?, error=?,
                   updated_at=? WHERE client_msg_id=?""",
                (next_attempt_at, error[:500], time.time(), client_msg_id),
            )

    def processing_downlinks(self) -> list[DownlinkRecord]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM downlink_requests WHERE state='processing' ORDER BY created_at").fetchall()
        return [self._downlink_record(row) for row in rows]

    def replay_downlink_status(self, client_msg_id: str) -> bool:
        record = self.get_downlink(client_msg_id)
        if not record or record.state != "done" or not record.status_event:
            return False
        return self.enqueue(
            status_event_id(record.status_event),
            record.status_event,
            force=True,
            platform=record.platform,
            platform_actor_id=record.platform_actor_id,
        )

    def record_rejected_downlink(
        self,
        *,
        client_msg_id: str,
        platform: str,
        platform_actor_id: str,
        platform_audience_id: str,
        payload: dict[str, Any],
        status: int,
        status_event: dict[str, Any],
        error: str,
    ) -> None:
        now = time.time()
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR IGNORE INTO downlink_requests
                   (client_msg_id, platform, platform_actor_id, platform_audience_id, content_type, content,
                    payload, state, attempts, next_attempt_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 0, '', ?, 'processing', 0, 0, ?, ?)""",
                (
                    client_msg_id,
                    platform,
                    platform_actor_id,
                    platform_audience_id,
                    encoded,
                    now,
                    now,
                ),
            )
        self.finish_downlink(
            client_msg_id,
            status=status,
            status_event=status_event,
            error=error,
        )

    def finish_downlink(
        self,
        client_msg_id: str,
        *,
        status: int,
        status_event: dict[str, Any],
        platform_message_id: str = "",
        error: str = "",
    ) -> None:
        encoded = json.dumps(status_event, ensure_ascii=False, separators=(",", ":"))
        event_id = status_event_id(status_event)
        if not str(status_event.get("clientMsgID") or status_event.get("client_msg_id") or "").strip():
            raise ValueError("status_event.clientMsgID is required")
        now = time.time()
        with self._lock, self._conn:
            owner = self._conn.execute(
                "SELECT platform, platform_actor_id FROM downlink_requests WHERE client_msg_id=?",
                (client_msg_id,),
            ).fetchone()
            if owner is None:
                raise RuntimeError(f"downlink {client_msg_id} does not exist")
            self._conn.execute(
                """UPDATE downlink_requests SET state='done', status=?, status_event=?,
                   platform_message_id=?, error=?, updated_at=? WHERE client_msg_id=?""",
                (
                    status,
                    encoded,
                    platform_message_id,
                    error[:500],
                    now,
                    client_msg_id,
                ),
            )
            # Persist the send result in the same transaction as its RabbitMQ
            # outbox event. A crash cannot lose a completed platform result.
            self._conn.execute(
                """INSERT OR IGNORE INTO outbox
                   (event_id, platform, platform_actor_id, payload, attempts, next_attempt_at, created_at)
                   VALUES (?, ?, ?, ?, 0, 0, ?)""",
                (
                    event_id,
                    str(owner["platform"] or ""),
                    str(owner["platform_actor_id"] or ""),
                    encoded,
                    now,
                ),
            )

    def add_echo(
        self,
        *,
        platform: str,
        platform_actor_id: str,
        platform_conversation_id: str,
        platform_message_id: str,
        fingerprint: str,
        ttl_seconds: float = 120.0,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO echo_suppressions
                   (platform, platform_actor_id, platform_conversation_id, platform_message_id,
                    fingerprint, expires_at) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    platform,
                    platform_actor_id,
                    platform_conversation_id,
                    platform_message_id,
                    fingerprint,
                    time.time() + ttl_seconds,
                ),
            )

    def consume_echo(
        self,
        *,
        platform: str,
        platform_actor_id: str,
        platform_conversation_id: str,
        platform_message_id: str,
        fingerprint: str,
    ) -> bool:
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM echo_suppressions WHERE expires_at<?", (now,))
            row = None
            if platform_message_id:
                row = self._conn.execute(
                    """SELECT id FROM echo_suppressions WHERE platform=? AND platform_actor_id=?
                       AND platform_message_id=? AND consumed_at IS NULL AND expires_at>=?
                       ORDER BY id LIMIT 1""",
                    (platform, platform_actor_id, platform_message_id, now),
                ).fetchone()
            if row is None and fingerprint:
                row = self._conn.execute(
                    """SELECT id FROM echo_suppressions WHERE platform=? AND platform_actor_id=?
                       AND platform_conversation_id=? AND fingerprint=?
                       AND consumed_at IS NULL AND expires_at>=? ORDER BY id LIMIT 1""",
                    (platform, platform_actor_id, platform_conversation_id, fingerprint, now),
                ).fetchone()
            # Conversation id can drift after create/send; still suppress by text fingerprint.
            if row is None and fingerprint:
                row = self._conn.execute(
                    """SELECT id FROM echo_suppressions WHERE platform=? AND platform_actor_id=?
                       AND fingerprint=? AND consumed_at IS NULL AND expires_at>=?
                       ORDER BY id LIMIT 1""",
                    (platform, platform_actor_id, fingerprint, now),
                ).fetchone()
            if row is None:
                return False
            self._conn.execute("UPDATE echo_suppressions SET consumed_at=? WHERE id=?", (now, row["id"]))
            return True
