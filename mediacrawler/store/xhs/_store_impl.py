# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/store/xhs/_store_impl.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#
# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

# @Author  : persist1@126.com
# @Time    : 2025/9/5 19:34
# @Desc    : Xiaohongshu storage implementation class
import json
import os
from datetime import datetime
from typing import List, Dict, Any

import config
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from base.base_crawler import AbstractStore
from database.db_session import get_session
from database.models import XhsNote, XhsNoteComment

from tools.async_file_writer import AsyncFileWriter
from tools.time_util import get_current_timestamp
from var import crawler_type_var, creator_profile_var, source_keyword_var
from database.mongodb_store_base import MongoDBStoreBase
from tools import utils
from store.excel_store_base import ExcelStoreBase

XHS_CREATOR_COMBINED_CSV_FIELDS = [
    "record_type",
    # profile-only fields (filled on first row only)
    "user_id",
    "gender",
    "avatar",
    "ip_location",
    "follows",
    "fans",
    "interaction",
    # note fields (original structure, filled on note rows only)
    "note_id",
    "type",
    "title",
    "desc",
    "video_url",
    "time",
    "last_update_time",
    "creator_hash",
    "nickname",
    "liked_count",
    "collected_count",
    "comment_count",
    "share_count",
    "image_list",
    "tag_list",
    "last_modify_ts",
    "note_url",
    "source_keyword",
    "xsec_token",
]


def _build_creator_profile_csv_row(creator_item: Dict) -> Dict:
    return {
        "record_type": "profile",
        "user_id": creator_item.get("user_id", ""),
        "nickname": creator_item.get("nickname", ""),
        "gender": creator_item.get("gender", ""),
        "avatar": creator_item.get("avatar", ""),
        "desc": creator_item.get("desc", ""),
        "ip_location": creator_item.get("ip_location", ""),
        "follows": creator_item.get("follows", ""),
        "fans": creator_item.get("fans", ""),
        "interaction": creator_item.get("interaction", ""),
        "tag_list": creator_item.get("tag_list", ""),
        "last_modify_ts": creator_item.get("last_modify_ts", ""),
    }


def _build_creator_note_csv_row(content_item: Dict) -> Dict:
    return {
        "record_type": "note",
        **content_item,
    }


XHS_SEARCH_CSV_FIELDS = [
    "note_id",
    "type",
    "title",
    "desc",
    "video_url",
    "time",
    "last_update_time",
    "creator_hash",
    "nickname",
    "liked_count",
    "collected_count",
    "comment_count",
    "share_count",
    "image_list",
    "tag_list",
    "last_modify_ts",
    "note_url",
    "source_keyword",
    "xsec_token",
]

XHS_SEARCH_COMMENT_CSV_FIELDS = [
    "comment_id",
    "create_time",
    "note_id",
    "content",
    "creator_hash",
    "nickname",
    "sub_comment_count",
    "pictures",
    "parent_comment_id",
    "last_modify_ts",
    "like_count",
]


