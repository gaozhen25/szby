# -*- coding: utf-8 -*-

import json
from pathlib import Path

import pytest

from services.xhs_json_service import XhsJsonService


@pytest.fixture
def sample_search_json(tmp_path: Path) -> Path:
    path = tmp_path / "美女_2026-07-10.json"
    path.write_text(
        json.dumps(
            {
                "code": 0,
                "message": "ok",
                "data": {
                    "keywords": ["美女"],
                    "notes": [
                        {
                            "note_id": "1",
                            "title": "测试",
                            "source_keyword": "美女",
                            "liked_count": "10",
                        }
                    ],
                    "comments": [],
                    "summary": {"note_count": 1},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def sample_creator_json(tmp_path: Path) -> Path:
    path = tmp_path / "火星生活_2026-07-10.json"
    path.write_text(
        json.dumps(
            {
                "code": 0,
                "message": "ok",
                "data": {
                    "profile": {
                        "user_id": "abc",
                        "nickname": "火星生活",
                        "fans": "23",
                    },
                    "notes": [
                        {
                            "note_id": "n1",
                            "title": "笔记1",
                            "creator_hash": "abc",
                        }
                    ],
                    "summary": {"note_count": 1},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_load_search_from_json(tmp_path: Path, sample_search_json: Path):
    service = XhsJsonService(json_dir=tmp_path)
    dataset = service.load_search_by_keyword("美女")
    assert dataset.note_count == 1
    assert dataset.notes[0].title == "测试"


def test_load_creator_from_json(tmp_path: Path, sample_creator_json: Path):
    service = XhsJsonService(json_dir=tmp_path)
    dataset = service.load_creator_by_nickname("火星生活")
    assert dataset.profile is not None
    assert dataset.profile.nickname == "火星生活"
    assert dataset.note_count == 1


def test_backend_client_archive_local_dict(tmp_path: Path, sample_search_json: Path):
    from sdk import XhsBackendClient

    client = XhsBackendClient.archive.local(json_dir=tmp_path)
    result = client.search("美女")
    assert isinstance(result, dict)
    assert result["code"] == 0
    assert result["data"]["summary"]["note_count"] == 1
    assert result["data"]["notes"][0]["title"] == "测试"


def test_backend_client_archive_local_as_dataset(tmp_path: Path, sample_search_json: Path):
    from sdk import XhsBackendClient

    client = XhsBackendClient.archive.local(json_dir=tmp_path)
    dataset = client.search("美女", as_dataset=True)
    assert dataset.note_count == 1


def test_backend_client_live_search_returns_dict():
    """live 模式：默认返回 dict。"""
    from unittest.mock import patch

    from sdk.backend_client import XhsBackendClient, _dataset_from_search_payload

    payload = {
        "code": 0,
        "message": "ok",
        "data": {
            "keywords": ["美女"],
            "notes": [
                {
                    "note_id": "live-1",
                    "title": "实时笔记",
                    "source_keyword": "美女",
                    "liked_count": "99",
                }
            ],
            "comments": [],
            "summary": {"note_count": 1, "source_file": "live"},
        },
    }
    dataset = _dataset_from_search_payload(payload, keyword="美女")
    assert dataset.note_count == 1

    client = XhsBackendClient.live("http://testserver", timeout=60.0)
    with patch("sdk.backend_client.request_json", return_value=payload) as mock_req:
        result = client.search("美女")
        mock_req.assert_called_once()
        call_args = mock_req.call_args
        assert call_args[0][1] == "POST"
        assert call_args[0][2] == "/api/data/crawl/search"
    assert isinstance(result, dict)
    assert result["data"]["notes"][0]["title"] == "实时笔记"

    with patch("sdk.backend_client.request_json", return_value=payload):
        dataset = client.search("美女", as_dataset=True)
    assert dataset.notes[0].title == "实时笔记"
    client.close()
