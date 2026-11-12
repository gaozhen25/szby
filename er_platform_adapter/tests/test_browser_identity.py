from __future__ import annotations

from message_adapter.browser_identity import (
    _identity_for,
    chrome_major_from_user_agent,
    sec_ch_ua_for_user_agent,
)
from message_adapter.platforms.douyin.api import DouyinClient
from message_adapter.platforms.douyin.protocol import _protobuf_headers


def test_browser_identity_uses_reduced_chrome_version_on_macos():
    identity = _identity_for("152.0.7977.83", "Darwin")

    assert "Chrome/152.0.0.0" in identity.user_agent
    assert '"Google Chrome";v="152"' in identity.sec_ch_ua
    assert identity.sec_ch_ua_platform == '"macOS"'


def test_douyin_headers_and_device_version_follow_custom_user_agent():
    user_agent = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
    )
    client = DouyinClient(user_agent=user_agent)
    headers = _protobuf_headers(user_agent)

    assert chrome_major_from_user_agent(user_agent) == 151
    assert client._common_params()["browser_version"] == "151.0.0.0"
    assert client._common_params()["engine_version"] == "151.0"
    assert headers["user-agent"] == user_agent
    assert headers["sec-ch-ua"] == sec_ch_ua_for_user_agent(user_agent)
    assert 'v="151"' in headers["sec-ch-ua"]
