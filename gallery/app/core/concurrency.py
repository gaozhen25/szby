"""Bound the heavy work the way fast-soy-admin bounds a worker.

Parse slots limit how many share-link extracts run at once.
Download slots limit how many media files are pulled at once.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypeVar, cast

T = TypeVar("T")
R = TypeVar("R")

PARSE_CONCURRENCY = max(1, int(os.getenv("PARSE_CONCURRENCY", "8")))
DOWNLOAD_CONCURRENCY = max(1, int(os.getenv("DOWNLOAD_CONCURRENCY", "8")))

parse_slots = asyncio.Semaphore(PARSE_CONCURRENCY)
download_slots = threading.BoundedSemaphore(DOWNLOAD_CONCURRENCY)


async def run_parse(func: Callable[..., T], *args: object) -> T:
    async with parse_slots:
        return await asyncio.to_thread(func, *args)


def map_parallel(func: Callable[[T], R], items: Iterable[T], *, workers: int) -> list[R]:
    """Run func on every item, keeping order. One worker when the batch is small."""
    jobs = list(items)
    if not jobs:
        return []
    size = max(1, min(workers, len(jobs)))
    if size == 1:
        return [func(item) for item in jobs]
    out: list[R | None] = [None] * len(jobs)
    with ThreadPoolExecutor(max_workers=size) as pool:
        futures = {pool.submit(func, item): index for index, item in enumerate(jobs)}
        for future in as_completed(futures):
            out[futures[future]] = future.result()
    return cast(list[R], out)
