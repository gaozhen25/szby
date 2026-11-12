# -*- coding: utf-8 -*-
"""
小红书关键词搜索爬取结果 —— 数据模型层。

对应 CSV 文件格式（由 search 模式 + csv 存储生成）:
    笔记文件: data/xhs/csv/search_contents_{日期}.csv
    评论文件: data/xhs/csv/search_comments_{日期}.csv  （开启评论爬取时才有）

每行笔记通过 ``source_keyword`` 字段标记所属搜索关键词。
若一次爬取配置了多个关键词（如 "美食,旅游"），会写入同一个 CSV，
后端可按关键词分组读取。

本模块只负责「数据结构定义」和「从 CSV 解析」，
更高层的查询/导出逻辑见 xhs_search_service.py。
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from tools.async_file_writer import AsyncFileWriter


# 旧格式文件前缀（向后兼容）
OLD_SEARCH_FILE_PREFIXES = ("creator_", "search_", "detail_")
# 新格式：{关键词}_{日期}.csv
KEYWORD_DATE_PATTERN = re.compile(r"^(.+)_(\d{4}-\d{2}-\d{2})\.csv$")


def _is_search_contents_csv(path: Path) -> bool:
    """判断是否为关键词搜索笔记 CSV（新格式或旧 search_contents 格式）。"""
    name = path.name
    if name.startswith(OLD_SEARCH_FILE_PREFIXES):
        return False
    if "_comments_" in name:
        return False
    if name.startswith("search_contents_") and name.endswith(".csv"):
        return True
    if not KEYWORD_DATE_PATTERN.match(name):
        return False
    try:
        with open(path, encoding="utf-8-sig") as f:
            header = f.readline().strip()
        # 博主合并 CSV 首列为 record_type，搜索 CSV 首列为 note_id
        return header.startswith("note_id,")
    except OSError:
        return False


def _find_search_csv_candidates(
    directory: Path,
    keyword: Optional[str] = None,
) -> list[Path]:
    """在目录中查找关键词搜索笔记 CSV 候选文件。"""
    candidates: list[Path] = []
    safe_kw = AsyncFileWriter.sanitize_filename(keyword, default="unknown_keyword") if keyword else None

    for path in directory.glob("*.csv"):
        if not _is_search_contents_csv(path):
            continue
        if safe_kw and not path.name.startswith(f"{safe_kw}_") and not path.name.startswith("search_contents_"):
            continue
        candidates.append(path)

    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)


def _infer_comments_csv_path(contents_path: Path) -> Path:
    """
    根据笔记 CSV 路径推断评论 CSV 路径。

    新格式: 美食_2026-07-06.csv → 美食_comments_2026-07-06.csv
    旧格式: search_contents_2026-07-06.csv → search_comments_2026-07-06.csv
    """
    match = KEYWORD_DATE_PATTERN.match(contents_path.name)
    if match:
        keyword_part, date_part = match.group(1), match.group(2)
        return contents_path.parent / f"{keyword_part}_comments_{date_part}.csv"
    if contents_path.name.startswith("search_contents_"):
        date_suffix = contents_path.stem.replace("search_contents_", "")
        return contents_path.parent / f"search_comments_{date_suffix}.csv"
    return contents_path.parent / "search_comments_unknown.csv"


# ---------------------------------------------------------------------------
# 搜索笔记模型
# ---------------------------------------------------------------------------

class XhsSearchNote(BaseModel):
    """
    关键词搜索到的单篇笔记。

    字段与 ``search_contents_*.csv`` 列名一一对应。
    ``source_keyword`` 是区分不同搜索词的关键字段。
    """

    note_id: str = Field(default="", description="笔记唯一 ID")
    type: str = Field(default="", description="笔记类型，如 normal / video")
    title: str = Field(default="", description="笔记标题")
    desc: str = Field(default="", description="笔记正文")
    video_url: str = Field(default="", description="视频地址（视频笔记才有）")
    time: str = Field(default="", description="发布时间戳（毫秒）")
    last_update_time: str = Field(default="", description="最后更新时间戳")
    creator_hash: str = Field(default="", description="作者匿名哈希")
    nickname: str = Field(default="", description="作者昵称（脱敏）")
    liked_count: str = Field(default="", description="点赞数")
    collected_count: str = Field(default="", description="收藏数")
    comment_count: str = Field(default="", description="评论数")
    share_count: str = Field(default="", description="分享数")
    image_list: str = Field(default="", description="图片 URL 列表，逗号分隔")
    tag_list: str = Field(default="", description="话题标签，逗号分隔")
    last_modify_ts: str = Field(default="", description="数据写入时间戳")
    note_url: str = Field(default="", description="笔记原始链接")
    source_keyword: str = Field(default="", description="搜索关键词，如「美食」")
    xsec_token: str = Field(default="", description="访问令牌")

    def image_urls(self) -> list[str]:
        """将 image_list 拆分为 URL 列表。"""
        if not self.image_list:
            return []
        return [url.strip() for url in self.image_list.split(",") if url.strip()]

    def topic_tags(self) -> list[str]:
        """将 tag_list 拆分为话题标签列表。"""
        if not self.tag_list:
            return []
        return [tag.strip() for tag in self.tag_list.split(",") if tag.strip()]


# ---------------------------------------------------------------------------
# 搜索评论模型（可选）
# ---------------------------------------------------------------------------

class XhsSearchComment(BaseModel):
    """
    关键词搜索笔记下的评论。

    对应 ``search_comments_*.csv``，通过 ``note_id`` 与笔记关联。
    """

    comment_id: str = Field(default="", description="评论 ID")
    create_time: str = Field(default="", description="评论时间戳")
    note_id: str = Field(default="", description="所属笔记 ID")
    content: str = Field(default="", description="评论正文")
    creator_hash: str = Field(default="", description="评论者匿名哈希")
    nickname: str = Field(default="", description="评论者昵称（脱敏）")
    sub_comment_count: str = Field(default="", description="子评论数量")
    pictures: str = Field(default="", description="评论图片 URL，逗号分隔")
    parent_comment_id: str = Field(default="", description="父评论 ID")
    last_modify_ts: str = Field(default="", description="数据写入时间戳")
    like_count: str = Field(default="", description="评论点赞数")


# ---------------------------------------------------------------------------
# 关键词搜索完整数据集
# ---------------------------------------------------------------------------

class XhsSearchDataset(BaseModel):
    """
    一次关键词搜索爬取的完整数据集。

    包含:
        - keywords   : 本次 CSV 中出现的所有搜索关键词（去重）
        - notes      : 笔记列表（可按 source_keyword 过滤）
        - comments   : 评论列表（可选，需单独加载）
        - note_count : 笔记总数

    基本用法::

        dataset = XhsSearchDataset.from_contents_csv(
            "data/xhs/csv/美食_2026-07-06.csv"
        )
        print(dataset.keywords)           # ['美食']
        food_notes = dataset.filter_by_keyword("美食")
        grouped = dataset.group_by_keyword()
    """

    keywords: list[str] = Field(default_factory=list, description="涉及的搜索关键词列表")
    notes: list[XhsSearchNote] = Field(default_factory=list, description="搜索到的笔记")
    comments: list[XhsSearchComment] = Field(default_factory=list, description="评论（可选）")
    source_file: str = Field(default="", description="笔记 CSV 文件路径")
    comments_file: str = Field(default="", description="评论 CSV 文件路径（若有）")
    note_count: int = Field(default=0, description="笔记总数")
    comment_count: int = Field(default=0, description="评论总数")

    # ----- 工厂方法 -----

    @classmethod
    def from_contents_csv(
        cls,
        csv_path: str | Path,
        keyword_filter: Optional[str] = None,
    ) -> "XhsSearchDataset":
        """
        从 search_contents CSV 加载笔记数据。

        Args:
            csv_path: 笔记 CSV 路径，如 ``美食_2026-07-06.csv``。
            keyword_filter: 可选，只保留指定关键词的笔记。

        Returns:
            XhsSearchDataset 实例。
        """
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV 文件不存在: {path}")

        notes: list[XhsSearchNote] = []
        keyword_set: set[str] = set()

        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                note = XhsSearchNote.model_validate(row)
                kw = (note.source_keyword or "").strip()
                if kw:
                    keyword_set.add(kw)
                if keyword_filter and kw != keyword_filter.strip():
                    continue
                notes.append(note)

        keywords = sorted(keyword_set)
        if keyword_filter and keyword_filter.strip() not in keyword_set:
            # 过滤后仍保留用户指定的关键词（即使无结果）
            keywords = [keyword_filter.strip()]

        return cls(
            keywords=keywords if not keyword_filter else [keyword_filter.strip()],
            notes=notes,
            source_file=str(path.resolve()),
            note_count=len(notes),
        )

    @classmethod
    def from_search_dir(
        cls,
        data_dir: str | Path = "data/xhs/csv",
        keyword: Optional[str] = None,
    ) -> "XhsSearchDataset":
        """
        从目录中自动查找最新的关键词搜索 CSV 并加载。

        支持两种文件命名:
            - 新格式: ``美食_2026-07-06.csv``
            - 旧格式: ``search_contents_2026-07-06.csv``（向后兼容）

        Args:
            data_dir: CSV 目录，默认 ``data/xhs/csv``。
            keyword: 可选，只加载该关键词的笔记。

        Returns:
            XhsSearchDataset 实例。
        """
        directory = Path(data_dir)
        if not directory.exists():
            raise FileNotFoundError(f"数据目录不存在: {directory}")

        candidates = _find_search_csv_candidates(directory, keyword=keyword)
        if not candidates:
            hint = f"（keyword={keyword!r}）" if keyword else ""
            raise FileNotFoundError(f"在 {directory} 中未找到关键词搜索 CSV {hint}")

        return cls.from_contents_csv(candidates[0], keyword_filter=keyword)

    def load_comments(self, comments_csv_path: Optional[str | Path] = None) -> "XhsSearchDataset":
        """
        加载与本次搜索同批次的评论 CSV，并挂载到当前 Dataset。

        若未指定路径，则根据笔记文件名自动推断::
            美食_2026-07-06.csv → 美食_comments_2026-07-06.csv

        Args:
            comments_csv_path: 评论 CSV 路径，为 None 时自动推断。

        Returns:
            self（支持链式调用）。
        """
        if comments_csv_path is None:
            comments_csv_path = _infer_comments_csv_path(Path(self.source_file))

        path = Path(comments_csv_path)
        if not path.exists():
            return self  # 无评论文件时静默跳过

        comments: list[XhsSearchComment] = []
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                comments.append(XhsSearchComment.model_validate(row))

        self.comments = comments
        self.comments_file = str(path.resolve())
        self.comment_count = len(comments)
        return self

    # ----- 查询方法 -----

    def filter_by_keyword(self, keyword: str) -> list[XhsSearchNote]:
        """返回指定关键词下的笔记列表。"""
        kw = keyword.strip()
        return [n for n in self.notes if n.source_keyword.strip() == kw]

    def group_by_keyword(self) -> dict[str, list[XhsSearchNote]]:
        """按 source_keyword 分组，返回 {关键词: [笔记列表]} 字典。"""
        grouped: dict[str, list[XhsSearchNote]] = {}
        for note in self.notes:
            kw = note.source_keyword.strip() or "未知关键词"
            grouped.setdefault(kw, []).append(note)
        return grouped

    def get_note_by_id(self, note_id: str) -> Optional[XhsSearchNote]:
        """按 note_id 查找单篇笔记。"""
        for note in self.notes:
            if note.note_id == note_id:
                return note
        return None

    def get_comments_by_note_id(self, note_id: str) -> list[XhsSearchComment]:
        """获取某篇笔记下的全部评论（需先 load_comments）。"""
        return [c for c in self.comments if c.note_id == note_id]

    def top_notes_by_likes(self, limit: int = 10, keyword: Optional[str] = None) -> list[XhsSearchNote]:
        """
        按点赞数降序返回 Top N 笔记。

        Args:
            limit: 返回条数。
            keyword: 可选，只在指定关键词范围内排序。
        """
        pool = self.filter_by_keyword(keyword) if keyword else self.notes
        return sorted(pool, key=lambda n: n.liked_count, reverse=True)[:limit]

    # ----- 输出方法 -----

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict，适合 JSON 或入库。"""
        return self.model_dump()

    def summary(self) -> dict[str, Any]:
        """返回摘要信息，适合列表页展示。"""
        grouped = self.group_by_keyword()
        return {
            "source_file": self.source_file,
            "keywords": self.keywords,
            "note_count": self.note_count,
            "comment_count": self.comment_count,
            "notes_per_keyword": {kw: len(notes) for kw, notes in grouped.items()},
        }

    @staticmethod
    def infer_date_from_contents_path(csv_path: str | Path) -> Optional[str]:
        """
        从文件名提取日期。

        支持:
            - 美食_2026-07-06.csv → 2026-07-06
            - search_contents_2026-07-06.csv → 2026-07-06
        """
        name = Path(csv_path).name
        match = KEYWORD_DATE_PATTERN.match(name)
        if match:
            return match.group(2)
        legacy = re.search(r"search_contents_(\d{4}-\d{2}-\d{2})\.csv", name)
        return legacy.group(1) if legacy else None
