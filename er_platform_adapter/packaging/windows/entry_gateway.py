import sys


def _force_utf8_stdio() -> None:
    """Make the frozen CLI survive any Windows console code page (cp1252/GBK...)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


_force_utf8_stdio()

from adapter_gateway.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
