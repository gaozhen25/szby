"""Turn share text into a watchable result, or into assets in the catalog."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.extract import ExtractError, Extracted, extract
from app.library import MAX_BATCH, Library, expand_jobs
from app.schemas import BatchParseIn, ReportItem


class IntakeError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def watch_one(text: str) -> Extracted:
    try:
        return extract(text)
    except ExtractError as exc:
        raise IntakeError(422, exc.code, exc.message) from exc


def _plain_count(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value >= 0 and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _reported_comments(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    rows: list[dict[str, Any]] = []
    for raw in value[:200]:
        if not isinstance(raw, dict):
            continue
        author = str(raw.get("nickname") or raw.get("author") or "").strip()[:80]
        text = str(raw.get("content") if raw.get("content") is not None else raw.get("text") or "").strip()[:2000]
        if not author and not text:
            continue
        row: dict[str, Any] = {"author": author, "text": text}
        zan = _plain_count(raw.get("zanCount", raw.get("like_count")))
        if zan is not None:
            row["zanCount"] = zan
        if "isZan" in raw:
            row["isZan"] = bool(raw["isZan"])
        if "isAuthor" in raw:
            row["isAuthor"] = bool(raw["isAuthor"])
        ip = raw.get("ip")
        if isinstance(ip, str) and ip.strip():
            row["ip"] = ip.strip()[:40]
        rows.append(row)
    return rows


def report_of(item: ReportItem) -> dict[str, Any] | None:
    """Keep the caller's numbers. Anything that is not a count stays in extra."""
    raw = item.model_dump()
    raw.pop("text", None)
    raw.update(item.model_extra or {})
    comments = _reported_comments(raw.pop("comments", None)) if "comments" in raw else None
    counts: dict[str, int] = {}
    extra: dict[str, Any] = {}
    for key, value in raw.items():
        if value is None:
            continue
        count = _plain_count(value) if key in ("like_count", "collect_count", "share_count", "comment_count") else None
        if count is not None:
            counts[key] = count
        else:
            extra[key] = value
    if not counts and not extra and comments is None:
        return None
    stored: dict[str, Any] = {"counts": counts, "extra": extra}
    if comments is not None:
        stored["comments"] = comments
    return stored


def coerce_batch(payload: Any) -> BatchParseIn:
    """Accept the caller's own record, a list of records, or the wrapped batch."""
    if isinstance(payload, list):
        return BatchParseIn(items=[_one_report(item) for item in payload])
    if isinstance(payload, dict) and "items" not in payload and "texts" not in payload and payload.get("text") is None:
        if any(payload.get(name) for name in ("shareLink", "share_link", "share_url")):
            return BatchParseIn(items=[_one_report(payload)])
    try:
        return BatchParseIn.model_validate(payload)
    except ValidationError as exc:
        raise IntakeError(422, "invalid_body", "请求格式不正确") from exc


def _one_report(item: Any) -> ReportItem:
    if not isinstance(item, dict):
        raise IntakeError(422, "invalid_body", "每条上报必须是对象")
    try:
        return ReportItem.model_validate(item)
    except ValidationError as exc:
        raise IntakeError(422, "invalid_body", "缺少分享链接 shareLink") from exc


def parse_batch(lib: Library, body: BatchParseIn) -> dict:
    for item in body.texts:
        if len(item) > 20_000:
            raise IntakeError(422, "text_too_long", "单条文本过长")
    jobs: list[tuple[str, dict[str, Any] | None]] = [(text, None) for text in expand_jobs(body.text, body.texts)]
    jobs.extend((item.text, report_of(item)) for item in body.items)
    if not jobs:
        raise IntakeError(422, "empty", "没有可解析的链接")
    if len(jobs) > MAX_BATCH:
        raise IntakeError(422, "too_many", f"一次最多解析 {MAX_BATCH} 条")

    from app.core.concurrency import PARSE_CONCURRENCY, map_parallel

    def one(job: tuple[int, str, dict[str, Any] | None]) -> dict[str, Any]:
        index, text, report = job
        try:
            got = extract(text)
        except ExtractError as exc:
            return {
                "index": index,
                "ok": False,
                "input": text[:180],
                "error": {"code": exc.code, "message": exc.message},
            }
        created, saved = lib.upsert(
            got,
            source_text=text,
            download=body.download,
            refresh_files=body.refresh_files,
            report=report,
        )
        from app.industry import classify_industry

        industry = classify_industry(got.title or got.content, got.tags, got.content)
        if industry:
            lib.set_source_industry(saved["source"]["id"], industry)
            saved["source"]["industry"] = industry
            for asset in saved["assets"]:
                asset["source"]["industry"] = industry
        return {
            "index": index,
            "ok": True,
            "created": created,
            "input": text[:180],
            "source": saved["source"],
            "assets": saved["assets"],
        }

    results = map_parallel(
        one,
        [(index, text, report) for index, (text, report) in enumerate(jobs)],
        workers=PARSE_CONCURRENCY,
    )
    saved_count = sum(1 for item in results if item["ok"])
    return {
        "ok": True,
        "total": len(results),
        "saved": saved_count,
        "failed": len(results) - saved_count,
        "results": results,
    }
