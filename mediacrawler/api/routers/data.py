# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/api/routers/data.py
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

import os
import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from services.xhs_creator_service import XhsCreatorService
from services.xhs_json_service import XhsJsonService
from services.xhs_search_service import XhsSearchService

from sdk import XhsDataClient

router = APIRouter(prefix="/data", tags=["data"])

# Data directory
DATA_DIR = Path(__file__).parent.parent.parent / "data"


def get_file_info(file_path: Path) -> dict:
    """Get file information"""
    stat = file_path.stat()
    record_count = None

    # Try to get record count
    try:
        if file_path.suffix == ".json":
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    record_count = len(data)
        elif file_path.suffix == ".csv":
            with open(file_path, "r", encoding="utf-8") as f:
                record_count = sum(1 for _ in f) - 1  # Subtract header row
    except Exception:
        pass

    return {
        "name": file_path.name,
        "path": str(file_path.relative_to(DATA_DIR)),
        "size": stat.st_size,
        "modified_at": stat.st_mtime,
        "record_count": record_count,
        "type": file_path.suffix[1:] if file_path.suffix else "unknown"
    }


@router.get("/files")
async def list_data_files(platform: Optional[str] = None, file_type: Optional[str] = None):
    """Get data file list"""
    if not DATA_DIR.exists():
        return {"files": []}

    files = []
    supported_extensions = {".json", ".csv", ".xlsx", ".xls"}

    for root, dirs, filenames in os.walk(DATA_DIR):
        root_path = Path(root)
        for filename in filenames:
            file_path = root_path / filename
            if file_path.suffix.lower() not in supported_extensions:
                continue

            # Platform filter
            if platform:
                rel_path = str(file_path.relative_to(DATA_DIR))
                if platform.lower() not in rel_path.lower():
                    continue

            # Type filter
            if file_type and file_path.suffix[1:].lower() != file_type.lower():
                continue

            try:
                files.append(get_file_info(file_path))
            except Exception:
                continue

    # Sort by modification time (newest first)
    files.sort(key=lambda x: x["modified_at"], reverse=True)

    return {"files": files}


