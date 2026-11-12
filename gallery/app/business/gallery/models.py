"""Gallery catalog tables, in the same shape starx-backend uses.

A row has a string primary key, status, created_at, and updated_at.
Lists are stored as JSON text. Indexes are named ix_<table>_<column>.
Identifiers stay the existing text ids because the OSS object key is the asset id.
"""

from __future__ import annotations

import sqlite3

SOURCE_TABLE = "sources"
ASSET_TABLE = "assets"

# Columns starx puts on every persisted row. Added to databases created
# before this shape existed.
AUDIT_COLUMNS = (
    ("created_by", "TEXT NOT NULL DEFAULT ''"),
    ("updated_by", "TEXT NOT NULL DEFAULT ''"),
    ("status", "TEXT NOT NULL DEFAULT 'enable'"),
)
SOURCE_METRIC_COLUMNS = (
    ("like_count", "INTEGER"),
    ("collect_count", "INTEGER"),
    ("share_count", "INTEGER"),
    ("reported", "TEXT"),
    ("industry", "TEXT NOT NULL DEFAULT ''"),
)


def create_catalog(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY,
            platform TEXT NOT NULL,
            content_id TEXT NOT NULL,
            source_url TEXT NOT NULL DEFAULT '',
            canonical_url TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            author TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '[]',
            comments TEXT NOT NULL DEFAULT '[]',
            comment_count INTEGER,
            like_count INTEGER,
            collect_count INTEGER,
            share_count INTEGER,
            reported TEXT,
            industry TEXT NOT NULL DEFAULT '',
            via TEXT NOT NULL DEFAULT '',
            source_text TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'enable',
            created_by TEXT NOT NULL DEFAULT '',
            updated_by TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (platform, content_id)
        );
        CREATE TABLE IF NOT EXISTS assets (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            type TEXT NOT NULL,
            ext TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL DEFAULT '',
            remote_url TEXT NOT NULL DEFAULT '',
            poster TEXT,
            oss_key TEXT,
            saved INTEGER NOT NULL DEFAULT 0,
            bytes INTEGER,
            error TEXT,
            category TEXT NOT NULL DEFAULT '',
            labels TEXT NOT NULL DEFAULT '[]',
            note TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'enable',
            created_by TEXT NOT NULL DEFAULT '',
            updated_by TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (source_id, ordinal)
        );
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    ensure_audit(conn)


def ensure_audit(conn: sqlite3.Connection) -> None:
    for table in (SOURCE_TABLE, ASSET_TABLE):
        have = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, ddl in AUDIT_COLUMNS:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    source_columns = {row[1] for row in conn.execute("PRAGMA table_info(sources)")}
    for name, ddl in SOURCE_METRIC_COLUMNS:
        if name not in source_columns:
            conn.execute(f"ALTER TABLE sources ADD COLUMN {name} {ddl}")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_sources_updated_at ON sources (updated_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_sources_status ON sources (status)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_sources_industry ON sources (industry)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_assets_source_id ON assets (source_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_assets_updated_at ON assets (updated_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_assets_status ON assets (status)")
