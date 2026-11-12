from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import threading
from uuid import uuid4


WORKSPACE_SCHEMA_VERSION = 1
MESSAGE_PLATFORMS = ("boss", "douyin", "rednote")
ALL_PLATFORMS = (*MESSAGE_PLATFORMS, "wechat", "wecom")
ENVIRONMENT_CREDENTIALS = ("BOSS_COOKIES", "DY_COOKIE", "REDNOTE_COOKIE")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _secure(path: Path, mode: int) -> None:
    if not path.exists():
        return
    try:
        os.chmod(path, mode)
    except OSError:
        pass


@dataclass(frozen=True, slots=True)
class Workspace:
    workspace_id: str
    activation_code: str
    device_id: str
    root: Path
    created_at: str
    last_used_at: str


class WorkspaceRegistry:
    """Persistent local-account registry.

    Activation codes are intentionally stored as clear text in a mode-0600
    SQLite database because the local UI must display and reuse the current
    code. Directory names use random UUIDs and never expose the code.
    """

    def __init__(self, data_root: Path | str = Path("adapter_data")):
        self.data_root = Path(data_root).expanduser().resolve()
        self.path = self.data_root / "workspaces.sqlite3"
        self.workspaces_root = self.data_root / "workspaces"
        self.archive_root = self.data_root / "archive"
        self._lock = threading.RLock()
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.workspaces_root.mkdir(parents=True, exist_ok=True)
        _secure(self.data_root, 0o700)
        _secure(self.workspaces_root, 0o700)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=FULL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
            if version not in {0, WORKSPACE_SCHEMA_VERSION}:
                raise RuntimeError(
                    f"unsupported workspace registry schema {version}; "
                    f"expected {WORKSPACE_SCHEMA_VERSION}"
                )
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS workspaces (
                    workspace_id TEXT PRIMARY KEY,
                    activation_code TEXT NOT NULL UNIQUE,
                    device_id TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            if version == 0:
                self._conn.execute(f"PRAGMA user_version={WORKSPACE_SCHEMA_VERSION}")
        self._secure_files()

    def _secure_files(self) -> None:
        for path in (self.path, Path(f"{self.path}-wal"), Path(f"{self.path}-shm")):
            _secure(path, 0o600)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _workspace(self, row: sqlite3.Row | None) -> Workspace | None:
        if row is None:
            return None
        workspace_id = str(row["workspace_id"])
        return Workspace(
            workspace_id=workspace_id,
            activation_code=str(row["activation_code"]),
            device_id=str(row["device_id"]),
            root=(self.workspaces_root / workspace_id).resolve(),
            created_at=str(row["created_at"]),
            last_used_at=str(row["last_used_at"]),
        )

    def find(self, activation_code: str) -> Workspace | None:
        code = str(activation_code or "").strip()
        if not code:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM workspaces WHERE activation_code=?", (code,)
            ).fetchone()
        return self._workspace(row)

    def get(self, workspace_id: str) -> Workspace | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM workspaces WHERE workspace_id=?", (workspace_id,)
            ).fetchone()
        return self._workspace(row)

    def active(self) -> Workspace | None:
        with self._lock:
            row = self._conn.execute(
                """SELECT w.* FROM workspaces w
                   JOIN settings s ON s.value=w.workspace_id
                   WHERE s.key='active_workspace_id'"""
            ).fetchone()
        return self._workspace(row)

    def create(self, activation_code: str, *, device_id: str = "") -> Workspace:
        code = str(activation_code or "").strip()
        if not 4 <= len(code) <= 256:
            raise ValueError("请输入有效的激活码")
        existing = self.find(code)
        if existing is not None:
            return existing
        now = _utc_now()
        workspace_id = uuid4().hex
        resolved_device_id = str(device_id or uuid4())
        root = self.workspaces_root / workspace_id
        root.mkdir(parents=True, exist_ok=False)
        _secure(root, 0o700)
        try:
            with self._lock, self._conn:
                self._conn.execute(
                    """INSERT INTO workspaces
                       (workspace_id, activation_code, device_id, created_at, last_used_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (workspace_id, code, resolved_device_id, now, now),
                )
        except Exception:
            root.rmdir()
            raise
        self._secure_files()
        created = self.get(workspace_id)
        assert created is not None
        return created

    def set_active(self, workspace_id: str) -> Workspace:
        workspace = self.get(workspace_id)
        if workspace is None:
            raise RuntimeError("本地工作区不存在")
        now = _utc_now()
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE workspaces SET last_used_at=? WHERE workspace_id=?",
                (now, workspace_id),
            )
            self._conn.execute(
                """INSERT INTO settings(key, value) VALUES ('active_workspace_id', ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (workspace_id,),
            )
        self._secure_files()
        active = self.get(workspace_id)
        assert active is not None
        return active

    def clear_active(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM settings WHERE key='active_workspace_id'")
        self._secure_files()

    def delete_if_empty(self, workspace_id: str) -> None:
        workspace = self.get(workspace_id)
        if workspace is None:
            return
        if workspace.root.exists() and any(workspace.root.iterdir()):
            raise RuntimeError("refusing to delete a non-empty workspace")
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM settings WHERE key='active_workspace_id' AND value=?",
                (workspace_id,),
            )
            self._conn.execute("DELETE FROM workspaces WHERE workspace_id=?", (workspace_id,))
        if workspace.root.exists():
            workspace.root.rmdir()
        self._secure_files()

    def has_workspaces(self) -> bool:
        with self._lock:
            return bool(self._conn.execute("SELECT 1 FROM workspaces LIMIT 1").fetchone())

    def has_legacy_data(self) -> bool:
        names = {
            "credentials.sqlite3",
            "boss.sqlite3",
            "douyin.sqlite3",
            "rednote.sqlite3",
            "wechat.sqlite3",
            "wecom.sqlite3",
            "douyin_media",
        }
        if any((self.data_root / name).exists() for name in names):
            return True
        profiles = self.data_root / "profiles"
        return any(
            (profiles / platform).exists()
            for platform in (*MESSAGE_PLATFORMS, "xiaohongshu")
        )

    def legacy_issues(self) -> list[str]:
        issues: list[str] = []
        for platform in ALL_PLATFORMS:
            legacy = sorted(self.data_root.glob(f"{platform}-*.sqlite3"))
            if len(legacy) > 1:
                issues.append(
                    f"multiple legacy {platform} state databases require manual migration"
                )
        return issues

    def legacy_control_state(self) -> dict[str, str]:
        credential_db = self.data_root / "credentials.sqlite3"
        if not credential_db.exists():
            return {}
        connection = sqlite3.connect(
            f"{credential_db.resolve().as_uri()}?mode=ro", uri=True, timeout=5
        )
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                "SELECT payload FROM platform_credentials WHERE platform='control_gateway'"
            ).fetchone()
        except sqlite3.Error:
            return {}
        finally:
            connection.close()
        if row is None:
            return {}
        try:
            payload = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            "activation_code": str(payload.get("activation_code") or "").strip(),
            "device_id": str(payload.get("device_id") or "").strip(),
        }

    def legacy_activation_code(self) -> str:
        return self.legacy_control_state().get("activation_code", "")

    def migrate_legacy_into(self, workspace: Workspace) -> list[tuple[Path, Path]]:
        """Move the one flat pre-workspace installation into ``workspace``.

        The caller must ensure no platform worker is running. Moves are rolled
        back in reverse order when any item fails.
        """
        issues = self.legacy_issues()
        if issues:
            raise RuntimeError("; ".join(issues))
        workspace.root.mkdir(parents=True, exist_ok=True)
        _secure(workspace.root, 0o700)
        moves: list[tuple[Path, Path]] = []

        def move(source: Path, target: Path) -> None:
            if not source.exists():
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise RuntimeError(f"workspace migration target already exists: {target.name}")
            shutil.move(str(source), str(target))
            moves.append((source, target))

        try:
            for name in (
                "credentials.sqlite3",
                "credentials.sqlite3-wal",
                "credentials.sqlite3-shm",
            ):
                move(self.data_root / name, workspace.root / name)
            for platform in ALL_PLATFORMS:
                for suffix in ("", "-wal", "-shm"):
                    name = f"{platform}.sqlite3{suffix}"
                    move(self.data_root / name, workspace.root / name)
                legacy = sorted(self.data_root.glob(f"{platform}-*.sqlite3"))
                if len(legacy) == 1:
                    move(legacy[0], workspace.root / legacy[0].name)
            profiles = self.data_root / "profiles"
            if profiles.exists():
                for platform in (*MESSAGE_PLATFORMS, "xiaohongshu"):
                    move(profiles / platform, workspace.root / "profiles" / platform)
                try:
                    profiles.rmdir()
                except OSError:
                    pass
            move(self.data_root / "douyin_media", workspace.root / "douyin_media")
        except Exception:
            for original, moved in reversed(moves):
                if moved.exists():
                    original.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(moved), str(original))
            raise
        return moves

    def archive_and_recreate(self, workspace: Workspace) -> Path:
        """Archive a complete workspace while preserving its registry identity."""
        source = workspace.root.resolve()
        if source.parent != self.workspaces_root.resolve():
            raise RuntimeError("workspace path is outside the managed workspace root")
        archived_at = datetime.now(timezone.utc)
        stamp = archived_at.strftime("%Y%m%dT%H%M%S%fZ")
        self.archive_root.mkdir(parents=True, exist_ok=True)
        _secure(self.archive_root, 0o700)
        archive = self.archive_root / f"workspace-{workspace.workspace_id}-{stamp}"
        staging = self.archive_root / f".workspace-{workspace.workspace_id}-{stamp}.staging"
        if archive.exists():
            raise RuntimeError("workspace archive path already exists")
        if staging.exists():
            raise RuntimeError("workspace archive staging path already exists")
        actor_bindings: dict[str, str] = {}
        credentials = source / "credentials.sqlite3"
        if credentials.exists():
            connection = sqlite3.connect(
                f"{credentials.resolve().as_uri()}?mode=ro",
                uri=True,
                timeout=5,
            )
            try:
                rows = connection.execute(
                    "SELECT platform, platform_actor_id FROM platform_credentials"
                ).fetchall()
                actor_bindings = {
                    str(platform): str(actor_id)
                    for platform, actor_id in rows
                    if str(actor_id or "").strip()
                }
            except sqlite3.Error:
                actor_bindings = {}
            finally:
                connection.close()
        moved = False
        try:
            if source.exists():
                shutil.move(str(source), str(staging))
                moved = True
            staging.mkdir(parents=True, exist_ok=True)
            manifest = staging / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "workspace_id": workspace.workspace_id,
                        "device_id": workspace.device_id,
                        "platform_actor_ids": actor_bindings,
                        "archived_at": archived_at.isoformat(),
                        "reason": "workspace_reset",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            _secure(manifest, 0o600)
            source.mkdir(parents=True, exist_ok=False)
            _secure(source, 0o700)
            shutil.move(str(staging), str(archive))
        except Exception:
            if source.exists() and not any(source.iterdir()):
                source.rmdir()
            rollback = staging if staging.exists() else archive
            if moved and rollback.exists() and not source.exists():
                partial_manifest = rollback / "manifest.json"
                if partial_manifest.exists():
                    partial_manifest.unlink()
                shutil.move(str(rollback), str(source))
            raise
        return archive.resolve()


def active_workspace_root(data_root: Path | str = Path("adapter_data")) -> Path | None:
    root = Path(data_root).expanduser().resolve()
    registry_path = root / "workspaces.sqlite3"
    if not registry_path.exists():
        return None
    registry = WorkspaceRegistry(root)
    try:
        workspace = registry.active()
        return workspace.root if workspace is not None else None
    finally:
        registry.close()


def environment_credential_names() -> list[str]:
    return [name for name in ENVIRONMENT_CREDENTIALS if os.environ.get(name, "").strip()]
