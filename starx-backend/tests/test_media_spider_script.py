import ast
import asyncio
from pathlib import Path

from scripts import media_spider


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "media_spider.py"


def test_media_spider_script_does_not_embed_cookie_literals():
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    embedded = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(
            node.value.value,
            str,
        ):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and "cookie" in target.id.lower():
                embedded.append(target.id)

    assert embedded == []


def test_media_spider_script_uses_mediaspider_cookie_pool(monkeypatch):
    calls = []

    class StubCookiePool:
        def candidates(self, platform):
            assert platform == "dy"
            return ("pool-cookie",)

    class StubService:
        async def crawl_by_keyword(self, **options):
            calls.append(options)
            return type(
                "Result",
                (),
                {"content_count": 0, "contents": []},
            )()

    monkeypatch.setattr(
        media_spider,
        "load_cookie_pool",
        lambda: StubCookiePool(),
    )
    monkeypatch.setattr(media_spider, "MediaCrawlerService", StubService)

    asyncio.run(media_spider.main())

    assert len(calls) == 1
    assert calls[0]["cookies"] == "pool-cookie"
    assert calls[0]["platform"] == "dy"
