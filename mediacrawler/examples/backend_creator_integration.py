# -*- coding: utf-8 -*-
"""
后端接入示例 —— 演示如何在业务代码中使用 services 包。

运行方式（在项目根目录执行）::

    uv run python examples/backend_creator_integration.py

前置条件:
    已运行过 creator 模式爬虫，且存在合并 CSV，例如:
    data/xhs/csv/Charon💕_2026-07-07.csv
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 将项目根目录加入 sys.path，确保能 import services 包
# 若后端项目与 MediaCrawler 在同一仓库，可省略此步
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services import XhsCreatorService, XhsCreatorDataset


def demo_load_by_nickname():
    """示例 1：按博主昵称加载最新数据"""
    print("=" * 60)
    print("示例 1：按博主昵称加载")
    print("=" * 60)

    service = XhsCreatorService(data_dir="data/xhs/csv")

    # 按昵称加载（自动找最新的 Charon💕_YYYY-MM-DD.csv）
    dataset = service.load_by_nickname("Charon💕")

    print(f"数据来源: {dataset.source_file}")
    print(f"博主昵称: {dataset.profile.nickname}")
    print(f"个人简介: {dataset.profile.desc[:50]}..." if dataset.profile else "无简介")
    print(f"粉丝数:   {dataset.profile.fans}")
    print(f"笔记数量: {dataset.note_count}")
    print()


def demo_iterate_notes():
    """示例 2：遍历笔记列表"""
    print("=" * 60)
    print("示例 2：遍历笔记")
    print("=" * 60)

    service = XhsCreatorService()
    dataset = service.load_latest()

    # 只打印前 3 篇
    for i, note in enumerate(dataset.notes[:3], start=1):
        print(f"[{i}] {note.title}")
        print(f"    点赞: {note.liked_count}  评论: {note.comment_count}")
        print(f"    链接: {note.note_url}")
        print(f"    图片数: {len(note.image_urls())}")
        print()


def demo_export_json():
    """示例 3：导出 JSON 供前端或其他服务使用"""
    print("=" * 60)
    print("示例 3：导出 JSON")
    print("=" * 60)

    service = XhsCreatorService()
    dataset = service.load_latest()

    # 方式 A：拿到 JSON 字符串
    json_str = service.export_json(dataset)
    print(f"JSON 长度: {len(json_str)} 字符")

    # 方式 B：写入文件
    output = service.export_json_file(dataset, "data/xhs/export/latest_creator.json")
    print(f"已导出到: {output}")
    print()


def demo_to_db_records():
    """示例 4：转换为入库格式"""
    print("=" * 60)
    print("示例 4：转换为入库格式")
    print("=" * 60)

    service = XhsCreatorService()
    dataset = service.load_latest()

    records = service.to_db_records(dataset)

    print("博主记录字段:", list(records["creator"].keys()) if records["creator"] else "无")
    print(f"笔记记录数: {len(records['notes'])}")
    print(f"元信息: {records['meta']}")

    # 伪代码：后端同事在此处对接自己的数据库
    # db.insert_creator(records["creator"])
    # db.batch_insert_notes(records["notes"])
    print()


def demo_api_response():
    """示例 5：生成标准 API 响应体"""
    print("=" * 60)
    print("示例 5：标准 API 响应")
    print("=" * 60)

    service = XhsCreatorService()
    dataset = service.load_latest()

    response = service.to_api_response(dataset)
    print(json.dumps(response, ensure_ascii=False, indent=2)[:500], "...")
    print()


def demo_list_creators():
    """示例 6：列出所有已爬取的博主"""
    print("=" * 60)
    print("示例 6：列出所有博主 CSV")
    print("=" * 60)

    service = XhsCreatorService()
    creators = service.list_available_creators()

    for item in creators:
        print(f"  {item['nickname']:15s}  粉丝:{item['fans']:8s}  笔记:{item['note_count']:3d}  文件:{item['file_name']}")
    print()


def demo_direct_dataset():
    """示例 7：不经过 Service，直接使用 Dataset（底层用法）"""
    print("=" * 60)
    print("示例 7：直接使用 XhsCreatorDataset")
    print("=" * 60)

    # 直接指定文件路径
    dataset = XhsCreatorDataset.from_csv("data/xhs/csv/Charon💕_2026-07-07.csv")

    # 按 note_id 查找
    if dataset.notes:
        first_note_id = dataset.notes[0].note_id
        found = dataset.get_note_by_id(first_note_id)
        print(f"查找 note_id={first_note_id}: {found.title if found else '未找到'}")

    # Top 笔记
    top3 = dataset.top_notes_by_likes(limit=3)
    print("点赞 Top 3:")
    for note in top3:
        print(f"  {note.liked_count:8s}  {note.title}")
    print()


if __name__ == "__main__":
    try:
        demo_load_by_nickname()
        demo_iterate_notes()
        demo_export_json()
        demo_to_db_records()
        demo_api_response()
        demo_list_creators()
        demo_direct_dataset()
        print("全部示例运行完成。")
    except FileNotFoundError as e:
        print(f"错误: {e}")
        print("请先运行 creator 模式爬虫生成 CSV 文件。")
        sys.exit(1)
