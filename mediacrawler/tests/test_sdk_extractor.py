# -*- coding: utf-8 -*-

import pytest

from services.crawler_runner import _build_creator_dataset_from_memory, _build_dataset_from_memory
from store.memory_collector import get_memory_collector, reset_memory_collector
from store.xhs._store_impl import XhsMemoryStoreImplement


@pytest.mark.asyncio
async def test_memory_store_collects_notes_and_comments():
    reset_memory_collector()
    store = XhsMemoryStoreImplement()

    await store.store_content(
        {
            "note_id": "note-1",
            "title": "测试笔记",
            "source_keyword": "火星生活",
            "liked_count": 10,
        }
    )
    await store.store_comment(
        {
            "comment_id": "comment-1",
            "note_id": "note-1",
            "content": "好棒",
            "like_count": 1,
        }
    )

    dataset = _build_dataset_from_memory("火星生活", with_comments=True)
    assert dataset.note_count == 1
    assert dataset.comment_count == 1
    assert dataset.notes[0].title == "测试笔记"
    assert dataset.comments[0].content == "好棒"


def test_build_dataset_filters_by_keyword():
    reset_memory_collector()
    collector = get_memory_collector()
    collector.upsert_note(
        {"note_id": "1", "title": "A", "source_keyword": "火星生活"}
    )
    collector.upsert_note(
        {"note_id": "2", "title": "B", "source_keyword": "旅游"}
    )

    dataset = _build_dataset_from_memory("火星生活", with_comments=False)
    assert dataset.note_count == 1
    assert dataset.notes[0].note_id == "1"


@pytest.mark.asyncio
async def test_memory_store_collects_creator_profile_and_notes():
    reset_memory_collector()
    store = XhsMemoryStoreImplement()

    await store.store_creator(
        {
            "user_id": "5f58bd990000000001003753",
            "nickname": "测试博主",
            "fans": "1.2万",
        }
    )
    await store.store_content(
        {
            "note_id": "note-1",
            "title": "博主笔记",
            "creator_hash": "5f58bd990000000001003753",
            "liked_count": "100",
        }
    )

    dataset = _build_creator_dataset_from_memory()
    assert dataset.profile is not None
    assert dataset.profile.nickname == "测试博主"
    assert dataset.note_count == 1
    assert dataset.notes[0].title == "博主笔记"