class XhsCsvStoreImplement(AbstractStore):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.writer = AsyncFileWriter(platform="xhs", crawler_type=crawler_type_var.get())

    def _use_creator_combined_csv(self) -> bool:
        return crawler_type_var.get() == "creator" and config.SAVE_DATA_OPTION == "csv"

    def _use_keyword_named_csv(self) -> bool:
        return crawler_type_var.get() == "search" and config.SAVE_DATA_OPTION == "csv"

    def _resolve_search_keyword(self, item: Dict) -> str:
        return (
            (item.get("source_keyword") or source_keyword_var.get() or "unknown_keyword").strip()
        )

    async def store_content(self, content_item: Dict):
        """
        store content data to csv file
        :param content_item:
        :return:
        """
        if self._use_creator_combined_csv():
            creator_item = creator_profile_var.get() or {}
            nickname = creator_item.get("nickname") or content_item.get("nickname") or "unknown_creator"
            file_path = self.writer.get_creator_combined_csv_path(nickname)
            note_row = _build_creator_note_csv_row(content_item)
            await self.writer.write_to_custom_csv(
                file_path, note_row, XHS_CREATOR_COMBINED_CSV_FIELDS, unique_field="note_id"
            )
            return
        if self._use_keyword_named_csv():
            keyword = self._resolve_search_keyword(content_item)
            file_path = self.writer.get_keyword_csv_path(keyword)
            await self.writer.write_to_custom_csv(
                file_path, content_item, XHS_SEARCH_CSV_FIELDS, unique_field="note_id"
            )
            return
        await self.writer.write_to_csv(item_type="contents", item=content_item)

    async def store_comment(self, comment_item: Dict):
        """
        store comment data to csv file
        :param comment_item:
        :return:
        """
        if self._use_keyword_named_csv():
            keyword = self._resolve_search_keyword(comment_item)
            file_path = self.writer.get_keyword_comments_csv_path(keyword)
            await self.writer.write_to_custom_csv(
                file_path, comment_item, XHS_SEARCH_COMMENT_CSV_FIELDS, unique_field="comment_id"
            )
            return
        await self.writer.write_to_csv(item_type="comments", item=comment_item)


    async def store_creator(self, creator_item: Dict):
        if self._use_creator_combined_csv():
            creator_profile_var.set(creator_item)
            nickname = creator_item.get("nickname") or "unknown_creator"
            file_path = self.writer.get_creator_combined_csv_path(nickname)
            if not os.path.exists(file_path):
                profile_row = _build_creator_profile_csv_row(creator_item)
                profile_row["last_modify_ts"] = creator_item.get("last_modify_ts", "")
                await self.writer.write_to_custom_csv(
                    file_path, profile_row, XHS_CREATOR_COMBINED_CSV_FIELDS
                )
            return
        await self.writer.write_to_csv(item_type="creators", item=creator_item)

    def flush(self):
        pass


class XhsJsonStoreImplement(AbstractStore):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.writer = AsyncFileWriter(platform="xhs", crawler_type=crawler_type_var.get())

    def _use_keyword_named_json(self) -> bool:
        return crawler_type_var.get() == "search"

    def _resolve_search_keyword(self, item: Dict) -> str:
        return (
            (item.get("source_keyword") or source_keyword_var.get() or "unknown_keyword").strip()
        )

    async def store_content(self, content_item: Dict):
        """搜索 JSON：``{关键词}_{日期}.json``"""
        if self._use_keyword_named_json():
            keyword = self._resolve_search_keyword(content_item)
            file_path = self.writer.get_keyword_json_path(keyword)
            await self.writer.write_single_item_to_json(
                item_type="contents", item=content_item, file_path=file_path
            )
            return
        await self.writer.write_single_item_to_json(item_type="contents", item=content_item)

    async def store_comment(self, comment_item: Dict):
        """搜索评论 JSON：``{关键词}_comments_{日期}.json``"""
        if self._use_keyword_named_json():
            keyword = self._resolve_search_keyword(comment_item)
            file_path = self.writer.get_keyword_comments_json_path(keyword)
            await self.writer.write_single_item_to_json(
                item_type="comments", item=comment_item, file_path=file_path
            )
            return
        await self.writer.write_single_item_to_json(item_type="comments", item=comment_item)

    async def store_creator(self, creator_item: Dict):
        await self.writer.write_single_item_to_json(item_type="creators", item=creator_item)

    def flush(self):
        """
        flush data to json file
        :return:
        """
        pass



class XhsJsonlStoreImplement(AbstractStore):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.writer = AsyncFileWriter(platform="xhs", crawler_type=crawler_type_var.get())

    async def store_content(self, content_item: Dict):
        await self.writer.write_to_jsonl(item_type="contents", item=content_item)

    async def store_comment(self, comment_item: Dict):
        await self.writer.write_to_jsonl(item_type="comments", item=comment_item)

    async def store_creator(self, creator_item: Dict):
        await self.writer.write_to_jsonl(item_type="creators", item=creator_item)

    def flush(self):
        pass


