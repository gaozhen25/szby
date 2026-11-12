# -*- coding: utf-8 -*-
"""抖音热点宝搜索热点总榜落盘测试。"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from store.douyin import save_search_hot_board
from tools.async_file_writer import AsyncFileWriter
from tools.hotspot_trend_chart import build_trend_chart_html, png_file_to_data_uri


SAMPLE_API = {
    "code": 0,
    "data": {
        "page_num": 1,
        "page_size": 10,
        "total_count": 10000,
        "search_list": [
            {
                "key_word": "世界杯",
                "search_score": 239640754,
                "trends": [
                    {"date": "20260630", "value": 958599412},
                    {"date": "20260713", "value": 239640754},
                ],
            },
            {
                "key_word": "巴威台风",
                "search_score": 220332256,
                "trends": [{"date": "20260713", "value": 220332256}],
            },
        ],
    },
}


def test_hotspot_board_json_path():
    writer = AsyncFileWriter(platform="dyhot", crawler_type="hotspot")
    path = writer.get_hotspot_board_json_path("搜索热点总榜")
    assert path.startswith("data/dyhot/json/搜索热点总榜_")
    assert path.endswith(".json")


@pytest.mark.asyncio
async def test_save_search_hot_board(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("config.SAVE_DATA_PATH", str(tmp_path))
    monkeypatch.setattr("config.PLATFORM", "dy")
    monkeypatch.setattr("config.DY_HOTSPOT_DATA_DIR", "dyhot")
    monkeypatch.setattr("config.CRAWLER_TYPE", "hotspot")
    monkeypatch.setattr("config.SAVE_DATA_OPTION", "json")

    data = SAMPLE_API["data"]
    items = []
    for idx, raw in enumerate(data["search_list"], start=1):
        items.append(
            {
                "rank": idx,
                "key_word": raw["key_word"],
                "search_score": raw["search_score"],
                "trends": raw.get("trends") or [],
                "sub_type": 3001,
                "date_window": 24,
                "last_modify_ts": 1,
            }
        )

    path = await save_search_hot_board(
        items,
        meta={
            "sub_type": 3001,
            "date_window": 24,
            "total_count": data["total_count"],
            "fetched_count": len(items),
        },
    )
    assert Path(path).exists()
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert payload["code"] == 0
    assert payload["data"]["fetched_count"] == 2
    assert payload["data"]["date_window"] == 24
    assert payload["data"]["items"][0]["key_word"] == "世界杯"
    assert payload["data"]["items"][0]["rank"] == 1
    assert payload["data"]["items"][0]["trends"][0]["date"] == "20260630"
    assert payload["data"]["items"][0]["trend_series"]["dates"] == ["06-30", "07-13"]
    chart_path = Path(payload["data"]["summary"]["chart_file"])
    assert chart_path.exists()
    html = chart_path.read_text(encoding="utf-8")
    assert "搜索量趋势" in html
    assert "世界杯" in html


def test_trend_html_embeds_wordcloud(tmp_path: Path):
    png = tmp_path / "demo_word_cloud.png"
    # 最小合法 PNG
    png.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
    )
    items = [
        {
            "rank": 1,
            "key_word": "世界杯",
            "search_score": 1,
            "trends": [{"date": "20260713", "value": 1}],
            "wordcloud_path": str(png),
        }
    ]
    uri = png_file_to_data_uri(str(png))
    assert uri and uri.startswith("data:image/png;base64,")
    html = build_trend_chart_html(items, meta={"board_name": "搜索热点总榜"})
    assert "wordcloud_data_uri" in html
    assert "data:image/png;base64," in html
    assert "暂无评论词云" in html  # 模板仍包含占位逻辑字符串
