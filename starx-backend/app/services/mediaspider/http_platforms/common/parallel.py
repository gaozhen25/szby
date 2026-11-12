# -*- coding: utf-8 -*-
"""多关键词并行：每个 cookie 账号独占一个 worker，从队列取关键词。"""

from __future__ import annotations

import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Empty, Queue
from typing import Callable, Dict, List, Optional, Tuple, TypeVar

from .cookies import CookieAccount

T = TypeVar("T")


def run_parallel_keywords(
    keywords: List[str],
    accounts: List[CookieAccount],
    worker_fn: Callable[[str, CookieAccount], T],
    *,
    max_workers: int = 0,
) -> Tuple[Dict[str, T], Dict[str, str]]:
    """
    按 cookie 数并行处理关键词。

    每个账号同一时刻只跑一个任务；多关键词排队消费。
    返回 (成功结果 dict, 失败信息 dict)。
    """
    if not keywords:
        return {}, {}
    if not accounts:
        raise RuntimeError("无可用 cookie 账号，无法并行")

    workers = max_workers if max_workers and max_workers > 0 else len(accounts)
    workers = max(1, min(workers, len(accounts), len(keywords)))
    selected = accounts[:workers]

    q: Queue[str] = Queue()
    for kw in keywords:
        q.put(kw)

    results: Dict[str, T] = {}
    errors: Dict[str, str] = {}

    def _worker(account: CookieAccount) -> None:
        while True:
            try:
                keyword = q.get_nowait()
            except Empty:
                return
            try:
                results[keyword] = worker_fn(keyword, account)
            except Exception as exc:
                errors[keyword] = str(exc)
                print(
                    f"[parallel][{account.name}] {keyword}: {exc}",
                    file=sys.stderr,
                )
                traceback.print_exc(file=sys.stderr)
            finally:
                q.task_done()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_worker, acc) for acc in selected]
        for fut in as_completed(futures):
            fut.result()

    return results, errors
