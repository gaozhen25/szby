# -*- coding: utf-8 -*-
"""
小红书博主爬取结果 —— 数据模型层。

对应 CSV 文件格式（由 creator 模式 + csv 存储生成）:
    第 1 行  record_type=profile  → 博主简介
    第 2+ 行 record_type=note    → 博主笔记

文件命名规则:
    data/xhs/csv/{博主昵称}_{日期}.csv
    例如: data/xhs/csv/Charon💕_2026-07-07.csv

本模块只负责「数据结构定义」和「从 CSV 解析」，
更高层的查询/导出逻辑见 xhs_creator_service.py。
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 博主简介模型
# ---------------------------------------------------------------------------

class XhsCreatorProfile(BaseModel):
    """
    博主个人简介。

    对应 CSV 中 ``record_type=profile`` 的那一行。
    字段与爬虫写入 CSV 时的列名一一对应。
    """

    user_id: str = Field(default="", description="博主用户 ID（24 位十六进制）")
    nickname: str = Field(default="", description="博主昵称")
    gender: Optional[str] = Field(default=None, description="性别，如 Female / Male")
    avatar: str = Field(default="", description="头像图片 URL")
    desc: str = Field(default="", description="个人简介正文")
    ip_location: str = Field(default="", description="IP 属地，如「江苏」")
    follows: str = Field(default="", description="关注数")
    fans: str = Field(default="", description="粉丝数")
    interaction: str = Field(default="", description="获赞与收藏总数")
    tag_list: str = Field(default="", description="博主标签，JSON 字符串")
    last_modify_ts: str = Field(default="", description="数据写入时间戳（毫秒）")


# ---------------------------------------------------------------------------
# 博主笔记模型
# ---------------------------------------------------------------------------

class XhsCreatorNote(BaseModel):
    """
    博主发布的单篇笔记。

    对应 CSV 中 ``record_type=note`` 的每一行。
    字段与原先 creator_contents_*.csv 保持一致。
    """

    note_id: str = Field(default="", description="笔记唯一 ID")
    type: str = Field(default="", description="笔记类型，如 normal / video")
    title: str = Field(default="", description="笔记标题")
    desc: str = Field(default="", description="笔记正文")
    video_url: str = Field(default="", description="视频地址（视频笔记才有）")
    time: str = Field(default="", description="发布时间戳（毫秒）")
    last_update_time: str = Field(default="", description="最后更新时间戳")
    creator_hash: str = Field(default="", description="创作者匿名哈希（脱敏后的 ID）")
    nickname: str = Field(default="", description="作者昵称（脱敏）")
    liked_count: str = Field(default="", description="点赞数，如 3.2万")
    collected_count: str = Field(default="", description="收藏数")
    comment_count: str = Field(default="", description="评论数")
    share_count: str = Field(default="", description="分享数")
    image_list: str = Field(default="", description="图片 URL 列表，逗号分隔")
    tag_list: str = Field(default="", description="话题标签，逗号分隔")
    last_modify_ts: str = Field(default="", description="数据写入时间戳")
    note_url: str = Field(default="", description="笔记原始链接")
    source_keyword: str = Field(default="", description="来源关键词（creator 模式通常为空）")
    xsec_token: str = Field(default="", description="访问令牌，用于再次请求笔记详情")

    def image_urls(self) -> list[str]:
        """将 image_list 字段拆分为 URL 列表，方便后端直接使用。"""
        if not self.image_list:
            return []
        return [url.strip() for url in self.image_list.split(",") if url.strip()]

    def topic_tags(self) -> list[str]:
        """将 tag_list 字段拆分为话题标签列表。"""
        if not self.tag_list:
            return []
        return [tag.strip() for tag in self.tag_list.split(",") if tag.strip()]


# ---------------------------------------------------------------------------
# 博主完整数据集
# ---------------------------------------------------------------------------

class XhsCreatorDataset(BaseModel):
    """
    一个博主的完整数据集 = 简介 + 笔记列表。

    这是后端最常用的顶层对象，包含:
        - profile   : 博主简介（可能为 None，如果 CSV 里没有 profile 行）
        - notes     : 笔记列表
        - note_count: 笔记数量（冗余字段，方便直接读取）

    基本用法::

        dataset = XhsCreatorDataset.from_csv("data/xhs/csv/Charon💕_2026-07-07.csv")
        print(dataset.profile.nickname)   # Charon💕
        print(dataset.note_count)         # 50
        payload = dataset.to_dict()       # 转 dict 入库或序列化
    """

    profile: Optional[XhsCreatorProfile] = Field(
        default=None, description="博主简介，CSV 第一行"
    )
    notes: list[XhsCreatorNote] = Field(
        default_factory=list, description="博主笔记列表"
    )
    source_file: str = Field(default="", description="数据来源 CSV 文件路径")
    note_count: int = Field(default=0, description="笔记总数")

    # ----- 工厂方法：从 CSV 加载 -----

    @classmethod
    def from_csv(cls, csv_path: str | Path) -> "XhsCreatorDataset":
        """
        从指定的合并 CSV 文件加载数据。

        Args:
            csv_path: CSV 文件路径，相对或绝对均可。

        Returns:
            解析后的 XhsCreatorDataset 实例。

        Raises:
            FileNotFoundError: 文件不存在时抛出。

        Example::

            dataset = XhsCreatorDataset.from_csv(
                "data/xhs/csv/Charon💕_2026-07-07.csv"
            )
        """
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV 文件不存在: {path}")

        profile: Optional[XhsCreatorProfile] = None
        notes: list[XhsCreatorNote] = []

        # utf-8-sig 可自动处理 Excel 打开 CSV 时产生的 BOM 头
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                record_type = (row.get("record_type") or "").strip().lower()

                if record_type == "profile":
                    # 第一行：博主简介
                    profile = XhsCreatorProfile.model_validate(row)

                elif record_type == "note":
                    # 后续行：笔记内容
                    notes.append(XhsCreatorNote.model_validate(row))

                # 其他 record_type 忽略（兼容未来扩展）

        return cls(
            profile=profile,
            notes=notes,
            source_file=str(path.resolve()),
            note_count=len(notes),
        )

    @classmethod
    def from_combined_csv_dir(
        cls,
        data_dir: str | Path = "data/xhs/csv",
        nickname: Optional[str] = None,
    ) -> "XhsCreatorDataset":
        """
        从目录中自动查找并加载博主 CSV。

        查找规则:
            1. 只匹配 ``{昵称}_{日期}.csv`` 格式的文件
            2. 排除旧格式文件（creator_contents_*.csv 等）
            3. 若指定 nickname，按文件名前缀过滤
            4. 多个候选时取修改时间最新的

        Args:
            data_dir: CSV 所在目录，默认 ``data/xhs/csv``。
            nickname: 博主昵称前缀，如 ``"Charon💕"``。为 None 时取最新文件。

        Returns:
            解析后的 XhsCreatorDataset 实例。

        Raises:
            FileNotFoundError: 目录不存在或找不到匹配文件时抛出。
        """
        directory = Path(data_dir)
        if not directory.exists():
            raise FileNotFoundError(f"数据目录不存在: {directory}")

        # 过滤出博主合并 CSV（排除旧格式命名）
        OLD_PREFIXES = ("creator_", "search_", "detail_")
        candidates = [
            p for p in directory.glob("*.csv")
            if not p.name.startswith(OLD_PREFIXES)
        ]

        # 按昵称前缀进一步过滤
        if nickname:
            candidates = [p for p in candidates if p.name.startswith(nickname)]

        if not candidates:
            hint = f"（nickname={nickname!r}）" if nickname else ""
            raise FileNotFoundError(f"在 {directory} 中未找到博主 CSV {hint}")

        # 取最新修改的文件
        latest = max(candidates, key=lambda p: p.stat().st_mtime)
        return cls.from_csv(latest)

    # ----- 输出方法 -----

    def to_dict(self) -> dict[str, Any]:
        """
        序列化为普通 dict。

        适合:
            - ``json.dumps(dataset.to_dict())`` 转 JSON
            - 直接写入 MongoDB / 传给下游微服务
            - FastAPI 接口返回（配合 response_model 使用）
        """
        return self.model_dump()

    def summary(self) -> dict[str, Any]:
        """
        返回简要摘要，适合列表页 / 仪表盘展示。

        Returns:
            包含 source_file、nickname、fans、note_count 的字典。
        """
        return {
            "source_file": self.source_file,
            "nickname": self.profile.nickname if self.profile else "",
            "fans": self.profile.fans if self.profile else "",
            "follows": self.profile.follows if self.profile else "",
            "ip_location": self.profile.ip_location if self.profile else "",
            "note_count": self.note_count,
        }

    def get_note_by_id(self, note_id: str) -> Optional[XhsCreatorNote]:
        """按 note_id 查找单篇笔记，找不到返回 None。"""
        for note in self.notes:
            if note.note_id == note_id:
                return note
        return None

    def top_notes_by_likes(self, limit: int = 10) -> list[XhsCreatorNote]:
        """
        按点赞数降序返回 Top N 笔记。

        注意: liked_count 可能是「3.2万」这类中文格式，
        此处做简单字符串排序，精确数值排序需后端自行转换。
        """
        return sorted(
            self.notes,
            key=lambda n: n.liked_count,
            reverse=True,
        )[:limit]
