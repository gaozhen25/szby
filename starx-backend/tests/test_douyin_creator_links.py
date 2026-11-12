import pytest

from app.services.mediaspider.http_platforms.douyin import client as client_module
from app.services.mediaspider.http_platforms.douyin.client import DouyinClient
from app.services.mediaspider.http_platforms.douyin.help import parse_sec_user_id


def test_parse_redirected_douyin_share_creator_url():
    parsed = parse_sec_user_id(
        "https://www.iesdouyin.com/share/user/MS4wLjABAAAAcreator-id?from=web"
    )
    assert parsed == "MS4wLjABAAAAcreator-id"


def test_parse_douyin_user_path():
    parsed = parse_sec_user_id(
        "https://www.douyin.com/user/MS4wLjABAAAAplain-id"
    )
    assert parsed == "MS4wLjABAAAAplain-id"


def test_creator_bundle_resolves_douyin_short_url(monkeypatch):
    client = object.__new__(DouyinClient)
    short_url = "https://v.douyin.com/creator-code"
    redirected_url = (
        "https://www.iesdouyin.com/share/user/MS4wLjABAAAAcreator-id?from=web"
    )
    monkeypatch.setattr(client, "resolve_short_url", lambda url: redirected_url)
    monkeypatch.setattr(client, "get_user_info", lambda sec_user_id: {})
    monkeypatch.setattr(
        client_module,
        "normalize_creator",
        lambda sec_user_id, raw: {"sec_uid": sec_user_id},
    )

    result = client.get_creator_bundle(short_url, with_posts=False)

    assert result["creator_url"] == (
        "https://www.douyin.com/user/MS4wLjABAAAAcreator-id"
    )
    assert result["creators"] == [{"sec_uid": "MS4wLjABAAAAcreator-id"}]


def test_creator_bundle_rejects_unresolved_douyin_short_url(monkeypatch):
    client = object.__new__(DouyinClient)
    short_url = "https://v.douyin.com/expired-code"
    monkeypatch.setattr(client, "resolve_short_url", lambda url: "")

    with pytest.raises(ValueError, match="短链解析失败"):
        client.get_creator_bundle(short_url, with_posts=False)