@router.get("/files/{file_path:path}")
async def get_file_content(file_path: str, preview: bool = True, limit: int = 100):
    """Get file content or preview"""
    full_path = DATA_DIR / file_path

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    if not full_path.is_file():
        raise HTTPException(status_code=400, detail="Not a file")

    # Security check: ensure within DATA_DIR
    try:
        full_path.resolve().relative_to(DATA_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    if preview:
        # Return preview data
        try:
            if full_path.suffix == ".json":
                with open(full_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return {"data": data[:limit], "total": len(data)}
                    return {"data": data, "total": 1}
            elif full_path.suffix == ".csv":
                import csv
                with open(full_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    rows = []
                    for i, row in enumerate(reader):
                        if i >= limit:
                            break
                        rows.append(row)
                    # Re-read to get total count
                    f.seek(0)
                    total = sum(1 for _ in f) - 1
                    return {"data": rows, "total": total}
            elif full_path.suffix.lower() in (".xlsx", ".xls"):
                import pandas as pd
                # Read first limit rows
                df = pd.read_excel(full_path, nrows=limit)
                # Get total row count (only read first column to save memory)
                df_count = pd.read_excel(full_path, usecols=[0])
                total = len(df_count)
                # Convert to list of dictionaries, handle NaN values
                rows = df.where(pd.notnull(df), None).to_dict(orient='records')
                return {
                    "data": rows,
                    "total": total,
                    "columns": list(df.columns)
                }
            else:
                raise HTTPException(status_code=400, detail="Unsupported file type for preview")
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON file")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        # Return file download
        return FileResponse(
            path=full_path,
            filename=full_path.name,
            media_type="application/octet-stream"
        )


@router.get("/download/{file_path:path}")
async def download_file(file_path: str):
    """Download file"""
    full_path = DATA_DIR / file_path

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    if not full_path.is_file():
        raise HTTPException(status_code=400, detail="Not a file")

    # Security check
    try:
        full_path.resolve().relative_to(DATA_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(
        path=full_path,
        filename=full_path.name,
        media_type="application/octet-stream"
    )


@router.get("/stats")
async def get_data_stats():
    """Get data statistics"""
    if not DATA_DIR.exists():
        return {"total_files": 0, "total_size": 0, "by_platform": {}, "by_type": {}}

    stats = {
        "total_files": 0,
        "total_size": 0,
        "by_platform": {},
        "by_type": {}
    }

    supported_extensions = {".json", ".csv", ".xlsx", ".xls"}

    for root, dirs, filenames in os.walk(DATA_DIR):
        root_path = Path(root)
        for filename in filenames:
            file_path = root_path / filename
            if file_path.suffix.lower() not in supported_extensions:
                continue

            try:
                stat = file_path.stat()
                stats["total_files"] += 1
                stats["total_size"] += stat.st_size

                # Statistics by type
                file_type = file_path.suffix[1:].lower()
                stats["by_type"][file_type] = stats["by_type"].get(file_type, 0) + 1

                # Statistics by platform (inferred from path)
                rel_path = str(file_path.relative_to(DATA_DIR))
                for platform in ["xhs", "dy", "ks", "bili", "wb", "tieba", "zhihu"]:
                    if platform in rel_path.lower():
                        stats["by_platform"][platform] = stats["by_platform"].get(platform, 0) + 1
                        break
            except Exception:
                continue

    return stats


@router.get("/creator-export")
async def get_creator_export(
    file_path: Optional[str] = None,
    nickname: Optional[str] = None,
    platform: str = "xhs",
):
    """
    将博主合并 CSV 解析为结构化 JSON，供后端调用。

    - file_path: 相对 data/ 的路径，如 xhs/csv/Charon💕_2026-07-07.csv
    - nickname: 按博主名匹配最新文件（与 file_path 二选一）
    """
    client = XhsDataClient.local(data_dir=DATA_DIR / platform / "csv", data_root=DATA_DIR)
    try:
        if file_path:
            full_path = DATA_DIR / file_path
            if not full_path.exists():
                raise HTTPException(status_code=404, detail="File not found")
            try:
                full_path.resolve().relative_to(DATA_DIR.resolve())
            except ValueError:
                raise HTTPException(status_code=403, detail="Access denied")
            dataset = client.creator.load(file_path=file_path)
        else:
            dataset = client.creator.load(nickname=nickname)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return dataset.to_dict()


@router.get("/creator-export/summary")
async def get_creator_export_summary(
    nickname: Optional[str] = None,
    platform: str = "xhs",
):
    """返回博主数据摘要（昵称、粉丝数、笔记数）。"""
    client = XhsDataClient.local(data_dir=DATA_DIR / platform / "csv", data_root=DATA_DIR)
    try:
        return client.creator.summary(nickname=nickname)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/search-export")
async def get_search_export(
    file_path: Optional[str] = None,
    keyword: Optional[str] = None,
    platform: str = "xhs",
    with_comments: bool = False,
):
    """
    将关键词搜索 CSV 解析为结构化 JSON，供后端调用。

    - file_path: 相对 data/ 的路径，如 xhs/csv/search_contents_2026-07-06.csv
    - keyword: 只返回该关键词的笔记（与 file_path 二选一，默认取最新文件）
    """
    client = XhsDataClient.local(data_dir=DATA_DIR / platform / "csv", data_root=DATA_DIR)
    try:
        if file_path:
            full_path = DATA_DIR / file_path
            if not full_path.exists():
                raise HTTPException(status_code=404, detail="File not found")
            try:
                full_path.resolve().relative_to(DATA_DIR.resolve())
            except ValueError:
                raise HTTPException(status_code=403, detail="Access denied")
        return client.search.export(
            keyword=keyword,
            file_path=file_path,
            with_comments=with_comments,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search-export/summary")
async def get_search_export_summary(
    keyword: Optional[str] = None,
    platform: str = "xhs",
):
    """返回关键词搜索数据摘要。"""
    client = XhsDataClient.local(data_dir=DATA_DIR / platform / "csv", data_root=DATA_DIR)
    try:
        return client.search.summary(keyword=keyword)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/search-json")
async def get_search_json(
    keyword: str,
    platform: str = "xhs",
    with_comments: bool = True,
):
    """从实时爬取 JSON 加载关键词搜索数据（供 ``XhsBackendClient.remote``）。"""
    json_service = XhsJsonService(json_dir=DATA_DIR / platform / "json")
    search_service = XhsSearchService()
    try:
        dataset = json_service.load_search_by_keyword(keyword, with_comments=with_comments)
        return search_service.to_api_response(dataset)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/creator-json")
async def get_creator_json(
    nickname: str,
    platform: str = "xhs",
):
    """从实时爬取 JSON 加载博主数据（供 ``XhsBackendClient.remote``）。"""
    json_service = XhsJsonService(json_dir=DATA_DIR / platform / "json")
    creator_service = XhsCreatorService()
    try:
        dataset = json_service.load_creator_by_nickname(nickname)
        return creator_service.to_api_response(dataset)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
