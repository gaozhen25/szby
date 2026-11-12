"""Start Gallery with several workers and a concurrency cap.

Same idea as fast-soy-admin's run.py: more than one worker, crashed workers
come back, and each worker refuses extra connections instead of queueing
without limit.
"""

from __future__ import annotations

import multiprocessing
import os


def main() -> None:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8790"))
    workers = int(os.getenv("WORKERS", str(min(multiprocessing.cpu_count(), 4))))
    try:
        from granian import Granian
        from granian.constants import Interfaces
        from granian.log import LogLevels
    except ImportError:
        import uvicorn

        uvicorn.run("app.main:app", host=host, port=port, workers=workers)
        return

    Granian(
        target="app.main:app",
        address=host,
        port=port,
        workers=workers,
        reload=False,
        interface=Interfaces.ASGI,
        log_level=LogLevels.info,
        respawn_failed_workers=True,
        respawn_interval=3.5,
        workers_kill_timeout=30,
        workers_lifetime=3600 * 4,
        workers_max_rss=512,
        backpressure=int(os.getenv("BACKPRESSURE", "64")),
        backlog=1024,
    ).serve()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
