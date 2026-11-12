from __future__ import annotations

import os
import shutil
import sqlite3
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path

from message_adapter.browser_profiles import BrowserProfile
from message_adapter.config import AdapterConfig
from message_adapter.process_lock import SingleInstanceLock
from message_adapter.storage import CredentialStore


def _state_actor_id(path: Path, platform: str) -> str:
    if not path.exists():
        return ""
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        rows = connection.execute(
            "SELECT platform_actor_id FROM account_state WHERE platform=?", (platform,)
        ).fetchall()
        if len(rows) > 1:
            raise RuntimeError("state database contains multiple legacy account slots; refusing reset")
        row = rows[0] if rows else None
        return str(row[0] or "") if row else ""
    finally:
        connection.close()


def archive_platform_state(
    config: AdapterConfig,
    confirm_uid: str,
    *,
    acquire_owner_lock: bool = True,
) -> Path:
    """Atomically detach one platform slot into a private, recoverable archive."""
    platform = config.platform
    profile = BrowserProfile(config.browser_profile_root, platform)
    state_lock = config.state_db.with_suffix(config.state_db.suffix + ".lock")
    owner_lock = SingleInstanceLock(config.owner_lock_path) if acquire_owner_lock else nullcontext()
    with (
        owner_lock,
        SingleInstanceLock(state_lock),
        SingleInstanceLock(profile.lock_path),
    ):
        credentials = CredentialStore(config.credential_db)
        try:
            credential_uid = credentials.get_bound_actor_id(platform)
            state_uid = _state_actor_id(config.state_db, platform)
            if credential_uid and state_uid and credential_uid != state_uid:
                raise RuntimeError(
                    f"credential UID {credential_uid} conflicts with state UID {state_uid}; refusing reset"
                )
            bound_uid = state_uid or credential_uid
            if not bound_uid:
                raise RuntimeError(f"{platform} has no bound platform_actor_id to confirm")
            if str(confirm_uid).strip() != bound_uid:
                raise RuntimeError(
                    f"confirmation UID does not match the bound platform_actor_id={bound_uid}"
                )

            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            archive = config.state_db.parent / "archive" / f"{platform}-{bound_uid}-{stamp}"
            archive.mkdir(parents=True, exist_ok=False)
            os.chmod(archive, 0o700)

            payload = credentials.get(platform)
            if payload is not None:
                archived_credentials = CredentialStore(archive / "credentials.sqlite3")
                try:
                    archived_credentials.save(platform, payload, platform_actor_id=bound_uid)
                finally:
                    archived_credentials.close()
                credentials.delete(platform)
        finally:
            credentials.close()

        for source in (config.state_db, Path(f"{config.state_db}-wal"), Path(f"{config.state_db}-shm")):
            if source.exists():
                shutil.move(str(source), str(archive / source.name))
        platform_profiles = profile.root.expanduser().resolve() / profile.platform_key
        if platform_profiles.exists():
            for source in platform_profiles.iterdir():
                if source.is_dir():
                    shutil.move(str(source), str(archive / f"profile-{source.name}"))
        return archive.resolve()
