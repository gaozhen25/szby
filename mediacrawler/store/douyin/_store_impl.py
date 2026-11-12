# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/store/douyin/_store_impl.py
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


# -*- coding: utf-8 -*-
# @Author  : persist1@126.com
# @Time    : 2025/9/5 19:34
# @Desc    : Douyin storage implementation class
import asyncio
import json
import os
import pathlib
from typing import Dict

from sqlalchemy import select

import config
from base.base_crawler import AbstractStore
from database.db_session import get_session
from database.models import DouyinAweme, DouyinAwemeComment
from tools import utils, words
from tools.async_file_writer import AsyncFileWriter
from var import crawler_type_var, creator_profile_var, source_keyword_var
from database.mongodb_store_base import MongoDBStoreBase


DOUYIN_CREATOR_COMBINED_CSV_FIELDS = [
    "record_type",
    "user_id",
    "gender",
    "avatar",
    "ip_location",
    "follows",
    "fans",
    "interaction",
    "videos_count",
    "aweme_id",
    "aweme_type",
    "title",
    "desc",
    "create_time",
    "creator_hash",
    "nickname",
    "liked_count",
    "collected_count",
    "comment_count",
    "share_count",
    "last_modify_ts",
    "aweme_url",
    "cover_url",
    "video_download_url",
    "music_download_url",
    "note_download_url",
    "source_keyword",
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
        "videos_count": creator_item.get("videos_count", ""),
        "last_modify_ts": creator_item.get("last_modify_ts", ""),
    }


def _build_creator_aweme_csv_row(content_item: Dict) -> Dict:
    return {
        "record_type": "aweme",
        **content_item,
    }

DOUYIN_SEARCH_CSV_FIELDS = [
    "aweme_id",
    "aweme_type",
    "title",
    "desc",
    "create_time",
    "creator_hash",
    "nickname",
    "liked_count",
    "collected_count",
    "comment_count",
    "share_count",
    "last_modify_ts",
    "aweme_url",
    "cover_url",
    "video_download_url",
    "music_download_url",
    "note_download_url",
    "source_keyword",
]

DOUYIN_SEARCH_COMMENT_CSV_FIELDS = [
    "comment_id",
    "create_time",
    "aweme_id",
    "content",
    "creator_hash",
    "nickname",
    "sub_comment_count",
    "like_count",
    "last_modify_ts",
    "parent_comment_id",
    "pictures",
]


