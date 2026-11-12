# -*- coding: utf-8 -*-
"""抖音博主简介与合并 JSON 导出回归测试。"""

import asyncio
import json
from pathlib import Path

import config
import store.douyin as ds
from store.douyin._store_impl import DouyinJsonStoreImplement
from tools.async_file_writer import AsyncFileWriter
from var import crawler_type_var, creator_profile_var


def _build_creator_api_response() -> dict:
    return {
        "user": {
            "nickname": "泡泡丸",
            "gender": 2,
            "signature": "这是博主简介",
            "ip_location": "上海",
            "following_count": 12,
            "max_follower_count": 3456,
            "total_favorited": 78910,
            "aweme_count": 50,
            "avatar_300x300": {"url_list": ["http://x/avatar.jpg"]},
        }
    }


def test_save_creator_builds_profile_fields():
    captured = {}

    class FakeStore:
        async def store_creator(self, creator):
            captured.update(creator)

    orig = ds.DouyinStoreFactory.create_store
    ds.DouyinStoreFactory.create_store = staticmethod(lambda: FakeStore())
    try:
        asyncio.run(ds.save_creator("MS4wLjABAAAATestSecUid", _build_creator_api_response()))
    finally:
        ds.DouyinStoreFactory.create_store = orig

    assert captured["user_id"] == "MS4wLjABAAAATestSecUid"
    assert captured["nickname"] == "泡泡丸"
    assert captured["desc"] == "这是博主简介"
    assert captured["gender"] == "Female"
    assert captured["avatar"] == "http://x/avatar.jpg"
    assert captured["fans"] == "3456"


def test_creator_combined_json_naming_and_merge(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SAVE_DATA_PATH", str(tmp_path))
    token = crawler_type_var.set("creator")
    creator_profile_var.set({"nickname": "泡泡丸"})
    writer = AsyncFileWriter(platform="douyin", crawler_type="creator")

    try:
        profile = {
            "user_id": "MS4wLjABAAAATestSecUid",
            "nickname": "泡泡丸",
            "desc": "这是博主简介",
            "fans": "3456",
        }
        aweme = {
            "aweme_id": "7514608774611717411",
            "title": "测试作品",
            "nickname": "泡泡丸",
        }

        file_path = asyncio.run(writer.upsert_creator_combined_json("泡泡丸", profile=profile))
        asyncio.run(writer.upsert_creator_combined_json("泡泡丸", aweme=aweme))

        path = Path(file_path)
        assert path.name.startswith("泡泡丸_")
        assert path.suffix == ".json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["data"]["profile"]["desc"] == "这是博主简介"
        assert len(payload["data"]["awemes"]) == 1
        assert payload["data"]["awemes"][0]["aweme_id"] == "7514608774611717411"
        assert payload["data"]["summary"]["aweme_count"] == 1
    finally:
        crawler_type_var.reset(token)
        creator_profile_var.set({})


def test_json_store_uses_combined_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SAVE_DATA_OPTION", "json")
    monkeypatch.setattr(config, "SAVE_DATA_PATH", str(tmp_path))
    token = crawler_type_var.set("creator")

    store = DouyinJsonStoreImplement()
    profile = {
        "user_id": "MS4wLjABAAAATestSecUid",
        "nickname": "测试博主",
        "desc": "简介内容",
    }
    aweme = {"aweme_id": "123", "title": "作品A", "nickname": "测试博主"}

    try:
        asyncio.run(store.store_creator(profile))
        asyncio.run(store.store_content(aweme))

        json_dir = Path(tmp_path) / "douyin" / "json"
        files = list(json_dir.glob("测试博主_*.json"))
        assert len(files) == 1
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        assert payload["data"]["profile"]["desc"] == "简介内容"
        assert payload["data"]["awemes"][0]["title"] == "作品A"
    finally:
        crawler_type_var.reset(token)
        creator_profile_var.set({})
