"""Safe one-time migration of pre-hash Adapter state databases."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import sqlite3

from message_adapter.config import AdapterConfig
from message_adapter.process_lock import SingleInstanceLock

logger = logging.getLogger(__name__)


def legacy_state_issues(config: AdapterConfig) -> list[str]:
    """Return read-only migration ambiguities for doctor."""
    destination = config.state_db.expanduser().resolve()
    candidates = [
        path.expanduser().resolve()
        for path in config.legacy_state_dbs
        if path.expanduser().resolve() != destination and path.exists()
    ]
    valid = [path for path in candidates if _belongs_to_platform_single_slot(path, config.platform)]
    issues: list[str] = []
    ambiguous = [path for path in candidates if path not in valid]
    if ambiguous:
        issues.append("legacy state has ambiguous or multi-account slots: " + ", ".join(map(str, ambiguous)))
    if len(valid) > 1:
        issues.append("multiple legacy state databases match this platform: " + ", ".join(map(str, valid)))
    return issues


def migrate_legacy_state_database(config: AdapterConfig) -> bool:
    """Move one legacy state DB only when its single platform slot is unambiguous."""
    from .credentials import CredentialStore

    credentials = CredentialStore(config.credential_db, read_only=True)
    try:
        if credentials.legacy_account_count(config.platform) > 1:
            raise RuntimeError("multiple legacy credential account_key slots require explicit reset")
    finally:
        credentials.close()
    destination = config.state_db.expanduser().resolve()
    if destination.exists():
        return False
    issues = legacy_state_issues(config)
    if issues:
        raise RuntimeError("; ".join(issues))
    resolved = [path.expanduser().resolve() for path in config.legacy_state_dbs]
    candidates = [
        path
        for path in resolved
        if path != destination and path.exists() and _belongs_to_platform_single_slot(path, config.platform)
    ]
    if not candidates:
        return False
    source = candidates[0]

    source_lock = source.with_suffix(source.suffix + ".lock")
    with SingleInstanceLock(source_lock):
        if destination.exists():
            return False
        _checkpoint(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)
        for suffix in ("-wal", "-shm"):
            old_sidecar = Path(f"{source}{suffix}")
            if old_sidecar.exists():
                os.replace(old_sidecar, Path(f"{destination}{suffix}"))
    logger.info("migrated Adapter state DB to single-platform path: %s", destination)
    return True


def _belongs_to_platform_single_slot(path: Path, platform: str) -> bool:
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=5)
        try:
            rows = connection.execute(
                "SELECT platform FROM account_state"
            ).fetchall()
            return len(rows) == 1 and str(rows[0][0]) == platform
        finally:
            connection.close()
    except sqlite3.Error:
        return False


def _checkpoint(path: Path) -> None:
    connection = sqlite3.connect(path, timeout=5)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()
