# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tools/async_file_writer.py
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

import asyncio
import csv
import json
import os
import pathlib
import re
from typing import Any, Dict, List, Optional
import aiofiles
import config
from tools import utils
from tools.words import AsyncWordCloudGenerator

class AsyncFileWriter:
    def __init__(self, platform: str, crawler_type: str):
        self.lock = asyncio.Lock()
        self.platform = platform
        self.crawler_type = crawler_type
        self.wordcloud_generator = AsyncWordCloudGenerator() if config.ENABLE_GET_WORDCLOUD else None
        # 同文件已写入记录的唯一键缓存，用于追加时跳过重复行
        self._csv_seen_ids: Dict[str, set[str]] = {}

    @staticmethod
    def sanitize_filename(name: str, default: str = "unknown") -> str:
        if not name:
            return default
        safe_name = re.sub(r'[\\/:*?"<>|\s]+', "_", name.strip())
        return safe_name[:80] or default

    def get_creator_combined_csv_path(self, creator_nickname: str) -> str:
        safe_name = self.sanitize_filename(creator_nickname, default="unknown_creator")
        if config.SAVE_DATA_PATH:
            base_path = f"{config.SAVE_DATA_PATH}/{self.platform}/csv"
        else:
            base_path = f"data/{self.platform}/csv"
        pathlib.Path(base_path).mkdir(parents=True, exist_ok=True)
        file_name = f"{safe_name}_{utils.get_current_date()}.csv"
        return f"{base_path}/{file_name}"

    def get_keyword_csv_path(self, keyword: str) -> str:
        """关键词搜索笔记 CSV：{关键词}_{日期}.csv"""
        safe_name = self.sanitize_filename(keyword, default="unknown_keyword")
        if config.SAVE_DATA_PATH:
            base_path = f"{config.SAVE_DATA_PATH}/{self.platform}/csv"
        else:
            base_path = f"data/{self.platform}/csv"
        pathlib.Path(base_path).mkdir(parents=True, exist_ok=True)
        file_name = f"{safe_name}_{utils.get_current_date()}.csv"
        return f"{base_path}/{file_name}"

    def get_keyword_comments_csv_path(self, keyword: str) -> str:
        """关键词搜索评论 CSV：{关键词}_comments_{日期}.csv"""
        safe_name = self.sanitize_filename(keyword, default="unknown_keyword")
        if config.SAVE_DATA_PATH:
            base_path = f"{config.SAVE_DATA_PATH}/{self.platform}/csv"
        else:
            base_path = f"data/{self.platform}/csv"
        pathlib.Path(base_path).mkdir(parents=True, exist_ok=True)
        file_name = f"{safe_name}_comments_{utils.get_current_date()}.csv"
        return f"{base_path}/{file_name}"

    def get_keyword_json_path(self, keyword: str) -> str:
        """关键词搜索笔记 JSON：{关键词}_{日期}.json"""
        safe_name = self.sanitize_filename(keyword, default="unknown_keyword")
        if config.SAVE_DATA_PATH:
            base_path = f"{config.SAVE_DATA_PATH}/{self.platform}/json"
        else:
            base_path = f"data/{self.platform}/json"
        pathlib.Path(base_path).mkdir(parents=True, exist_ok=True)
        return f"{base_path}/{safe_name}_{utils.get_current_date()}.json"

    def get_keyword_comments_json_path(self, keyword: str) -> str:
        """关键词搜索评论 JSON：{关键词}_comments_{日期}.json"""
        safe_name = self.sanitize_filename(keyword, default="unknown_keyword")
        if config.SAVE_DATA_PATH:
            base_path = f"{config.SAVE_DATA_PATH}/{self.platform}/json"
        else:
            base_path = f"data/{self.platform}/json"
        pathlib.Path(base_path).mkdir(parents=True, exist_ok=True)
        return f"{base_path}/{safe_name}_comments_{utils.get_current_date()}.json"

    def get_creator_combined_json_path(self, creator_nickname: str) -> str:
        safe_name = self.sanitize_filename(creator_nickname, default="unknown_creator")
        if config.SAVE_DATA_PATH:
            base_path = f"{config.SAVE_DATA_PATH}/{self.platform}/json"
        else:
            base_path = f"data/{self.platform}/json"
        pathlib.Path(base_path).mkdir(parents=True, exist_ok=True)
        file_name = f"{safe_name}_{utils.get_current_date()}.json"
        return f"{base_path}/{file_name}"

    def get_hotspot_board_json_path(self, board_name: str = "搜索热点总榜") -> str:
        """热点榜 JSON：``{榜单名}_{日期}.json``"""
        safe_name = self.sanitize_filename(board_name, default="hotspot_board")
        if config.SAVE_DATA_PATH:
            base_path = f"{config.SAVE_DATA_PATH}/{self.platform}/json"
        else:
            base_path = f"data/{self.platform}/json"
        pathlib.Path(base_path).mkdir(parents=True, exist_ok=True)
        return f"{base_path}/{safe_name}_{utils.get_current_date()}.json"

    async def write_hotspot_board_json(
        self,
        board_name: str,
        payload: Dict[str, Any],
    ) -> str:
        """整榜覆盖写入热点榜 JSON。"""
        file_path = self.get_hotspot_board_json_path(board_name)
        async with self.lock:
            data = payload.setdefault("data", {})
            summary = data.setdefault("summary", {})
            summary["source_file"] = file_path
            summary["item_count"] = len(data.get("items") or [])
            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(payload, ensure_ascii=False, indent=2))
        return file_path

    @staticmethod
    def _default_creator_json_payload() -> dict[str, Any]:
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "profile": None,
                "awemes": [],
                "summary": {},
            },
        }

    @staticmethod
    def _merge_awemes_by_id(
        existing: list[dict[str, Any]],
        incoming: dict[str, Any],
        id_field: str = "aweme_id",
    ) -> list[dict[str, Any]]:
        record_id = str(incoming.get(id_field) or "").strip()
        if not record_id:
            return existing

        merged: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for item in existing:
            item_id = str(item.get(id_field) or "").strip()
            if not item_id or item_id in merged:
                continue
            merged[item_id] = item
            order.append(item_id)

        if record_id not in merged:
            order.append(record_id)
        merged[record_id] = incoming
        return [merged[item_id] for item_id in order]

    @staticmethod
    def _build_douyin_creator_summary(
        profile: Optional[dict[str, Any]],
        awemes: list[dict[str, Any]],
        source_file: str,
    ) -> dict[str, Any]:
        profile = profile or {}
        return {
            "source_file": source_file,
            "nickname": profile.get("nickname", ""),
            "fans": profile.get("fans", ""),
            "follows": profile.get("follows", ""),
            "ip_location": profile.get("ip_location", ""),
            "aweme_count": len(awemes),
        }

    async def upsert_creator_combined_json(
        self,
        creator_nickname: str,
        *,
        profile: Optional[Dict[str, Any]] = None,
        aweme: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        博主模式合并 JSON：``{昵称}_{日期}.json``，结构为 profile + awemes。
        """
        file_path = self.get_creator_combined_json_path(creator_nickname)
        async with self.lock:
            payload = self._default_creator_json_payload()
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                    try:
                        content = await f.read()
                        if content:
                            loaded = json.loads(content)
                            if isinstance(loaded, dict):
                                payload = loaded
                    except json.JSONDecodeError:
                        pass

            data = payload.setdefault("data", {})
            if profile:
                data["profile"] = profile
            if aweme:
                awemes = list(data.get("awemes") or [])
                data["awemes"] = self._merge_awemes_by_id(awemes, aweme)

            data["summary"] = self._build_douyin_creator_summary(
                data.get("profile"),
                list(data.get("awemes") or []),
                file_path,
            )

            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(payload, ensure_ascii=False, indent=2))
        return file_path

    def _get_file_path(self, file_type: str, item_type: str) -> str:
        if config.SAVE_DATA_PATH:
            base_path = f"{config.SAVE_DATA_PATH}/{self.platform}/{file_type}"
        else:
            base_path = f"data/{self.platform}/{file_type}"
        pathlib.Path(base_path).mkdir(parents=True, exist_ok=True)
        file_name = f"{self.crawler_type}_{item_type}_{utils.get_current_date()}.{file_type}"
        return f"{base_path}/{file_name}"

    async def write_to_csv(self, item: Dict, item_type: str):
        file_path = self._get_file_path('csv', item_type)
        async with self.lock:
            file_exists = os.path.exists(file_path)
            async with aiofiles.open(file_path, 'a', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=item.keys())
                if not file_exists or await f.tell() == 0:
                    await writer.writeheader()
                await writer.writerow(item)

    def _load_existing_ids(self, file_path: str, unique_field: str) -> set[str]:
        """从已有 CSV 加载唯一键，保证同名文件重复爬取时只追加新数据。"""
        if file_path in self._csv_seen_ids:
            return self._csv_seen_ids[file_path]

        seen: set[str] = set()
        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    value = (row.get(unique_field) or "").strip()
                    if value:
                        seen.add(value)

        self._csv_seen_ids[file_path] = seen
        return seen

    async def write_to_custom_csv(
        self,
        file_path: str,
        item: Dict,
        fieldnames: List[str],
        unique_field: Optional[str] = None,
    ) -> bool:
        """
        追加写入自定义 CSV，永不覆盖已有内容。

        Args:
            unique_field: 去重字段（如 note_id、comment_id）。已存在则跳过，只写入新记录。

        Returns:
            True 表示写入成功，False 表示因重复而跳过。
        """
        async with self.lock:
            if unique_field:
                seen = self._load_existing_ids(file_path, unique_field)
                unique_value = (item.get(unique_field) or "").strip()
                if unique_value and unique_value in seen:
                    return False
                if unique_value:
                    seen.add(unique_value)

            file_exists = os.path.exists(file_path) and os.path.getsize(file_path) > 0
            async with aiofiles.open(file_path, 'a', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                if not file_exists:
                    await writer.writeheader()
                row = {field: item.get(field, "") for field in fieldnames}
                await writer.writerow(row)
            return True

    async def write_to_jsonl(self, item: Dict, item_type: str):
        file_path = self._get_file_path('jsonl', item_type)
        async with self.lock:
            async with aiofiles.open(file_path, 'a', encoding='utf-8') as f:
                await f.write(json.dumps(item, ensure_ascii=False) + '\n')

    async def write_single_item_to_json(
        self,
        item: Dict,
        item_type: str,
        file_path: Optional[str] = None,
        unique_field: Optional[str] = "note_id",
    ):
        if not file_path:
            file_path = self._get_file_path('json', item_type)
        async with self.lock:
            existing_data = []
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                    try:
                        content = await f.read()
                        if content:
                            existing_data = json.loads(content)
                        if not isinstance(existing_data, list):
                            existing_data = [existing_data]
                    except json.JSONDecodeError:
                        existing_data = []

            if unique_field:
                new_id = str(item.get(unique_field) or "").strip()
                if new_id:
                    for old in existing_data:
                        if isinstance(old, dict) and str(old.get(unique_field) or "").strip() == new_id:
                            return

            existing_data.append(item)

            async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(existing_data, ensure_ascii=False, indent=4))

    async def generate_wordcloud_from_comments(self):
        """
        Generate wordcloud from comments data
        Only works when ENABLE_GET_WORDCLOUD and ENABLE_GET_COMMENTS are True
        """
        if not config.ENABLE_GET_WORDCLOUD or not config.ENABLE_GET_COMMENTS:
            return

        if not self.wordcloud_generator:
            return

        try:
            # Read comments from JSON or JSONL file
            comments_data = []
            jsonl_file_path = self._get_file_path('jsonl', 'comments')
            json_file_path = self._get_file_path('json', 'comments')

            if os.path.exists(jsonl_file_path) and os.path.getsize(jsonl_file_path) > 0:
                async with aiofiles.open(jsonl_file_path, 'r', encoding='utf-8') as f:
                    async for line in f:
                        line = line.strip()
                        if line:
                            try:
                                comments_data.append(json.loads(line))
                            except json.JSONDecodeError:
                                continue
            elif os.path.exists(json_file_path) and os.path.getsize(json_file_path) > 0:
                async with aiofiles.open(json_file_path, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    if content:
                        comments_data = json.loads(content)
                        if not isinstance(comments_data, list):
                            comments_data = [comments_data]

            if not comments_data:
                utils.logger.info(f"[AsyncFileWriter.generate_wordcloud_from_comments] No comments data found")
                return

            # Filter comments data to only include 'content' field
            # Handle different comment data structures across platforms
            filtered_data = []
            for comment in comments_data:
                if isinstance(comment, dict):
                    # Try different possible content field names
                    content_text = comment.get('content') or comment.get('comment_text') or comment.get('text') or ''
                    if content_text:
                        filtered_data.append({'content': content_text})

            if not filtered_data:
                utils.logger.info(f"[AsyncFileWriter.generate_wordcloud_from_comments] No valid comment content found")
                return

            # Generate wordcloud
            if config.SAVE_DATA_PATH:
                words_base_path = f"{config.SAVE_DATA_PATH}/{self.platform}/words"
            else:
                words_base_path = f"data/{self.platform}/words"
            pathlib.Path(words_base_path).mkdir(parents=True, exist_ok=True)
            words_file_prefix = f"{words_base_path}/{self.crawler_type}_comments_{utils.get_current_date()}"

            utils.logger.info(f"[AsyncFileWriter.generate_wordcloud_from_comments] Generating wordcloud from {len(filtered_data)} comments")
            await self.wordcloud_generator.generate_word_frequency_and_cloud(filtered_data, words_file_prefix)
            utils.logger.info(f"[AsyncFileWriter.generate_wordcloud_from_comments] Wordcloud generated successfully at {words_file_prefix}")

        except Exception as e:
            utils.logger.error(f"[AsyncFileWriter.generate_wordcloud_from_comments] Error generating wordcloud: {e}")
