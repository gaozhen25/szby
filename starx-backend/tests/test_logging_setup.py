from pathlib import Path

from app.core.config import Settings
from app.core.logging import configure_logging, get_logger


def test_configure_logging_returns_named_logger():
    configure_logging()

    logger = get_logger("starx.test")

    assert logger.name == "starx.test"
    assert logger.handlers or logger.parent is not None


def test_main_contains_local_uvicorn_entrypoint():
    main_source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")

    assert 'uvicorn.run("app.main:app"' in main_source
    assert 'host="0.0.0.0"' in main_source
    assert "port=settings.port" in main_source
    assert "reload=True" in main_source


def test_backend_port_defaults_to_10102(monkeypatch):
    monkeypatch.delenv("STARX_PORT", raising=False)

    assert Settings(_env_file=None).port == 10102


def test_backend_port_can_be_configured_from_environment(monkeypatch):
    monkeypatch.setenv("STARX_PORT", "12000")

    assert Settings(_env_file=None).port == 12000
