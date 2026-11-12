from pathlib import Path

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
    assert "reload=True" in main_source