class DouyinCsvStoreImplement(AbstractStore):
    def __init__(self):
        self.file_writer = AsyncFileWriter(
            crawler_type=crawler_type_var.get(),
            platform="douyin"
        )

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
        Douyin content CSV storage implementation
        Args:
            content_item: note item dict

        Returns:

        """
        if self._use_creator_combined_csv():
            creator_item = creator_profile_var.get() or {}
            nickname = creator_item.get("nickname") or content_item.get("nickname") or "unknown_creator"
            file_path = self.file_writer.get_creator_combined_csv_path(nickname)
            aweme_row = _build_creator_aweme_csv_row(content_item)
            await self.file_writer.write_to_custom_csv(
                file_path, aweme_row, DOUYIN_CREATOR_COMBINED_CSV_FIELDS, unique_field="aweme_id"
            )
            return
        if self._use_keyword_named_csv():
            keyword = self._resolve_search_keyword(content_item)
            file_path = self.file_writer.get_keyword_csv_path(keyword)
            await self.file_writer.write_to_custom_csv(
                file_path,
                content_item,
                DOUYIN_SEARCH_CSV_FIELDS,
                unique_field="aweme_id",
            )
            return
        await self.file_writer.write_to_csv(
            item=content_item,
            item_type="contents"
        )

    async def store_comment(self, comment_item: Dict):
        """
        Douyin comment CSV storage implementation
        Args:
            comment_item: comment item dict

        Returns:

        """
        if self._use_keyword_named_csv():
            keyword = self._resolve_search_keyword(comment_item)
            file_path = self.file_writer.get_keyword_comments_csv_path(keyword)
            await self.file_writer.write_to_custom_csv(
                file_path,
                comment_item,
                DOUYIN_SEARCH_COMMENT_CSV_FIELDS,
                unique_field="comment_id",
            )
            return
        await self.file_writer.write_to_csv(
            item=comment_item,
            item_type="comments"
        )

    async def store_creator(self, creator: Dict):
        """
        Douyin creator CSV storage implementation
        Args:
            creator: creator item dict

        Returns:

        """
        if self._use_creator_combined_csv():
            creator_profile_var.set(creator)
            nickname = creator.get("nickname") or "unknown_creator"
            file_path = self.file_writer.get_creator_combined_csv_path(nickname)
            if not os.path.exists(file_path):
                profile_row = _build_creator_profile_csv_row(creator)
                await self.file_writer.write_to_custom_csv(
                    file_path, profile_row, DOUYIN_CREATOR_COMBINED_CSV_FIELDS
                )
            return
        await self.file_writer.write_to_csv(
            item=creator,
            item_type="creators"
        )


class DouyinDbStoreImplement(AbstractStore):
    async def store_content(self, content_item: Dict):
        """
        Douyin content DB storage implementation
        Args:
            content_item: content item dict
        """
        aweme_id = content_item.get("aweme_id")
        async with get_session() as session:
            result = await session.execute(select(DouyinAweme).where(DouyinAweme.aweme_id == aweme_id))
            aweme_detail = result.scalar_one_or_none()

            if not aweme_detail:
                content_item["add_ts"] = utils.get_current_timestamp()
                if content_item.get("title"):
                    new_content = DouyinAweme(**content_item)
                    session.add(new_content)
            else:
                for key, value in content_item.items():
                    setattr(aweme_detail, key, value)
            await session.commit()

    async def store_comment(self, comment_item: Dict):
        """
        Douyin comment DB storage implementation
        Args:
            comment_item: comment item dict
        """
        comment_id = comment_item.get("comment_id")
        async with get_session() as session:
            result = await session.execute(select(DouyinAwemeComment).where(DouyinAwemeComment.comment_id == comment_id))
            comment_detail = result.scalar_one_or_none()

            if not comment_detail:
                comment_item["add_ts"] = utils.get_current_timestamp()
                new_comment = DouyinAwemeComment(**comment_item)
                session.add(new_comment)
            else:
                for key, value in comment_item.items():
                    setattr(comment_detail, key, value)
            await session.commit()

    async def store_creator(self, creator: Dict):
        # DyCreator 表已移除，profile 请使用 json/csv 合并文件落盘。
        pass


class DouyinJsonStoreImplement(AbstractStore):
    def __init__(self):
        self.file_writer = AsyncFileWriter(
            crawler_type=crawler_type_var.get(),
            platform="douyin"
        )

    def _use_creator_combined_json(self) -> bool:
        return crawler_type_var.get() == "creator" and config.SAVE_DATA_OPTION == "json"

    def _use_keyword_named_json(self) -> bool:
        return crawler_type_var.get() == "search"

    def _resolve_search_keyword(self, item: Dict) -> str:
        return (
            (item.get("source_keyword") or source_keyword_var.get() or "unknown_keyword").strip()
        )

    async def store_content(self, content_item: Dict):
        """
        content JSON storage implementation
        搜索：``{关键词}_{日期}.json``；博主：``{昵称}_{日期}.json``
        """
        if self._use_creator_combined_json():
            creator_item = creator_profile_var.get() or {}
            nickname = creator_item.get("nickname") or content_item.get("nickname") or "unknown_creator"
            await self.file_writer.upsert_creator_combined_json(
                nickname,
                aweme=content_item,
            )
            return
        if self._use_keyword_named_json():
            keyword = self._resolve_search_keyword(content_item)
            file_path = self.file_writer.get_keyword_json_path(keyword)
            await self.file_writer.write_single_item_to_json(
                item=content_item,
                item_type="contents",
                file_path=file_path,
            )
            return
        await self.file_writer.write_single_item_to_json(
            item=content_item,
            item_type="contents"
        )

    async def store_comment(self, comment_item: Dict):
        """
        comment JSON storage implementation
        搜索：``{关键词}_comments_{日期}.json``
        """
        if self._use_keyword_named_json():
            keyword = self._resolve_search_keyword(comment_item)
            file_path = self.file_writer.get_keyword_comments_json_path(keyword)
            await self.file_writer.write_single_item_to_json(
                item=comment_item,
                item_type="comments",
                file_path=file_path,
            )
            return
        await self.file_writer.write_single_item_to_json(
            item=comment_item,
            item_type="comments"
        )

    async def store_creator(self, creator: Dict):
        """
        creator JSON storage implementation
        Args:
            creator:

        Returns:

        """
        if self._use_creator_combined_json():
            creator_profile_var.set(creator)
            nickname = creator.get("nickname") or "unknown_creator"
            await self.file_writer.upsert_creator_combined_json(
                nickname,
                profile=creator,
            )
            return
        await self.file_writer.write_single_item_to_json(
            item=creator,
            item_type="creators"
        )



class DouyinJsonlStoreImplement(AbstractStore):
    def __init__(self):
        self.file_writer = AsyncFileWriter(
            crawler_type=crawler_type_var.get(),
            platform="douyin"
        )

    async def store_content(self, content_item: Dict):
        await self.file_writer.write_to_jsonl(
            item=content_item,
            item_type="contents"
        )

    async def store_comment(self, comment_item: Dict):
        await self.file_writer.write_to_jsonl(
            item=comment_item,
            item_type="comments"
        )

    async def store_creator(self, creator: Dict):
        await self.file_writer.write_to_jsonl(
            item=creator,
            item_type="creators"
        )


class DouyinSqliteStoreImplement(DouyinDbStoreImplement):
    pass


class DouyinMongoStoreImplement(AbstractStore):
    """Douyin MongoDB storage implementation"""

    def __init__(self):
        self.mongo_store = MongoDBStoreBase(collection_prefix="douyin")

    async def store_content(self, content_item: Dict):
        """
        Store video content to MongoDB
        Args:
            content_item: Video content data
        """
        aweme_id = content_item.get("aweme_id")
        if not aweme_id:
            return

        await self.mongo_store.save_or_update(
            collection_suffix="contents",
            query={"aweme_id": aweme_id},
            data=content_item
        )
        utils.logger.info(f"[DouyinMongoStoreImplement.store_content] Saved aweme {aweme_id} to MongoDB")

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
        utils.logger.info(f"[DouyinMongoStoreImplement.store_comment] Saved comment {comment_id} to MongoDB")

    async def store_creator(self, creator_item: Dict):
        # 教学版：创作者个人资料不再落库
        pass


class DouyinExcelStoreImplement:
    """Douyin Excel storage implementation - Global singleton"""

    def __new__(cls, *args, **kwargs):
        from store.excel_store_base import ExcelStoreBase
        return ExcelStoreBase.get_instance(
            platform="douyin",
            crawler_type=crawler_type_var.get()
        )
