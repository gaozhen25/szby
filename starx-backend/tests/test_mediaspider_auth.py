import asyncio

import pytest

from app.services.mediaspider.models import CrawlerAuthenticationError
from app.services.mediaspider.runtime.auth import ensure_authenticated


def test_existing_login_state_skips_login_and_refresh():
    calls = []

    async def probe():
        calls.append("probe")
        return True

    async def login():
        calls.append("login")

    async def refresh():
        calls.append("refresh")

    asyncio.run(
        ensure_authenticated(
            platform="xhs",
            login_type="cookie",
            probe=probe,
            login=login,
            refresh=refresh,
        )
    )

    assert calls == ["probe"]


def test_cookie_login_refreshes_before_second_probe():
    calls = []
    probe_results = iter([False, True])

    async def probe():
        calls.append("probe")
        return next(probe_results)

    async def login():
        calls.append("login")

    async def refresh():
        calls.append("refresh")

    asyncio.run(
        ensure_authenticated(
            platform="xhs",
            login_type="cookie",
            probe=probe,
            login=login,
            refresh=refresh,
        )
    )

    assert calls == ["probe", "login", "refresh", "probe"]


def test_cookie_login_fails_only_after_second_probe():
    calls = []

    async def probe():
        calls.append("probe")
        return False

    async def login():
        calls.append("login")

    async def refresh():
        calls.append("refresh")

    with pytest.raises(CrawlerAuthenticationError) as exc_info:
        asyncio.run(
            ensure_authenticated(
                platform="dy",
                login_type="cookie",
                probe=probe,
                login=login,
                refresh=refresh,
            )
        )

    assert exc_info.value.platform == "dy"
    assert calls == ["probe", "login", "refresh", "probe"]


@pytest.mark.parametrize("login_type", ["phone", "qrcode"])
def test_interactive_login_keeps_single_pre_login_probe(login_type):
    calls = []

    async def probe():
        calls.append("probe")
        return False

    async def login():
        calls.append("login")

    async def refresh():
        calls.append("refresh")

    asyncio.run(
        ensure_authenticated(
            platform="dy",
            login_type=login_type,
            probe=probe,
            login=login,
            refresh=refresh,
        )
    )

    assert calls == ["probe", "login", "refresh"]


@pytest.mark.parametrize(
    "failing_action",
    ["initial_probe", "login", "refresh", "second_probe"],
)
def test_auth_action_exception_is_not_reclassified(failing_action):
    error = RuntimeError("auth action failed")
    probe_count = 0

    async def probe():
        nonlocal probe_count
        probe_count += 1
        if failing_action == "initial_probe" and probe_count == 1:
            raise error
        if failing_action == "second_probe" and probe_count == 2:
            raise error
        return False

    async def login():
        if failing_action == "login":
            raise error

    async def refresh():
        if failing_action == "refresh":
            raise error

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(
            ensure_authenticated(
                platform="ks",
                login_type="cookie",
                probe=probe,
                login=login,
                refresh=refresh,
            )
        )

    assert exc_info.value is error
