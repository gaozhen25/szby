from __future__ import annotations

import os
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None


_IS_WINDOWS = os.name == "nt"


class SingleInstanceLock:
    def __init__(self, path: Path):
        self.path = path
        self._file = None

    def __enter__(self) -> "SingleInstanceLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a+", encoding="utf-8")
        try:
            self._acquire()
        except ImportError as exc:
            self._file.close()
            self._file = None
            raise RuntimeError(f"adapter platform file locking is unavailable (lock: {self.path})") from exc
        except OSError as exc:
            self._file.close()
            self._file = None
            raise RuntimeError(f"adapter platform slot is already running (lock: {self.path})") from exc
        try:
            self._file.seek(0)
            self._file.truncate()
            self._file.write(str(os.getpid()))
            self._file.flush()
        except BaseException:
            self.__exit__()
            raise
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        return self

    def _acquire(self) -> None:
        assert self._file is not None
        if _IS_WINDOWS:
            import msvcrt

            self._file.seek(0, os.SEEK_END)
            if self._file.tell() == 0:
                self._file.write("\0")
                self._file.flush()
            self._file.seek(0)
            msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            return

        import fcntl

        fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _release(self) -> None:
        assert self._file is not None
        if _IS_WINDOWS:
            import msvcrt

            self._file.seek(0)
            msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            return

        import fcntl

        fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)

    def __exit__(self, *args) -> None:  # noqa: ANN002
        if self._file is None:
            return
        try:
            self._release()
        except (ImportError, OSError):
            pass
        finally:
            self._file.close()
            self._file = None
