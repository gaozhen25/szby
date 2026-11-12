import asyncio

from app.services.mediaspider.platforms.douyin import core as douyin_core
from app.services.mediaspider.platforms.douyin.core import DouYinCrawler
from app.services.mediaspider.platforms.douyin.help import parse_creator_info_from_url
from app.services.mediaspider.platforms.douyin import help as douyin_help


def test_parse_redirected_douyin_share_creator_url():
    parsed = parse_creator_info_from_url(
        "https://www.iesdouyin.com/share/user/MS4wLjABAAAAcreator-id?from=web"
    )

    assert parsed.sec_user_id == "MS4wLjABAAAAcreator-id"


def test_creator_crawler_expands_douyin_short_link(monkeypatch):
    calls = []

    class FakeClient:
        async def resolve_short_url(self, url):
            calls.append(("resolve", url))
            return "https://www.iesdouyin.com/share/user/MS4wLjABAAAAresolved"

        async def get_user_info(self, sec_user_id):
            calls.append(("profile", sec_user_id))
            return {"nickname": "短链博主"}

        async def get_all_user_aweme_posts(self, sec_user_id, callback, max_count):
            calls.append(("posts", sec_user_id, max_count))
            return []

    saved = []

    async def fake_save_creator(user_id, creator):
        saved.append((user_id, creator))

    async def fake_batch_comments(_video_ids):
        return None

    monkeypatch.setattr(
        douyin_core.config,
        "DY_CREATOR_ID_LIST",
        ["https://v.douyin.com/short-code"],
    )
    monkeypatch.setattr(douyin_core.config, "CRAWLER_MAX_NOTES_COUNT", 10)
    monkeypatch.setattr(douyin_core.douyin_store, "save_creator", fake_save_creator)
    crawler = DouYinCrawler()
    crawler.dy_client = FakeClient()
    crawler.batch_get_note_comments = fake_batch_comments

    asyncio.run(crawler.get_creators_and_videos())

    assert calls == [
        ("resolve", "https://v.douyin.com/short-code"),
        ("profile", "MS4wLjABAAAAresolved"),
        ("posts", "MS4wLjABAAAAresolved", 10),
    ]
    assert saved == [
        ("MS4wLjABAAAAresolved", {"nickname": "短链博主"})
    ]


def test_douyin_signing_prefers_playwright_page_over_execjs(monkeypatch):
    calls = []

    class FakePage:
        async def evaluate(self, expression, argument=None):
            calls.append(("evaluate", expression, argument))
            if argument is None:
                return False
            return "browser-signature"

        async def add_script_tag(self, *, content):
            calls.append(("inject", bool(content)))

    def fail_execjs(*_args):
        raise AssertionError("Playwright 页面可用时不应调用 ExecJS")

    monkeypatch.setattr(douyin_help, "get_a_bogus_from_js", fail_execjs)

    result = asyncio.run(
        douyin_help.get_a_bogus(
            "/aweme/v1/web/user/profile/other/",
            "sec_user_id=test",
            {},
            "Mozilla/5.0",
            FakePage(),
        )
    )

    assert result == "browser-signature"
    assert calls[0][0] == "evaluate"
    assert calls[1] == ("inject", True)
    assert calls[2][2][0] == "sign_datail"
