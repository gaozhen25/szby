# -*- coding: utf-8 -*-
"""
后端接入示例 —— 关键词搜索爬取数据。

运行方式（在项目根目录执行）::

    uv run python examples/backend_search_integration.py

前置条件:
    已运行过 search 模式爬虫，且存在 CSV，例如:
    data/xhs/csv/美食_2026-07-06.csv

爬虫命令参考::

    uv run main.py --platform xhs --type search --lt qrcode --keywords "美食"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services import XhsSearchService, XhsSearchDataset


def demo_load_by_keyword():
    """示例 1：按关键词加载最新搜索结果"""
    print("=" * 60)
    print("示例 1：按关键词加载")
    print("=" * 60)

    service = XhsSearchService(data_dir="data/xhs/csv")
    dataset = service.load_by_keyword("美食")

    print(f"数据来源: {dataset.source_file}")
    print(f"关键词:   {dataset.keywords}")
    print(f"笔记数量: {dataset.note_count}")
    print()


def demo_load_all_and_group():
    """示例 2：加载全部关键词并按词分组"""
    print("=" * 60)
    print("示例 2：按关键词分组")
    print("=" * 60)

    service = XhsSearchService()
    # 分别加载每个关键词文件（新命名：美食_日期.csv / 旅游_日期.csv）
    for item in service.list_available_searches():
        ds = service.load_by_file(item["file_path"])
        for kw, notes in ds.group_by_keyword().items():
            print(f"  关键词「{kw}」: {len(notes)} 篇笔记")
    print()


def demo_iterate_notes():
    """示例 3：遍历笔记"""
    print("=" * 60)
    print("示例 3：遍历笔记（前 3 篇）")
    print("=" * 60)

    service = XhsSearchService()
    dataset = service.load_by_keyword("美食")

    for i, note in enumerate(dataset.notes[:3], start=1):
        print(f"[{i}] {note.title}")
        print(f"    关键词: {note.source_keyword}")
        print(f"    点赞: {note.liked_count}  作者: {note.nickname}")
        print(f"    链接: {note.note_url}")
        print()


def demo_top_notes():
    """示例 4：点赞 Top 笔记"""
    print("=" * 60)
    print("示例 4：点赞 Top 5")
    print("=" * 60)

    service = XhsSearchService()
    dataset = service.load_by_keyword("美食")

    for note in dataset.top_notes_by_likes(limit=5):
        print(f"  {note.liked_count:8s}  {note.title[:40]}")
    print()


def demo_export_json():
    """示例 5：导出 JSON"""
    print("=" * 60)
    print("示例 5：导出 JSON")
    print("=" * 60)

    service = XhsSearchService()
    dataset = service.load_by_keyword("美食")

    output = service.export_json_file(
        dataset, "data/xhs/export/search_美食_latest.json"
    )
    print(f"已导出到: {output}")
    print()


def demo_export_by_keyword():
    """示例 6：按关键词拆分导出多个 JSON 文件"""
    print("=" * 60)
    print("示例 6：按关键词拆分导出")
    print("=" * 60)

    service = XhsSearchService()
    written = []
    for item in service.list_available_searches():
        ds = service.load_by_file(item["file_path"])
        written.extend(service.export_by_keyword_files(ds, "data/xhs/export/by_keyword"))
    for f in written:
        print(f"  {f}")
    print()


def demo_to_db_records():
    """示例 7：转换为入库格式"""
    print("=" * 60)
    print("示例 7：转换为入库格式")
    print("=" * 60)

    service = XhsSearchService()
    dataset = service.load_by_keyword("美食")

    records = service.to_db_records(dataset)
    print(f"关键词: {records['keywords']}")
    print(f"笔记数: {len(records['notes'])}")
    print(f"分组:   {list(records['grouped_notes'].keys())}")

    # 伪代码：后端入库
    # for kw, notes in records["grouped_notes"].items():
    #     db.batch_insert_search_notes(keyword=kw, notes=notes)
    print()


def demo_api_response():
    """示例 8：标准 API 响应体"""
    print("=" * 60)
    print("示例 8：标准 API 响应")
    print("=" * 60)

    service = XhsSearchService()
    dataset = service.load_by_keyword("美食")

    response = service.to_api_response(dataset)
    print(json.dumps(response, ensure_ascii=False, indent=2)[:600], "...")
    print()


def demo_list_searches():
    """示例 9：列出所有历史搜索 CSV"""
    print("=" * 60)
    print("示例 9：列出历史搜索")
    print("=" * 60)

    service = XhsSearchService()
    for item in service.list_available_searches():
        print(
            f"  {item['date']}  关键词:{item['keywords']}  "
            f"笔记:{item['note_count']:3d}  文件:{item['file_name']}"
        )
    print()


def demo_direct_dataset():
    """示例 10：直接使用 Dataset（底层用法）"""
    print("=" * 60)
    print("示例 10：直接使用 XhsSearchDataset")
    print("=" * 60)

    dataset = XhsSearchDataset.from_search_dir("data/xhs/csv", keyword="美食")
    print(f"摘要: {dataset.summary()}")

    note = dataset.get_note_by_id(dataset.notes[0].note_id) if dataset.notes else None
    if note:
        print(f"首篇笔记: {note.title}")
        print(f"话题标签: {note.topic_tags()[:3]}")
    print()


if __name__ == "__main__":
    try:
        demo_load_by_keyword()
        demo_load_all_and_group()
        demo_iterate_notes()
        demo_top_notes()
        demo_export_json()
        demo_export_by_keyword()
        demo_to_db_records()
        demo_api_response()
        demo_list_searches()
        demo_direct_dataset()
        print("全部示例运行完成。")
    except FileNotFoundError as e:
        print(f"错误: {e}")
        print('请先运行: uv run main.py --platform xhs --type search --lt qrcode --keywords "美食"')
        sys.exit(1)
