# -*- coding: utf-8 -*-
"""MediaCrawler SDK 命令行快捷入口。"""

from __future__ import annotations

import json

import typer

app = typer.Typer(add_completion=False, help="MediaCrawler SDK：keyword_ex / creator_ex 快捷命令")


def _print_summary(result) -> None:
    if hasattr(result, "summary"):
        typer.echo(json.dumps(result.summary(), ensure_ascii=False, indent=2))
        return
    summary = result.get("data", {}).get("summary", {}) if isinstance(result, dict) else {}
    typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))


@app.command("search")
def search_cmd(
    keyword: str,
    platform: str = typer.Option("xhs", "--platform", "-p", help="平台，默认 xhs"),
    max_notes: int = typer.Option(20, "--max-notes", "-n", help="最多爬取笔记数"),
    comments: bool = typer.Option(False, "--comments", "-c", help="是否爬评论"),
) -> None:
    """关键词搜索：等价于 keyword_ex(platform, keyword)"""
    from sdk import keyword_ex

    result = keyword_ex(
        platform,
        keyword,
        max_notes_count=max_notes,
        enable_comments=comments,
    )
    _print_summary(result)


@app.command("creator")
def creator_cmd(
    creator_id: str = typer.Argument(
        ...,
        help="博主 user_id 或主页 URL（URL 请用引号包裹）",
    ),
    platform: str = typer.Option("xhs", "--platform", "-p", help="平台，默认 xhs"),
    max_notes: int = typer.Option(20, "--max-notes", "-n", help="最多爬取笔记数"),
    comments: bool = typer.Option(False, "--comments", "-c", help="是否爬评论"),
) -> None:
    """博主爬取：支持 24 位 user_id 或带 xsec_token 的主页链接"""
    from sdk import creator_ex

    result = creator_ex(
        platform,
        creator_id,
        max_notes_count=max_notes,
        enable_comments=comments,
    )
    _print_summary(result)


if __name__ == "__main__":
    app()