class XhsMemoryStoreImplement(AbstractStore):
    """将爬取结果写入内存，供 SDK keyword_ex 直接返回。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        from store.memory_collector import get_memory_collector

        self._collector = get_memory_collector()

    @staticmethod
    def _normalize_row(item: Dict) -> Dict[str, str]:
        return {key: "" if value is None else str(value) for key, value in item.items()}

    async def store_content(self, content_item: Dict):
        self._collector.upsert_note(self._normalize_row(content_item))

    async def store_comment(self, comment_item: Dict):
        self._collector.upsert_comment(self._normalize_row(comment_item))

    async def store_creator(self, creator_item: Dict):
        self._collector.set_creator(self._normalize_row(creator_item))

    def flush(self):
        pass


class XhsDbStoreImplement(AbstractStore):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def store_content(self, content_item: Dict):
        note_id = content_item.get("note_id")
        if not note_id:
            return
        async with get_session() as session:
            if await self.content_is_exist(session, note_id):
                await self.update_content(session, content_item)
            else:
                await self.add_content(session, content_item)

    async def add_content(self, session: AsyncSession, content_item: Dict):
        add_ts = int(get_current_timestamp())
        last_modify_ts = int(get_current_timestamp())
        note = XhsNote(
            creator_hash=content_item.get("creator_hash"),
            nickname=content_item.get("nickname"),
            add_ts=add_ts,
            last_modify_ts=last_modify_ts,
            note_id=content_item.get("note_id"),
            type=content_item.get("type"),
            title=content_item.get("title"),
            desc=content_item.get("desc"),
            video_url=content_item.get("video_url"),
            time=content_item.get("time"),
            last_update_time=content_item.get("last_update_time"),
            liked_count=str(content_item.get("liked_count")),
            collected_count=str(content_item.get("collected_count")),
            comment_count=str(content_item.get("comment_count")),
            share_count=str(content_item.get("share_count")),
            image_list=json.dumps(content_item.get("image_list")),
            tag_list=json.dumps(content_item.get("tag_list")),
            note_url=content_item.get("note_url"),
            source_keyword=content_item.get("source_keyword", ""),
            xsec_token=content_item.get("xsec_token", "")
        )
        session.add(note)

    async def update_content(self, session: AsyncSession, content_item: Dict):
        note_id = content_item.get("note_id")
        last_modify_ts = int(get_current_timestamp())
        update_data = {
            "last_modify_ts": last_modify_ts,
            "liked_count": str(content_item.get("liked_count")),
            "collected_count": str(content_item.get("collected_count")),
            "comment_count": str(content_item.get("comment_count")),
            "share_count": str(content_item.get("share_count")),
            "last_update_time": content_item.get("last_update_time"),
        }
        stmt = update(XhsNote).where(XhsNote.note_id == note_id).values(**update_data)
        await session.execute(stmt)

    async def content_is_exist(self, session: AsyncSession, note_id: str) -> bool:
        stmt = select(XhsNote).where(XhsNote.note_id == note_id)
        result = await session.execute(stmt)
        return result.first() is not None

    async def store_comment(self, comment_item: Dict):
        if not comment_item:
            return
        async with get_session() as session:
            comment_id = comment_item.get("comment_id")
            if not comment_id:
                return
            if await self.comment_is_exist(session, comment_id):
                await self.update_comment(session, comment_item)
            else:
                await self.add_comment(session, comment_item)

    async def add_comment(self, session: AsyncSession, comment_item: Dict):
        add_ts = int(get_current_timestamp())
        last_modify_ts = int(get_current_timestamp())
        comment = XhsNoteComment(
            creator_hash=comment_item.get("creator_hash"),
            nickname=comment_item.get("nickname"),
            add_ts=add_ts,
            last_modify_ts=last_modify_ts,
            comment_id=comment_item.get("comment_id"),
            create_time=comment_item.get("create_time"),
            note_id=comment_item.get("note_id"),
            content=comment_item.get("content"),
            sub_comment_count=int(comment_item.get("sub_comment_count", 0) or 0),
            pictures=json.dumps(comment_item.get("pictures")),
            parent_comment_id=str(comment_item.get("parent_comment_id", "")),
            like_count=str(comment_item.get("like_count"))
        )
        session.add(comment)

    async def update_comment(self, session: AsyncSession, comment_item: Dict):
        comment_id = comment_item.get("comment_id")
        last_modify_ts = int(get_current_timestamp())
        update_data = {
            "last_modify_ts": last_modify_ts,
            "like_count": str(comment_item.get("like_count")),
            "sub_comment_count": int(comment_item.get("sub_comment_count", 0) or 0),
        }
        stmt = update(XhsNoteComment).where(XhsNoteComment.comment_id == comment_id).values(**update_data)
        await session.execute(stmt)

    async def comment_is_exist(self, session: AsyncSession, comment_id: str) -> bool:
        stmt = select(XhsNoteComment).where(XhsNoteComment.comment_id == comment_id)
        result = await session.execute(stmt)
        return result.first() is not None

    async def store_creator(self, creator_item: Dict):
        # 教学版：创作者个人资料不再落库
        pass

    async def get_all_content(self) -> List[Dict]:
        async with get_session() as session:
            stmt = select(XhsNote)
            result = await session.execute(stmt)
            return [item.__dict__ for item in result.scalars().all()]

    async def get_all_comments(self) -> List[Dict]:
        async with get_session() as session:
            stmt = select(XhsNoteComment)
            result = await session.execute(stmt)
            return [item.__dict__ for item in result.scalars().all()]


class XhsSqliteStoreImplement(XhsDbStoreImplement):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class XhsMongoStoreImplement(AbstractStore):
    """Xiaohongshu MongoDB storage implementation"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mongo_store = MongoDBStoreBase(collection_prefix="xhs")

    async def store_content(self, content_item: Dict):
        """
        Store note content to MongoDB
        Args:
            content_item: Note content data
        """
        note_id = content_item.get("note_id")
        if not note_id:
            return

        await self.mongo_store.save_or_update(
            collection_suffix="contents",
            query={"note_id": note_id},
            data=content_item
        )
        utils.logger.info(f"[XhsMongoStoreImplement.store_content] Saved note {note_id} to MongoDB")

    async def store_comment(self, comment_item: Dict):
        """
        Store comment to MongoDB
        Args:
            comment_item: Comment data
        """
        comment_id = comment_item.get("comment_id")
        if not comment_id:
            return

        await self.mongo_store.save_or_update(
            collection_suffix="comments",
            query={"comment_id": comment_id},
            data=comment_item
        )
        utils.logger.info(f"[XhsMongoStoreImplement.store_comment] Saved comment {comment_id} to MongoDB")

    async def store_creator(self, creator_item: Dict):
        """
        Store creator information to MongoDB
        Args:
            creator_item: Creator data
        """
        user_id = creator_item.get("user_id")
        if not user_id:
            return

        await self.mongo_store.save_or_update(
            collection_suffix="creators",
            query={"user_id": user_id},
            data=creator_item,
        )
        utils.logger.info(f"[XhsMongoStoreImplement.store_creator] Saved creator {user_id} to MongoDB")


class XhsExcelStoreImplement:
    """Xiaohongshu Excel storage implementation - Global singleton"""

    def __new__(cls, *args, **kwargs):
        from store.excel_store_base import ExcelStoreBase
        resume_key = getattr(config, "EXCEL_RESUME_KEY", "") or ""
        crawler_type = crawler_type_var.get()
        # 断点续爬时把关键词编进 singleton key，避免串文件
        if resume_key:
            crawler_type = f"{crawler_type}:{resume_key}"
        return ExcelStoreBase.get_instance(
            platform="xhs",
            crawler_type=crawler_type,
        )
