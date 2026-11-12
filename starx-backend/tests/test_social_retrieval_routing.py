from types import SimpleNamespace

from app.core.config import Settings
from app.services.social_retrieval import (
    RetrievalBackend,
    RetrievalMode,
    backend_for_platform,
    normalize_retrieval_mode,
)


def test_hybrid_routes_supported_platforms_to_mediaspider_and_keeps_kuaishou():
    configured = SimpleNamespace(social_retrieval_provider="hybrid")

    assert backend_for_platform(configured, "dy") == RetrievalBackend.MEDIASPIDER
    assert backend_for_platform(configured, "xhs") == RetrievalBackend.MEDIASPIDER
    assert backend_for_platform(configured, "ks") == RetrievalBackend.TIKHUB


def test_tikhub_mode_keeps_every_platform_on_tikhub():
    for platform in ("dy", "xhs", "ks"):
        assert (
            backend_for_platform("tikhub", platform)
            == RetrievalBackend.TIKHUB
        )


def test_legacy_and_invalid_modes_normalize_to_safe_hybrid_mode():
    assert normalize_retrieval_mode("legacy") == RetrievalMode.HYBRID
    assert normalize_retrieval_mode("unknown") == RetrievalMode.TIKHUB


def test_settings_keep_safe_tikhub_default_but_accept_hybrid_rollout(monkeypatch):
    monkeypatch.delenv("STARX_SOCIAL_RETRIEVAL_PROVIDER", raising=False)
    monkeypatch.delenv("SOCIAL_RETRIEVAL_PROVIDER", raising=False)
    assert Settings(_env_file=None).social_retrieval_provider == "tikhub"

    monkeypatch.setenv("STARX_SOCIAL_RETRIEVAL_PROVIDER", "hybrid")
    assert Settings(_env_file=None).social_retrieval_provider == "hybrid"

    monkeypatch.setenv("STARX_SOCIAL_RETRIEVAL_PROVIDER", "legacy")
    assert Settings(_env_file=None).social_retrieval_provider == "hybrid"
