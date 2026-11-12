"""Material library.

A share link is a source: caption, tags, and comments.
Each picture or video from that link is its own asset, and can be
classified and reused without staying attached to the post.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.extract import Extracted
from app.oss import plain_store_error

MAX_BATCH = 20
_EXT = {"jpg", "jpeg", "png", "webp", "mp4", "mov"}
_NAME = re.compile(r"[^\w.-]")


def expand_jobs(text: str | None, texts: list[str]) -> list[str]:
    """One share paste is one job. A blob with several linked lines becomes several jobs."""
    chunks: list[str] = []
    if text and text.strip():
        chunks.append(text.strip())
    for item in texts:
        if item and item.strip():
            chunks.append(item.strip())
    jobs: list[str] = []
    for chunk in chunks:
        lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
        linked = [ln for ln in lines if "http://" in ln.lower() or "https://" in ln.lower()]
        if len(lines) > 1 and len(linked) >= 2:
            jobs.extend(linked)
        else:
            jobs.append(chunk)
    seen: set[str] = set()
    out: list[str] = []
    for job in jobs:
        if job in seen:
            continue
        seen.add(job)
        out.append(job)
    return out


def media_name(content_id: str, media_type: str, ext: str, index: int) -> str:
    safe = _NAME.sub("", content_id)[:60] or "file"
    if media_type == "cover":
        return f"{safe}-cover.{ext}"
    if media_type == "video":
        return f"{safe}.{ext}"
    return f"{safe}-{index + 1}.{ext}"


def _ext_for(media_type: str, ext: str) -> str:
    cleaned = (ext or "").lower().lstrip(".")
    if cleaned == "jpeg":
        cleaned = "jpg"
    if cleaned in _EXT:
        return "jpg" if cleaned == "jpeg" else cleaned
    return "mp4" if media_type == "video" else "jpg"


def stable_id(*parts: str) -> str:
    return hashlib.sha256(":".join(parts).encode()).hexdigest()[:32]


def specs_for(item: Extracted) -> list[dict[str, Any]]:
    """One spec per picture or video. The post itself is not a library row."""
    specs: list[dict[str, Any]] = []
    for index, media in enumerate(item.medias):
        kind = media.type if media.type in ("image", "video") else "image"
        ext = _ext_for(kind, media.ext)
        specs.append(
            {
                "ordinal": index,
                "type": kind,
                "ext": ext,
                "name": media_name(item.content_id, kind, ext, index),
                "remote_url": media.url,
                "poster": item.cover if kind == "video" else (media.cover or media.url),
            }
        )
    return specs


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _loads(raw: str | None, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return fallback


class Library:
    def __init__(self, root: Path, api_key: str | None = None, max_bytes: int | None = None, store: Any | None = None):
        self.root = root
        self.db_path = root / "library.sqlite"
        self.key_path = root / "api_key"
        self._api_key_override = (api_key or "").strip() or None
        if max_bytes is not None:
            self.max_bytes = max_bytes
        else:
            # 0 means no size cap. Large videos stream straight into OSS.
            self.max_bytes = int(os.environ.get("GALLERY_MAX_FILE_BYTES", "0") or "0")
        if store is None:
            from app.oss import build_store

            store = build_store()
        self.store = store
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    @property
    def key_source(self) -> str:
        if self._api_key_override:
            return "override"
        if os.environ.get("GALLERY_API_KEY", "").strip():
            return "env"
        return "file"

    def api_key(self) -> str:
        if self._api_key_override:
            return self._api_key_override
        env = os.environ.get("GALLERY_API_KEY", "").strip()
        if env:
            return env
        with self._lock:
            if self.key_path.exists():
                return self.key_path.read_text(encoding="utf-8").strip()
            self.root.mkdir(parents=True, exist_ok=True)
            key = secrets.token_urlsafe(32)
            self.key_path.write_text(key + "\n", encoding="utf-8")
            self.key_path.chmod(0o600)
            return key

    def check_key(self, got: str) -> bool:
        if not got:
            return False
        expected = self.api_key()
        if len(got) != len(expected):
            return False
        return hmac.compare_digest(got, expected)

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            self.root.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            from app.business.gallery.models import create_catalog

            create_catalog(conn)
            self._migrate_materials(conn)
            conn.commit()
            self._conn = conn
        return self._conn

    def _migrate_materials(self, conn: sqlite3.Connection) -> None:
        done = conn.execute("SELECT value FROM meta WHERE key = 'assets_v1'").fetchone()
        if done:
            return
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "materials" in tables:
            for row in conn.execute("SELECT * FROM materials"):
                self._import_material(conn, row)
        conn.execute("INSERT INTO meta (key, value) VALUES ('assets_v1', '1')")

    def _import_material(self, conn: sqlite3.Connection, row: sqlite3.Row) -> None:
        source_id = row["id"]
        conn.execute(
            """
            INSERT OR IGNORE INTO sources (
                id, platform, content_id, source_url, canonical_url, title, content, author,
                tags, comments, comment_count, via, source_text, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', NULL, ?, ?, ?, ?)
            """,
            (
                source_id,
                row["platform"],
                row["content_id"],
                row["source_url"],
                row["canonical_url"],
                row["title"],
                row["content"],
                row["author"],
                row["tags"],
                row["via"],
                row["source_text"],
                row["created_at"],
                row["updated_at"],
            ),
        )
        files = [item for item in _loads(row["files"], []) if isinstance(item, dict) and item.get("role") != "cover"]
        if not files:
            files = []
            for index, media in enumerate(_loads(row["medias"], [])):
                if not isinstance(media, dict):
                    continue
                files.append(
                    {
                        "index": index,
                        "type": media.get("type") or "image",
                        "ext": media.get("ext") or "jpg",
                        "name": media.get("name") or f"file-{index + 1}",
                        "source_url": media.get("url") or "",
                    }
                )
        for spec in files:
            ordinal = int(spec.get("index") or 0)
            kind = spec.get("type") if spec.get("type") in ("image", "video") else "image"
            conn.execute(
                """
                INSERT OR IGNORE INTO assets (
                    id, source_id, ordinal, type, ext, name, remote_url, poster, oss_key, saved, bytes, error,
                    category, labels, note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?)
                """,
                (
                    stable_id(row["platform"], row["content_id"], str(ordinal)),
                    source_id,
                    ordinal,
                    kind,
                    spec.get("ext") or "",
                    spec.get("name") or "",
                    spec.get("source_url") or "",
                    row["cover"],
                    spec.get("oss_key"),
                    1 if spec.get("saved") and spec.get("oss_key") else 0,
                    spec.get("bytes"),
                    spec.get("error"),
                    row["labels"] or "[]",
                    row["note"] or "",
                    row["created_at"],
                    row["updated_at"],
                ),
            )

    def upsert(
        self,
        item: Extracted,
        *,
        source_text: str,
        download: bool,
        refresh_files: bool,
        report: dict[str, Any] | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        specs = specs_for(item)
        now = _now()
        source_id = stable_id(item.platform, item.content_id)
        created_any = False
        asset_ids: list[str] = []
        with self._lock:
            conn = self._db()
            existing = conn.execute(
                "SELECT * FROM sources WHERE platform = ? AND content_id = ?",
                (item.platform, item.content_id),
            ).fetchone()
            created_at = now if existing is None else existing["created_at"]
            if existing is None:
                created_any = True
            else:
                source_id = existing["id"]
            counts = (report or {}).get("counts") or {}
            extra = (report or {}).get("extra") or {}
            comment_count = counts["comment_count"] if "comment_count" in counts else item.comment_count
            if report and "comments" in report:
                comment_rows = report["comments"]
            else:
                comment_rows = [comment.to_dict() for comment in item.comments]
            previous = _loads(existing["reported"], {}) if existing is not None else {}
            reported = {**previous, **counts, **extra} if report else None
            conn.execute(
                """
                INSERT INTO sources (
                    id, platform, content_id, source_url, canonical_url, title, content, author,
                    tags, comments, comment_count, like_count, collect_count, share_count, reported,
                    via, source_text, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, content_id) DO UPDATE SET
                    source_url = excluded.source_url,
                    canonical_url = excluded.canonical_url,
                    title = excluded.title,
                    content = excluded.content,
                    author = excluded.author,
                    tags = excluded.tags,
                    comments = excluded.comments,
                    comment_count = COALESCE(excluded.comment_count, sources.comment_count),
                    like_count = COALESCE(excluded.like_count, sources.like_count),
                    collect_count = COALESCE(excluded.collect_count, sources.collect_count),
                    share_count = COALESCE(excluded.share_count, sources.share_count),
                    reported = COALESCE(excluded.reported, sources.reported),
                    via = excluded.via,
                    source_text = excluded.source_text,
                    updated_at = excluded.updated_at
                """,
                (
                    source_id,
                    item.platform,
                    item.content_id,
                    item.source_url,
                    item.canonical_url,
                    item.title,
                    item.content,
                    item.author,
                    json.dumps(item.tags, ensure_ascii=False),
                    json.dumps(comment_rows, ensure_ascii=False),
                    comment_count,
                    counts.get("like_count"),
                    counts.get("collect_count"),
                    counts.get("share_count"),
                    json.dumps(reported, ensure_ascii=False) if reported else None,
                    item.via,
                    source_text[:4000],
                    created_at,
                    now,
                ),
            )
            planned: list[dict[str, Any]] = []
            for spec in specs:
                asset_id = stable_id(item.platform, item.content_id, str(spec["ordinal"]))
                prev = conn.execute(
                    "SELECT * FROM assets WHERE source_id = ? AND ordinal = ?",
                    (source_id, spec["ordinal"]),
                ).fetchone()
                if prev is None:
                    created_any = True
                    note, labels, category, asset_created = "", "[]", "", now
                    previous: dict[str, Any] = {}
                else:
                    asset_id = prev["id"]
                    note = prev["note"]
                    labels = prev["labels"]
                    category = prev["category"]
                    asset_created = prev["created_at"]
                    previous = dict(prev)
                planned.append(
                    {
                        "asset_id": asset_id,
                        "spec": spec,
                        "previous": previous,
                        "note": note,
                        "labels": labels,
                        "category": category,
                        "asset_created": asset_created,
                    }
                )
                asset_ids.append(asset_id)
            conn.commit()

        from app.core.concurrency import DOWNLOAD_CONCURRENCY, map_parallel

        def store_planned(row: dict[str, Any]) -> dict[str, Any]:
            return self._store_one(
                row["asset_id"],
                row["spec"],
                row["previous"],
                download=download,
                refresh=refresh_files,
            )

        stored_rows = map_parallel(store_planned, planned, workers=DOWNLOAD_CONCURRENCY)

        with self._lock:
            conn = self._db()
            for row, stored in zip(planned, stored_rows, strict=True):
                spec = row["spec"]
                labels = row["labels"]
                conn.execute(
                    """
                    INSERT INTO assets (
                        id, source_id, ordinal, type, ext, name, remote_url, poster, oss_key, saved, bytes, error,
                        category, labels, note, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_id, ordinal) DO UPDATE SET
                        type = excluded.type,
                        ext = excluded.ext,
                        name = excluded.name,
                        remote_url = excluded.remote_url,
                        poster = excluded.poster,
                        oss_key = excluded.oss_key,
                        saved = excluded.saved,
                        bytes = excluded.bytes,
                        error = excluded.error,
                        updated_at = excluded.updated_at
                    """,
                    (
                        row["asset_id"],
                        source_id,
                        spec["ordinal"],
                        spec["type"],
                        stored["ext"],
                        spec["name"],
                        spec["remote_url"],
                        spec["poster"],
                        stored["oss_key"],
                        stored["saved"],
                        stored["bytes"],
                        stored["error"],
                        row["category"],
                        labels if isinstance(labels, str) else json.dumps(labels, ensure_ascii=False),
                        row["note"],
                        row["asset_created"],
                        now,
                    ),
                )
            conn.commit()
            source = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
            assets = [conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone() for asset_id in asset_ids]
        return created_any, {
            "source": self._public_source(source),
            "assets": [self._public_asset(asset, source) for asset in assets],
        }

    def _store_one(
        self,
        asset_id: str,
        spec: dict[str, Any],
        prev: dict[str, Any],
        *,
        download: bool,
        refresh: bool,
    ) -> dict[str, Any]:
        same = bool(prev.get("remote_url") == spec["remote_url"] and prev.get("saved") and prev.get("oss_key"))
        rec: dict[str, Any] = {"oss_key": None, "saved": 0, "bytes": None, "error": None, "ext": spec["ext"]}
        if download and not (same and not refresh):
            try:
                key, nbytes = self._put_spec(asset_id, spec)
                previous = prev.get("oss_key")
                if previous and previous != key:
                    try:
                        self.store.delete(previous)
                    except Exception:
                        pass
                rec.update(oss_key=key, saved=1, bytes=nbytes, error=None)
            except Exception as exc:
                message = plain_store_error(str(exc))
                if prev.get("saved") and prev.get("oss_key"):
                    rec.update(
                        oss_key=prev.get("oss_key"),
                        saved=1,
                        bytes=prev.get("bytes"),
                        ext=prev.get("ext") or spec["ext"],
                        error=message,
                    )
                else:
                    rec["error"] = message
        elif prev.get("oss_key") and (same or not download):
            rec.update(oss_key=prev.get("oss_key"), saved=1, bytes=prev.get("bytes"), ext=prev.get("ext") or spec["ext"])
            if not download and not same:
                rec["error"] = "remote url changed; file not refreshed"
        return rec

    def _put_spec(self, asset_id: str, spec: dict[str, Any]) -> tuple[str, int]:
        if not getattr(self.store, "configured", False):
            missing = "、".join(self.store.status().get("missing") or [])
            raise RuntimeError(f"OSS 未配置。请设置 {missing}" if missing else "OSS 未配置")
        key = self.store.object_key(asset_id, 0, spec["ext"])
        nbytes = self.store.put_remote(
            key,
            spec["remote_url"],
            want_mp4=spec["ext"] == "mp4",
            max_bytes=self.max_bytes,
        )
        return key, nbytes

    def file_url(self, asset_id: str, index: int = 0) -> tuple[str, str, Any] | None:
        if index not in (0,):
            return None
        with self._lock:
            row = self._asset_row(asset_id)
        if row is None or not row["saved"] or not row["oss_key"]:
            return None
        from app.oss import content_type

        return str(row["name"] or "file"), content_type(str(row["ext"] or "")), self.store.read(row["oss_key"])

    def get(self, asset_id: str) -> dict[str, Any] | None:
        with self._lock:
            found = self._joined(asset_id)
        if found is None:
            return None
        asset, source = found
        return self._public_asset(asset, source)

    def delete(self, asset_id: str) -> bool:
        with self._lock:
            conn = self._db()
            row = self._asset_row(asset_id)
            if row is None:
                return False
            oss_key = row["oss_key"]
            source_id = row["source_id"]
            conn.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
            left = conn.execute("SELECT COUNT(*) FROM assets WHERE source_id = ?", (source_id,)).fetchone()[0]
            if left == 0:
                conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
            conn.commit()
        if oss_key:
            try:
                self.store.delete(oss_key)
            except Exception:
                pass
        return True

    def set_source_industry(self, source_id: str, industry: str) -> None:
        label = (industry or "").strip()[:40]
        if not source_id or not label:
            return
        with self._lock:
            conn = self._db()
            conn.execute(
                "UPDATE sources SET industry = ?, updated_at = ? WHERE id = ?",
                (label, _now(), source_id),
            )
            conn.commit()

    def patch(
        self,
        asset_id: str,
        *,
        note: str | None,
        labels: list[str] | None,
        category: str | None = None,
        industry: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            conn = self._db()
            row = self._asset_row(asset_id)
            if row is None:
                return None
            next_note = row["note"] if note is None else note
            next_labels = _loads(row["labels"], []) if labels is None else labels
            next_category = row["category"] if category is None else category
            conn.execute(
                "UPDATE assets SET note = ?, labels = ?, category = ?, updated_at = ? WHERE id = ?",
                (next_note, json.dumps(next_labels, ensure_ascii=False), next_category, _now(), asset_id),
            )
            if industry is not None:
                conn.execute(
                    "UPDATE sources SET industry = ?, updated_at = ? WHERE id = ?",
                    (industry.strip()[:40], _now(), row["source_id"]),
                )
            conn.commit()
            found = self._joined(asset_id)
        if found is None:
            return None
        asset, source = found
        return self._public_asset(asset, source)

    def query(
        self,
        *,
        q: str = "",
        platform: str = "",
        kind: str = "",
        tag: str = "",
        category: str = "",
        industry: str = "",
        source_id: str = "",
        group: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        media_type = kind if kind in ("image", "video") else ""
        where = ["1=1"]
        args: list[Any] = []
        if platform:
            where.append("sources.platform = ?")
            args.append(platform)
        if media_type:
            where.append("assets.type = ?")
            args.append(media_type)
        if category:
            where.append("assets.category = ?")
            args.append(category)
        if industry:
            where.append("sources.industry = ?")
            args.append(industry)
        if source_id:
            where.append("assets.source_id = ?")
            args.append(source_id)
        if tag:
            where.append(
                "(EXISTS (SELECT 1 FROM json_each(sources.tags) WHERE json_each.value = ?) "
                "OR EXISTS (SELECT 1 FROM json_each(assets.labels) WHERE json_each.value = ?) "
                "OR assets.category = ?)"
            )
            args.extend([tag, tag, tag])
        if q:
            like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            where.append(
                "(sources.title LIKE ? ESCAPE '\\' OR sources.content LIKE ? ESCAPE '\\' "
                "OR sources.author LIKE ? ESCAPE '\\' OR sources.content_id LIKE ? ESCAPE '\\' "
                "OR sources.industry LIKE ? ESCAPE '\\' "
                "OR assets.note LIKE ? ESCAPE '\\' OR assets.category LIKE ? ESCAPE '\\' "
                "OR EXISTS (SELECT 1 FROM json_each(sources.tags) WHERE json_each.value LIKE ? ESCAPE '\\'))"
            )
            args.extend([like, like, like, like, like, like, like, like])
        clause = " AND ".join(where)
        join = "FROM assets JOIN sources ON sources.id = assets.source_id"
        with self._lock:
            conn = self._db()
            if group == "source":
                return self._query_works(conn, join, clause, args, limit, offset)
            total = conn.execute(f"SELECT COUNT(*) {join} WHERE {clause}", args).fetchone()[0]
            rows = conn.execute(
                f"SELECT assets.id AS id {join} WHERE {clause} ORDER BY assets.updated_at DESC, assets.id DESC LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()
            items = []
            for row in rows:
                found = self._joined(row["id"])
                if found:
                    items.append(self._public_asset(*found))
        return {"ok": True, "total": total, "limit": limit, "offset": offset, "items": items}

    def _query_works(
        self,
        conn: sqlite3.Connection,
        join: str,
        clause: str,
        args: list[Any],
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        """One row per work. Search still matches every asset; each row then includes all of that work's assets."""
        asset_total = conn.execute(f"SELECT COUNT(*) {join} WHERE {clause}", args).fetchone()[0]
        total = conn.execute(f"SELECT COUNT(DISTINCT assets.source_id) {join} WHERE {clause}", args).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT assets.source_id AS source_id, MAX(assets.updated_at) AS updated_at
            {join}
            WHERE {clause}
            GROUP BY assets.source_id
            ORDER BY updated_at DESC, source_id DESC
            LIMIT ? OFFSET ?
            """,
            [*args, limit, offset],
        ).fetchall()
        items = []
        for row in rows:
            source = conn.execute("SELECT * FROM sources WHERE id = ?", (row["source_id"],)).fetchone()
            if source is None:
                continue
            asset_rows = conn.execute(
                "SELECT id FROM assets WHERE source_id = ? ORDER BY ordinal ASC, id ASC",
                (row["source_id"],),
            ).fetchall()
            assets = []
            for asset_row in asset_rows:
                found = self._joined(asset_row["id"])
                if found:
                    assets.append(self._public_asset(*found))
            items.append({
                "source": self._public_source(source),
                "assets": assets,
                "updated_at": row["updated_at"],
            })
        return {
            "ok": True,
            "total": int(total),
            "asset_total": int(asset_total),
            "limit": limit,
            "offset": offset,
            "grouped": "source",
            "items": items,
        }

    def summary(self) -> dict[str, Any]:
        with self._lock:
            conn = self._db()
            total = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
            rows = conn.execute(
                """
                SELECT sources.platform AS platform, assets.type AS type, COUNT(*) AS c
                FROM assets JOIN sources ON sources.id = assets.source_id
                GROUP BY sources.platform, assets.type
                """
            ).fetchall()
            industry_rows = conn.execute(
                """
                SELECT sources.industry AS industry, COUNT(*) AS c
                FROM assets JOIN sources ON sources.id = assets.source_id
                WHERE TRIM(COALESCE(sources.industry, '')) != ''
                GROUP BY sources.industry
                ORDER BY c DESC, sources.industry ASC
                """
            ).fetchall()
        out: dict[str, Any] = {"total": int(total), "douyin": 0, "xhs": 0, "image": 0, "video": 0, "industries": []}
        for row in rows:
            count = int(row["c"])
            if row["platform"] in out:
                out[row["platform"]] += count
            if row["type"] in out:
                out[row["type"]] += count
        out["industries"] = [
            {"name": str(row["industry"]), "count": int(row["c"])}
            for row in industry_rows
            if row["industry"]
        ]
        return out

    def _asset_row(self, asset_id: str) -> sqlite3.Row | None:
        if not re.fullmatch(r"[0-9a-f]{32}", asset_id):
            return None
        return self._db().execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()

    def _joined(self, asset_id: str) -> tuple[sqlite3.Row, sqlite3.Row] | None:
        asset = self._asset_row(asset_id)
        if asset is None:
            return None
        source = self._db().execute("SELECT * FROM sources WHERE id = ?", (asset["source_id"],)).fetchone()
        if source is None:
            return None
        return asset, source

    def _public_source(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "platform": row["platform"],
            "content_id": row["content_id"],
            "source_url": row["source_url"],
            "canonical_url": row["canonical_url"],
            "title": row["title"],
            "content": row["content"],
            "author": row["author"],
            "tags": _loads(row["tags"], []),
            "comments": _loads(row["comments"], []),
            "comment_count": row["comment_count"],
            "like_count": row["like_count"],
            "collect_count": row["collect_count"],
            "share_count": row["share_count"],
            "reported": _loads(row["reported"], {}),
            "industry": (row["industry"] or "") if "industry" in row.keys() else "",
            "via": row["via"],
        }

    def _public_asset(self, asset: sqlite3.Row, source: sqlite3.Row) -> dict[str, Any]:
        saved = bool(asset["saved"] and asset["oss_key"])
        href = f"/api/v1/library/{asset['id']}/file" if saved else None
        return {
            "id": asset["id"],
            "type": asset["type"],
            "ordinal": asset["ordinal"],
            "name": asset["name"],
            "ext": asset["ext"],
            "remote_url": asset["remote_url"],
            "poster": asset["poster"],
            "oss_key": asset["oss_key"] or None,
            "saved": saved,
            "bytes": asset["bytes"] if saved else None,
            "href": href,
            "error": asset["error"],
            "category": asset["category"] or "",
            "labels": _loads(asset["labels"], []),
            "note": asset["note"] or "",
            "created_at": asset["created_at"],
            "updated_at": asset["updated_at"],
            "source": self._public_source(source),
        }
