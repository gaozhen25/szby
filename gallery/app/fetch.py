"""Download a remote media file. OssStore streams bytes straight into the bucket."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import httpx

from app.cdn import host_allowed, referer_for
from app.core.concurrency import DOWNLOAD_CONCURRENCY, download_slots
from app.extract import as_mp4_start

_http_lock = threading.Lock()
_http: httpx.Client | None = None
_CHUNK = 256 * 1024


class SaveError(Exception):
    pass


def plain_fetch_error(detail: str) -> str:
    folded = detail.lower()
    if "peer closed connection" in folded or "incomplete message body" in folded:
        return "视频下载中途被对方断开，已收到一部分但没传完，请再解析一次"
    return " ".join(detail.split())[:300]


def _client() -> httpx.Client:
    global _http
    with _http_lock:
        if _http is None:
            _http = httpx.Client(
                follow_redirects=True,
                # Large origin videos can take a long time; do not cut them off early.
                timeout=httpx.Timeout(3600.0, connect=15.0),
                trust_env=False,
                limits=httpx.Limits(
                    max_connections=max(DOWNLOAD_CONCURRENCY * 2, 16),
                    max_keepalive_connections=DOWNLOAD_CONCURRENCY,
                ),
            )
        return _http


class RemoteStream:
    """File-like body. OSS reads this while the CDN response is still downloading."""

    def __init__(self, resp: httpx.Response, *, want_mp4: bool, max_bytes: int):
        self._iter: Iterator[bytes] = resp.iter_bytes(_CHUNK)
        self._want_mp4 = want_mp4
        self._max_bytes = max_bytes
        self._buf = b""
        self._pending = b""
        self._patched = not want_mp4
        self._done = False
        self.written = 0
        length = resp.headers.get("content-length")
        if length and length.isdigit():
            size = int(length)
            if max_bytes > 0 and size > max_bytes:
                raise SaveError("file too large")
            # oss2 looks for .len when Content-Length is known.
            self.len = size

    def read(self, size: int = -1) -> bytes:
        if size == 0 or self._done:
            return b""
        # Never buffer the whole object in one read(); large videos stream in chunks.
        want = _CHUNK if size is None or size < 0 else size
        out = bytearray()
        while len(out) < want:
            if self._buf:
                take = self._buf[: want - len(out)]
                self._buf = self._buf[len(take) :]
                out.extend(take)
                continue
            piece = self._next_piece()
            if piece is None:
                self._done = True
                break
            self._buf = piece
        return bytes(out)

    def _next_piece(self) -> bytes | None:
        while True:
            try:
                chunk = next(self._iter)
            except StopIteration:
                if self._pending:
                    data = as_mp4_start(self._pending) if self._want_mp4 else self._pending
                    self._pending = b""
                    self._patched = True
                    return data
                return None
            self._account(len(chunk))
            if self._patched:
                return chunk
            self._pending += chunk
            if len(self._pending) < 32:
                continue
            data = as_mp4_start(self._pending)
            self._pending = b""
            self._patched = True
            return data

    def _account(self, nbytes: int) -> None:
        self.written += nbytes
        if self._max_bytes > 0 and self.written > self._max_bytes:
            raise SaveError("file too large")


@contextmanager
def open_remote(url: str, *, want_mp4: bool, max_bytes: int):
    if not host_allowed(url):
        raise SaveError("host not allowed")
    with download_slots:
        try:
            with _client().stream(
                "GET",
                url,
                headers={"User-Agent": "Mozilla/5.0", "Referer": referer_for(url)},
            ) as resp:
                if not host_allowed(str(resp.url)):
                    raise SaveError("host not allowed")
                if resp.status_code >= 400:
                    raise SaveError(f"upstream {resp.status_code}")
                yield RemoteStream(resp, want_mp4=want_mp4, max_bytes=max_bytes)
        except SaveError:
            raise
        except httpx.HTTPError as exc:
            raise SaveError(plain_fetch_error(str(exc))) from exc


def save_remote(url: str, dest: Path, *, want_mp4: bool, max_bytes: int) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    try:
        with open_remote(url, want_mp4=want_mp4, max_bytes=max_bytes) as body:
            with tmp.open("wb") as handle:
                while True:
                    chunk = body.read(_CHUNK)
                    if not chunk:
                        break
                    handle.write(chunk)
        tmp.replace(dest)
    except SaveError:
        tmp.unlink(missing_ok=True)
        raise
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise SaveError(str(exc)) from exc
    return dest.stat().st_size
