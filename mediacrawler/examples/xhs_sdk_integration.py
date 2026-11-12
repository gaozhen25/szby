# -*- coding: utf-8 -*-
"""
小红书数据 SDK 接入示例。

运行方式（在项目根目录执行）::

    uv run python examples/xhs_sdk_integration.py

可选：先启动 API 服务以演示远程模式::

    uv run uvicorn api.main:app --host 127.0.0.1 --port 8080
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sdk import XhsDataClient


def demo_local_search():
    print("=" * 60)
    print("本地模式：关键词搜索")
    print("=" * 60)

    client = XhsDataClient.local(data_dir="data/xhs/csv")
    dataset = client.search.load(keyword="旅游")

    print(f"数据来源: {dataset.source_file}")
    print(f"关键词:   {dataset.keywords}")
    print(f"笔记数量: {dataset.note_count}")

    summary = client.search.summary(keyword="旅游")
    print(f"摘要:     {summary}")
    print()


def demo_local_creator():
    print("=" * 60)
    print("本地模式：博主数据")
    print("=" * 60)

    client = XhsDataClient.local()
    creators = client.creator.list_available()
    if not creators:
        print("暂无博主 CSV，跳过")
        print()
        return

    item = creators[0]
    nickname = item["nickname"]
    dataset = client.creator.load(nickname=nickname)
    print(f"博主:     {dataset.profile.nickname if dataset.profile else nickname}")
    print(f"粉丝:     {dataset.profile.fans if dataset.profile else '-'}")
    print(f"笔记数:   {dataset.note_count}")

    records = client.creator.to_db_records(dataset)
    print(f"入库笔记: {len(records['notes'])} 条")
    print()


def demo_local_export_api_shape():
    print("=" * 60)
    print("本地模式：API 响应格式")
    print("=" * 60)

    client = XhsDataClient.local()
    response = client.search.export(keyword="旅游")
    print(f"code:     {response['code']}")
    print(f"notes:    {len(response['data']['notes'])} 条")
    print()


def demo_remote_search():
    print("=" * 60)
    print("远程模式：关键词搜索（需 API 服务运行中）")
    print("=" * 60)

    try:
        with XhsDataClient.remote("http://127.0.0.1:8080") as client:
            health = client.files.health()
            print(f"健康检查: {health}")

            dataset = client.search.load(keyword="旅游")
            print(f"远程加载: {dataset.note_count} 条笔记")
    except Exception as e:
        print(f"远程模式跳过: {e}")
    print()


if __name__ == "__main__":
    try:
        demo_local_search()
        demo_local_creator()
        demo_local_export_api_shape()
        demo_remote_search()
        print("SDK 示例运行完成。")
    except FileNotFoundError as e:
        print(f"错误: {e}")
        print('请先运行爬虫生成 CSV，例如: uv run main.py --platform xhs --type search --keywords "旅游"')
        sys.exit(1)
