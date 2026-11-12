from __future__ import annotations

import asyncio
from collections.abc import Callable
import threading
from typing import Any, TypeVar

T = TypeVar("T")


async def run_in_daemon_thread(function: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run blocking platform I/O without making process shutdown wait for the thread."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[T] = loop.create_future()

    def finish_result(value: T) -> None:
        if not future.done():
            future.set_result(value)

    def finish_error(error: BaseException) -> None:
        if not future.done():
            future.set_exception(error)

    def work() -> None:
        try:
            result = function(*args, **kwargs)
        except BaseException as exc:
            try:
                loop.call_soon_threadsafe(finish_error, exc)
            except RuntimeError:
                pass
        else:
            try:
                loop.call_soon_threadsafe(finish_result, result)
            except RuntimeError:
                pass

    threading.Thread(target=work, name="adapter-platform-io", daemon=True).start()
    return await future
