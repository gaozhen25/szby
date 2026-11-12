# -*- coding: utf-8 -*-

from unittest.mock import AsyncMock, patch

import pytest

from sdk.extractor import creator_ex, keyword_ex, keyword_ex_async


@pytest.mark.asyncio
async def test_keyword_ex_async_returns_api_dict():
    payload = {
        "code": 0,
        "message": "ok",
        "data": {
            "keywords": ["美女"],
            "notes": [{"note_id": "1", "title": "测试"}],
            "comments": [],
            "summary": {"note_count": 1},
        },
    }
    with patch(
        "sdk.extractor.run_keyword_search",
        new_callable=AsyncMock,
        return_value=payload,
    ):
        result = await keyword_ex_async("xhs", "美女")
    assert result["code"] == 0
    assert result["data"]["summary"]["note_count"] == 1


def test_keyword_ex_sync_returns_dict():
    payload = {
        "code": 0,
        "message": "ok",
        "data": {"keywords": ["美女"], "notes": [], "comments": [], "summary": {}},
    }
    with patch("sdk.extractor.MediaCrawlerSDK.keyword_ex", return_value=payload):
        result = keyword_ex("xhs", "美女")
    assert isinstance(result, dict)
    assert result["code"] == 0


def test_creator_ex_sync_returns_dict():
    payload = {
        "code": 0,
        "message": "ok",
        "data": {"profile": None, "notes": [], "summary": {"note_count": 0}},
    }
    with patch("sdk.extractor.MediaCrawlerSDK.creator_ex", return_value=payload):
        result = creator_ex("xhs", "abc")
    assert isinstance(result, dict)
    assert "data" in result
