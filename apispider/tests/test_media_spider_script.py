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


def test_media_spider_script_uses_tikhub_without_cookie_pool(monkeypatch):
    calls = []

    class StubService:
        async def crawl_by_keyword(self, **options):
            calls.append(options)
            return {"ok": True}

    monkeypatch.setattr(media_spider, "TikHubCrawlService", StubService)

    asyncio.run(media_spider.main())

    assert len(calls) == 1
    assert "cookies" not in calls[0]
    assert calls[0]["platform"] == "dy"
