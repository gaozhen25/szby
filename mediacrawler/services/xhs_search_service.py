# -*- coding: utf-8 -*-
"""
小红书关键词搜索数据 —— 业务服务层。

后端同事推荐直接使用 ``XhsSearchService``。

典型接入流程::

    1. 爬虫以 search 模式跑完，生成 {关键词}_{日期}.csv
    2. 后端 import XhsSearchService
    3. service.load_by_keyword("美食") 拿到结构化数据
    4. service.to_db_records(dataset) 转成入库格式
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .xhs_search_dataset import (
    XhsSearchComment,
    XhsSearchDataset,
    XhsSearchNote,
    _find_search_csv_candidates,
)


class XhsSearchService:
    """
    小红书关键词搜索数据服务类。

    所有方法均为无副作用的读取操作。

    Args:
        data_dir: CSV 文件目录，默认 ``data/xhs/csv``。

    Example::

        service = XhsSearchService()

        # 加载最新一次搜索，并按关键词过滤
        dataset = service.load_by_keyword("美食")

        # 按关键词分组
        grouped = service.group_by_keyword(dataset)

        # 导出 JSON
        json_str = service.export_json(dataset)
    """

    def __init__(self, data_dir: str | Path = "data/xhs/csv"):
        self.data_dir = Path(data_dir)

    # ------------------------------------------------------------------
    # 加载方法
    # ------------------------------------------------------------------

    def load_by_file(
        self,
        csv_path: str | Path,
        keyword: Optional[str] = None,
        with_comments: bool = False,
    ) -> XhsSearchDataset:
        """
        从指定 search_contents CSV 加载。

        Args:
            csv_path: 笔记 CSV 路径。
            keyword: 可选，只保留该关键词的笔记。
            with_comments: 是否同时加载同批次的评论 CSV。
        """
        dataset = XhsSearchDataset.from_contents_csv(csv_path, keyword_filter=keyword)
        if with_comments:
            dataset.load_comments()
        return dataset

    def load_latest(
        self,
        keyword: Optional[str] = None,
        with_comments: bool = False,
    ) -> XhsSearchDataset:
        """
        加载目录下最新一次 search_contents CSV。

        Args:
            keyword: 可选，只保留该关键词的笔记。
            with_comments: 是否同时加载评论。
        """
        dataset = XhsSearchDataset.from_search_dir(self.data_dir, keyword=keyword)
        if with_comments:
            dataset.load_comments()
        return dataset

    def load_by_keyword(
        self,
        keyword: str,
        with_comments: bool = False,
    ) -> XhsSearchDataset:
        """
        从最新搜索 CSV 中加载指定关键词的笔记。

        Args:
            keyword: 搜索关键词，如 ``"美食"``。
            with_comments: 是否同时加载评论。

        Returns:
            只包含该关键词笔记的 XhsSearchDataset。
        """
        return self.load_latest(keyword=keyword, with_comments=with_comments)

    def load_all_keywords(self, with_comments: bool = False) -> XhsSearchDataset:
        """
        加载最新搜索 CSV 中的全部关键词笔记（不过滤）。

        Returns:
            包含所有关键词笔记的 XhsSearchDataset。
        """
        return self.load_latest(keyword=None, with_comments=with_comments)

    def list_available_searches(self) -> list[dict[str, Any]]:
        """
        扫描目录，返回所有关键词搜索 CSV 的摘要。

        支持新格式 ``美食_2026-07-06.csv`` 与旧格式 ``search_contents_*.csv``。

        Returns:
            列表，每项含 file_name、date、keywords、note_count 等。
        """
        if not self.data_dir.exists():
            return []

        results: list[dict[str, Any]] = []
        for csv_file in _find_search_csv_candidates(self.data_dir):
            try:
                dataset = XhsSearchDataset.from_contents_csv(csv_file)
                results.append({
                    "file_name": csv_file.name,
                    "file_path": str(csv_file),
                    "date": XhsSearchDataset.infer_date_from_contents_path(csv_file),
                    "keywords": dataset.keywords,
                    "note_count": dataset.note_count,
                    "modified_at": csv_file.stat().st_mtime,
                })
            except Exception:
                continue
        return results

    # ------------------------------------------------------------------
    # 数据读取方法
    # ------------------------------------------------------------------

    def get_notes(self, dataset: XhsSearchDataset) -> list[XhsSearchNote]:
        """获取全部笔记。"""
        return dataset.notes

    def get_keywords(self, dataset: XhsSearchDataset) -> list[str]:
        """获取涉及的关键词列表。"""
        return dataset.keywords

    def group_by_keyword(self, dataset: XhsSearchDataset) -> dict[str, list[XhsSearchNote]]:
        """按关键词分组笔记。"""
        return dataset.group_by_keyword()

    def get_note_by_id(self, dataset: XhsSearchDataset, note_id: str) -> Optional[XhsSearchNote]:
        """按 note_id 查找笔记。"""
        return dataset.get_note_by_id(note_id)

    def get_comments_for_note(
        self, dataset: XhsSearchDataset, note_id: str
    ) -> list[XhsSearchComment]:
        """获取某篇笔记的评论（需先 with_comments=True 加载）。"""
        return dataset.get_comments_by_note_id(note_id)

    # ------------------------------------------------------------------
    # 导出 / 转换方法
    # ------------------------------------------------------------------

    def export_json(self, dataset: XhsSearchDataset, indent: int = 2) -> str:
        """序列化为 JSON 字符串。"""
        return json.dumps(dataset.to_dict(), ensure_ascii=False, indent=indent)

    def export_json_file(self, dataset: XhsSearchDataset, output_path: str | Path) -> str:
        """导出为 JSON 文件，返回写入路径。"""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.export_json(dataset), encoding="utf-8")
        return str(path.resolve())

    def export_by_keyword_files(
        self,
        dataset: XhsSearchDataset,
        output_dir: str | Path,
    ) -> list[str]:
        """
        按关键词拆分为多个 JSON 文件，便于分关键词入库。

        输出示例::
            output_dir/美食_2026-07-06.json
            output_dir/旅游_2026-07-06.json

        Returns:
            写入的文件路径列表。
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        date = XhsSearchDataset.infer_date_from_contents_path(dataset.source_file) or "unknown"
        written: list[str] = []

        for kw, notes in dataset.group_by_keyword().items():
            safe_kw = kw.replace("/", "_").replace("\\", "_") or "unknown"
            sub_dataset = XhsSearchDataset(
                keywords=[kw],
                notes=notes,
                source_file=dataset.source_file,
                note_count=len(notes),
            )
            file_path = out / f"{safe_kw}_{date}.json"
            file_path.write_text(self.export_json(sub_dataset), encoding="utf-8")
            written.append(str(file_path.resolve()))

        return written

    def to_db_records(self, dataset: XhsSearchDataset) -> dict[str, Any]:
        """
        转换为适合入库的结构。

        返回格式::

            {
                "keywords": ["美食", "旅游"],
                "notes": [ {...}, {...} ],
                "comments": [ {...} ],   # 若已加载评论
                "grouped_notes": {
                    "美食": [ {...}, ... ],
                    "旅游": [ {...}, ... ],
                },
                "meta": { ... }
            }
        """
        grouped = dataset.group_by_keyword()
        return {
            "keywords": dataset.keywords,
            "notes": [note.model_dump() for note in dataset.notes],
            "comments": [c.model_dump() for c in dataset.comments],
            "grouped_notes": {
                kw: [n.model_dump() for n in notes]
                for kw, notes in grouped.items()
            },
            "meta": {
                "source_file": dataset.source_file,
                "comments_file": dataset.comments_file,
                "note_count": dataset.note_count,
                "comment_count": dataset.comment_count,
            },
        }

    def to_api_response(self, dataset: XhsSearchDataset) -> dict[str, Any]:
        """
        转换为标准 API 响应格式。

        响应结构::

            {
                "code": 0,
                "message": "ok",
                "data": {
                    "keywords": [...],
                    "notes": [...],
                    "comments": [...],
                    "grouped_notes": {...},
                    "summary": {...}
                }
            }
        """
        grouped = dataset.group_by_keyword()
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "keywords": dataset.keywords,
                "notes": [n.model_dump() for n in dataset.notes],
                "comments": [c.model_dump() for c in dataset.comments],
                "grouped_notes": {
                    kw: [n.model_dump() for n in notes]
                    for kw, notes in grouped.items()
                },
                "summary": dataset.summary(),
            },
        }
