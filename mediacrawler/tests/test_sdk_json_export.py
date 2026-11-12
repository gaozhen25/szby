# -*- coding: utf-8 -*-

import json
from pathlib import Path

import pytest

from services.sdk_json_export import (
    export_creator_response,
    export_search_response,
    merge_creator_response,
    merge_search_response,
)


def test_merge_search_dedupes_note_id():
    existing = {
        "code": 0,
        "data": {
            "notes": [{"note_id": "1", "title": "old", "source_keyword": "火星生活"}],
            "comments": [],
            "keywords": ["火星生活"],
            "grouped_notes": {"火星生活": [{"note_id": "1", "title": "old", "source_keyword": "火星生活"}]},
            "summary": {"note_count": 1},
        },
    }
    incoming = {
        "code": 0,
        "data": {
            "notes": [
                {"note_id": "1", "title": "new", "source_keyword": "火星生活"},
                {"note_id": "2", "title": "added", "source_keyword": "火星生活"},
            ],
            "comments": [],
            "keywords": ["火星生活"],
            "grouped_notes": {},
            "summary": {"note_count": 2},
        },
    }

    merged = merge_search_response(existing, incoming)
    notes = merged["data"]["notes"]
    assert len(notes) == 2
    assert notes[0]["title"] == "old"
    assert notes[1]["note_id"] == "2"


def test_merge_creator_dedupes_note_id_and_updates_profile():
    existing = {
        "code": 0,
        "data": {
            "profile": {"nickname": "火星生活", "fans": "20"},
            "notes": [{"note_id": "1", "title": "old"}],
            "summary": {"note_count": 1},
        },
    }
    incoming = {
        "code": 0,
        "data": {
            "profile": {"nickname": "火星生活", "fans": "23"},
            "notes": [
                {"note_id": "1", "title": "new"},
                {"note_id": "2", "title": "added"},
            ],
            "summary": {"note_count": 2},
        },
    }

    merged = merge_creator_response(existing, incoming)
    assert merged["data"]["profile"]["fans"] == "23"
    assert len(merged["data"]["notes"]) == 2
    assert merged["data"]["notes"][0]["title"] == "old"


def test_export_search_writes_and_appends_without_overwrite(tmp_path: Path):
    first = {
        "code": 0,
        "message": "ok",
        "data": {
            "keywords": ["火星生活"],
            "notes": [{"note_id": "1", "title": "A", "source_keyword": "火星生活"}],
            "comments": [],
            "grouped_notes": {"火星生活": [{"note_id": "1", "title": "A", "source_keyword": "火星生活"}]},
            "summary": {},
        },
    }
    second = {
        "code": 0,
        "message": "ok",
        "data": {
            "keywords": ["火星生活"],
            "notes": [
                {"note_id": "1", "title": "A2", "source_keyword": "火星生活"},
                {"note_id": "2", "title": "B", "source_keyword": "火星生活"},
            ],
            "comments": [],
            "grouped_notes": {},
            "summary": {},
        },
    }

    merged1, path1 = export_search_response(first, platform="xhs", keyword="火星生活", data_root=tmp_path)
    assert Path(path1).exists()
    assert len(merged1["data"]["notes"]) == 1

    merged2, path2 = export_search_response(second, platform="xhs", keyword="火星生活", data_root=tmp_path)
    assert path1 == path2
    assert len(merged2["data"]["notes"]) == 2
    assert merged2["data"]["notes"][0]["title"] == "A"

    on_disk = json.loads(Path(path2).read_text(encoding="utf-8"))
    assert len(on_disk["data"]["notes"]) == 2


def test_export_creator_uses_nickname_filename(tmp_path: Path):
    response = {
        "code": 0,
        "message": "ok",
        "data": {
            "profile": {"nickname": "火星生活", "fans": "23"},
            "notes": [{"note_id": "1", "title": "note"}],
            "summary": {},
        },
    }
    merged, path = export_creator_response(response, platform="xhs", nickname="火星生活", data_root=tmp_path)
    assert "火星生活_" in Path(path).name
    assert merged["data"]["summary"]["source_file"] == path
