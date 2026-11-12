# -*- coding: utf-8 -*-
"""
小红书博主数据 —— 业务服务层。

后端同事推荐直接使用 ``XhsCreatorService``，而不是直接操作 Dataset。
Service 封装了常见的业务场景：加载、列表、导出、入库前转换等。

典型接入流程::

    1. 爬虫跑完，生成 data/xhs/csv/{昵称}_{日期}.csv
    2. 后端 import XhsCreatorService
    3. service.load_by_nickname("Charon💕") 拿到结构化数据
    4. service.to_db_records(dataset) 转成入库格式
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .xhs_creator_dataset import (
    XhsCreatorDataset,
    XhsCreatorNote,
    XhsCreatorProfile,
)


class XhsCreatorService:
    """
    小红书博主数据服务类。

    所有方法均为无副作用的读取操作（不写数据库、不修改 CSV）。
    后端可按需实例化，也可在 FastAPI 中作为依赖注入单例使用。

    Args:
        data_dir: CSV 文件所在目录，默认 ``data/xhs/csv``。
                  可通过构造参数覆盖，方便测试或多环境部署。

    Example::

        service = XhsCreatorService()

        # 加载指定博主最新数据
        dataset = service.load_by_nickname("Charon💕")

        # 获取简介
        profile = service.get_profile(dataset)

        # 获取所有笔记
        notes = service.get_notes(dataset)

        # 导出 JSON 给前端
        json_str = service.export_json(dataset)
    """

    def __init__(self, data_dir: str | Path = "data/xhs/csv"):
        self.data_dir = Path(data_dir)

    # ------------------------------------------------------------------
    # 加载方法
    # ------------------------------------------------------------------

    def load_by_file(self, csv_path: str | Path) -> XhsCreatorDataset:
        """
        从指定 CSV 文件路径加载数据。

        Args:
            csv_path: CSV 文件路径（相对项目根目录或绝对路径）。

        Returns:
            XhsCreatorDataset 实例。
        """
        return XhsCreatorDataset.from_csv(csv_path)

    def load_by_nickname(self, nickname: str) -> XhsCreatorDataset:
        """
        按博主昵称加载最新一份 CSV。

        会在 ``self.data_dir`` 下查找以 ``{nickname}_`` 开头的最新文件。

        Args:
            nickname: 博主昵称，需与 CSV 文件名前缀一致，如 ``"Charon💕"``。

        Returns:
            XhsCreatorDataset 实例。
        """
        return XhsCreatorDataset.from_combined_csv_dir(
            data_dir=self.data_dir,
            nickname=nickname,
        )

    def load_latest(self) -> XhsCreatorDataset:
        """
        加载目录下最新的一份博主 CSV（不指定昵称）。

        Returns:
            XhsCreatorDataset 实例。
        """
        return XhsCreatorDataset.from_combined_csv_dir(data_dir=self.data_dir)

    def list_available_creators(self) -> list[dict[str, Any]]:
        """
        扫描数据目录，返回所有可用博主 CSV 的摘要列表。

        适合后台管理页面展示「已爬取的博主」列表。

        Returns:
            列表，每项包含 file_name、nickname、modified_at、note_count 等。
        """
        if not self.data_dir.exists():
            return []

        OLD_PREFIXES = ("creator_", "search_", "detail_")
        results: list[dict[str, Any]] = []

        for csv_file in sorted(self.data_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True):
            if csv_file.name.startswith(OLD_PREFIXES):
                continue

            try:
                dataset = XhsCreatorDataset.from_csv(csv_file)
                if dataset.profile is None:
                    continue
                results.append({
                    "file_name": csv_file.name,
                    "file_path": str(csv_file),
                    "nickname": dataset.profile.nickname if dataset.profile else "",
                    "fans": dataset.profile.fans if dataset.profile else "",
                    "note_count": dataset.note_count,
                    "modified_at": csv_file.stat().st_mtime,
                })
            except Exception:
                # 跳过格式不符的文件，不影响其他文件
                continue

        return results

    # ------------------------------------------------------------------
    # 数据读取方法
    # ------------------------------------------------------------------

    def get_profile(self, dataset: XhsCreatorDataset) -> Optional[XhsCreatorProfile]:
        """从 Dataset 中获取博主简介，可能为 None。"""
        return dataset.profile

    def get_notes(self, dataset: XhsCreatorDataset) -> list[XhsCreatorNote]:
        """从 Dataset 中获取全部笔记列表。"""
        return dataset.notes

    def get_note_by_id(self, dataset: XhsCreatorDataset, note_id: str) -> Optional[XhsCreatorNote]:
        """按 note_id 查找单篇笔记。"""
        return dataset.get_note_by_id(note_id)

    # ------------------------------------------------------------------
    # 导出 / 转换方法（供入库或 API 返回）
    # ------------------------------------------------------------------

    def export_json(self, dataset: XhsCreatorDataset, indent: int = 2) -> str:
        """
        将 Dataset 序列化为 JSON 字符串。

        Args:
            dataset: 数据集实例。
            indent: JSON 缩进，默认 2。传 0 或 None 可压缩输出。

        Returns:
            JSON 字符串，可直接写入文件或作为 HTTP 响应体。
        """
        return json.dumps(dataset.to_dict(), ensure_ascii=False, indent=indent)

    def export_json_file(self, dataset: XhsCreatorDataset, output_path: str | Path) -> str:
        """
        将 Dataset 导出为 JSON 文件。

        Args:
            dataset: 数据集实例。
            output_path: 输出文件路径。

        Returns:
            写入的文件绝对路径。
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.export_json(dataset), encoding="utf-8")
        return str(path.resolve())

    def to_db_records(self, dataset: XhsCreatorDataset) -> dict[str, Any]:
        """
        将 Dataset 转换为适合入库的结构。

        返回格式::

            {
                "creator": { ... },   # 一条博主记录，可直接 INSERT
                "notes": [ ... ],       # 多条笔记记录列表
            }

        后端同事可在此基础上对接自己的 ORM / SQL：
            - creator 表：写入 profile 字段
            - note 表：批量写入 notes 列表，用 user_id 关联

        Args:
            dataset: 数据集实例。

        Returns:
            包含 creator 和 notes 两个 key 的字典。
        """
        creator_record: Optional[dict[str, Any]] = None
        if dataset.profile:
            creator_record = dataset.profile.model_dump()

        note_records = [note.model_dump() for note in dataset.notes]

        return {
            "creator": creator_record,
            "notes": note_records,
            "meta": {
                "source_file": dataset.source_file,
                "note_count": dataset.note_count,
            },
        }

    def to_api_response(self, dataset: XhsCreatorDataset) -> dict[str, Any]:
        """
        转换为标准 API 响应格式，可直接作为 FastAPI / Flask 的返回值。

        响应结构::

            {
                "code": 0,
                "message": "ok",
                "data": {
                    "profile": { ... },
                    "notes": [ ... ],
                    "summary": { ... }
                }
            }
        """
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "profile": dataset.profile.model_dump() if dataset.profile else None,
                "notes": [note.model_dump() for note in dataset.notes],
                "summary": dataset.summary(),
            },
        }
