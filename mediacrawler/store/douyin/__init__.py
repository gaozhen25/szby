# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/store/douyin/__init__.py
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

# -*- coding: utf-8 -*-
# @Author  : relakkes@gmail.com
# @Time    : 2024/1/14 18:46
# @Desc    :
import pathlib
from typing import Dict, List, Optional

import config
from tools import utils
from tools.async_file_writer import AsyncFileWriter
from var import source_keyword_var
from ._store_impl import *
from .douyin_store_media import *


class DouyinStoreFactory:
    STORES = {
        "csv": DouyinCsvStoreImplement,
        "db": DouyinDbStoreImplement,
        "postgres": DouyinDbStoreImplement,
        "json": DouyinJsonStoreImplement,
        "jsonl": DouyinJsonlStoreImplement,
        "sqlite": DouyinSqliteStoreImplement,
        "mongodb": DouyinMongoStoreImplement,
        "excel": DouyinExcelStoreImplement,
    }

    @staticmethod
    def create_store() -> AbstractStore:
        store_class = DouyinStoreFactory.STORES.get(config.SAVE_DATA_OPTION)
        if not store_class:
            raise ValueError("[DouyinStoreFactory.create_store] Invalid save option only supported csv or db or json or sqlite or mongodb or excel ...")
        return store_class()


def _extract_note_image_list(aweme_detail: Dict) -> List[str]:
    """
    Extract note image list

    Args:
        aweme_detail (Dict): Douyin content details

    Returns:
        List[str]: Note image list
    """
    images_res: List[str] = []
    images: List[Dict] = aweme_detail.get("images", [])

    if not images:
        return []

    for image in images:
        image_url_list = image.get("url_list", [])  # download_url_list has watermarked images, url_list has non-watermarked images
        if image_url_list:
            images_res.append(image_url_list[-1])

    return images_res


def _extract_comment_image_list(comment_item: Dict) -> List[str]:
    """
    Extract comment image list

    Args:
        comment_item (Dict): Douyin comment

    Returns:
        List[str]: Comment image list
    """
    images_res: List[str] = []
    image_list: List[Dict] = comment_item.get("image_list", [])

    if not image_list:
        return []

    for image in image_list:
        image_url_list = image.get("origin_url", {}).get("url_list", [])
        if image_url_list and len(image_url_list) > 1:
            images_res.append(image_url_list[1])

    return images_res


def _extract_content_cover_url(aweme_detail: Dict) -> str:
    """
    Extract video cover URL

    Args:
        aweme_detail (Dict): Douyin content details

    Returns:
        str: Video cover URL
    """
    res_cover_url = ""

    video_item = aweme_detail.get("video", {})
    raw_cover_url_list = (video_item.get("raw_cover", {}) or video_item.get("origin_cover", {})).get("url_list", [])
    if raw_cover_url_list and len(raw_cover_url_list) > 1:
        res_cover_url = raw_cover_url_list[1]

    return res_cover_url


def _extract_video_download_url(aweme_detail: Dict) -> str:
    """
    Extract video download URL

    Args:
        aweme_detail (Dict): Douyin video

    Returns:
        str: Video download URL
    """
    video_item = aweme_detail.get("video", {})
    url_h264_list = video_item.get("play_addr_h264", {}).get("url_list", [])
    url_256_list = video_item.get("play_addr_256", {}).get("url_list", [])
    url_list = video_item.get("play_addr", {}).get("url_list", [])
    actual_url_list = url_h264_list or url_256_list or url_list
    if not actual_url_list or len(actual_url_list) < 2:
        return ""
    return actual_url_list[-1]


def _extract_music_download_url(aweme_detail: Dict) -> str:
    """
    Extract music download URL

    Args:
        aweme_detail (Dict): Douyin video

    Returns:
        str: Music download URL
    """
    music_item = aweme_detail.get("music", {})
    play_url = music_item.get("play_url", {})
    music_url = play_url.get("uri", "")
    return music_url


async def update_douyin_aweme(aweme_item: Dict):
    aweme_id = aweme_item.get("aweme_id")
    user_info = aweme_item.get("author", {})
    interact_info = aweme_item.get("statistics", {})
    save_content_item = {
        "aweme_id": aweme_id,
        "aweme_type": str(aweme_item.get("aweme_type")),
        "title": aweme_item.get("desc", ""),
        "desc": aweme_item.get("desc", ""),
        "create_time": aweme_item.get("create_time"),
        "creator_hash": str(user_info.get("uid") or ""),
        "nickname": user_info.get("nickname") or "",
        "liked_count": str(interact_info.get("digg_count")),
        "collected_count": str(interact_info.get("collect_count")),
        "comment_count": str(interact_info.get("comment_count")),
        "share_count": str(interact_info.get("share_count")),
        "last_modify_ts": utils.get_current_timestamp(),
        "aweme_url": f"https://www.douyin.com/video/{aweme_id}",
        "cover_url": _extract_content_cover_url(aweme_item),
        "video_download_url": _extract_video_download_url(aweme_item),
        "music_download_url": _extract_music_download_url(aweme_item),
        "note_download_url": ",".join(_extract_note_image_list(aweme_item)),
        "source_keyword": source_keyword_var.get(),
    }
    utils.logger.info(f"[store.douyin.update_douyin_aweme] douyin aweme id:{aweme_id}, title:{save_content_item.get('title')}")
    await DouyinStoreFactory.create_store().store_content(content_item=save_content_item)


async def batch_update_dy_aweme_comments(aweme_id: str, comments: List[Dict]):
    if not comments:
        return
    for comment_item in comments:
        await update_dy_aweme_comment(aweme_id, comment_item)


async def update_dy_aweme_comment(aweme_id: str, comment_item: Dict):
    comment_aweme_id = comment_item.get("aweme_id")
    if aweme_id != comment_aweme_id:
        utils.logger.error(f"[store.douyin.update_dy_aweme_comment] comment_aweme_id: {comment_aweme_id} != aweme_id: {aweme_id}")
        return
    user_info = comment_item.get("user", {})
    comment_id = comment_item.get("cid")
    parent_comment_id = comment_item.get("reply_id", "0")
    save_comment_item = {
        "comment_id": comment_id,
        "create_time": comment_item.get("create_time"),
        "aweme_id": aweme_id,
        "content": comment_item.get("text"),
        "creator_hash": str(user_info.get("uid") or ""),
        "nickname": user_info.get("nickname") or "",
        "sub_comment_count": str(comment_item.get("reply_comment_total", 0)),
        "like_count": (comment_item.get("digg_count") if comment_item.get("digg_count") else 0),
        "last_modify_ts": utils.get_current_timestamp(),
        "parent_comment_id": parent_comment_id,
        "pictures": ",".join(_extract_comment_image_list(comment_item)),
    }
    utils.logger.info(f"[store.douyin.update_dy_aweme_comment] douyin aweme comment: {comment_id}, content: {save_comment_item.get('content')}")

    await DouyinStoreFactory.create_store().store_comment(comment_item=save_comment_item)


def _extract_creator_avatar_url(user_info: Dict) -> str:
    for key in ("avatar_300x300", "avatar_medium", "avatar_168x168", "avatar_thumb"):
        avatar_info = user_info.get(key) or {}
        url_list = avatar_info.get("url_list") or []
        if url_list:
            return url_list[-1]
    avatar_uri = (user_info.get("avatar_300x300") or {}).get("uri")
    if avatar_uri:
        return f"https://p3-pc.douyinpic.com/img/{avatar_uri}~c5_300x300.jpeg?from=2956013662"
    return ""


async def save_creator(user_id: str, creator: Dict):
    """
    Save Douyin creator profile (nickname, bio, fans, etc.).
    """
    if not creator:
        return

    user_info = creator.get("user", {}) or {}
    gender_map = {0: "Unknown", 1: "Male", 2: "Female"}
    local_db_item = {
        "user_id": user_id,
        "nickname": user_info.get("nickname") or "",
        "gender": gender_map.get(user_info.get("gender"), "Unknown"),
        "avatar": _extract_creator_avatar_url(user_info),
        "desc": user_info.get("signature") or "",
        "ip_location": user_info.get("ip_location") or "",
        "follows": str(user_info.get("following_count") or 0),
        "fans": str(user_info.get("max_follower_count") or user_info.get("follower_count") or 0),
        "interaction": str(user_info.get("total_favorited") or 0),
        "videos_count": str(user_info.get("aweme_count") or 0),
        "last_modify_ts": utils.get_current_timestamp(),
    }
    utils.logger.info(f"[store.douyin.save_creator] creator:{local_db_item}")
    await DouyinStoreFactory.create_store().store_creator(local_db_item)


async def save_search_hot_board(items: List[Dict], meta: Optional[Dict] = None) -> str:
    """
    保存抖音热点宝搜索热点总榜。

    输出：
    - ``data/dyhot/json/搜索热点总榜_{日期}.json``
    - ``data/dyhot/json/搜索热点总榜_{日期}_趋势.html``（按日搜索量折线图）
    """
    from tools.hotspot_trend_chart import enrich_items_with_series, write_hotspot_trend_chart

    meta = meta or {}
    enrich_items_with_series(items)
    hotspot_dir = getattr(config, "DY_HOTSPOT_DATA_DIR", "dyhot") or "dyhot"
    writer = AsyncFileWriter(platform=hotspot_dir, crawler_type="hotspot")
    file_path = writer.get_hotspot_board_json_path("搜索热点总榜")
    chart_path = file_path[:-5] + "_趋势.html" if file_path.endswith(".json") else file_path + "_趋势.html"
    chart_meta = {
        "board_name": "搜索热点总榜",
        "sub_type": meta.get("sub_type"),
        "date_window": meta.get("date_window"),
        "total_count": meta.get("total_count"),
        "fetched_count": meta.get("fetched_count", len(items)),
        "chart_file": chart_path,
    }
    payload = {
        "code": 0,
        "message": "ok",
        "data": {
            "board_name": "搜索热点总榜",
            "sub_type": meta.get("sub_type"),
            "date_window": meta.get("date_window"),
            "total_count": meta.get("total_count"),
            "fetched_count": meta.get("fetched_count", len(items)),
            "items": items,
            "summary": dict(chart_meta),
        },
    }

    file_path = await writer.write_hotspot_board_json("搜索热点总榜", payload)
    chart_path = await write_hotspot_trend_chart(file_path, items, meta=chart_meta)

    if config.SAVE_DATA_OPTION == "csv":
        csv_path = file_path.replace("/json/", "/csv/").replace(".json", ".csv")
        pathlib.Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
        if pathlib.Path(csv_path).exists():
            pathlib.Path(csv_path).unlink()
        fields = [
            "rank",
            "key_word",
            "search_score",
            "sub_type",
            "date_window",
            "last_modify_ts",
        ]
        for item in items:
            await writer.write_to_custom_csv(csv_path, item, fields, unique_field="rank")

    utils.logger.info(
        f"[store.douyin.save_search_hot_board] saved {len(items)} -> {file_path}; chart -> {chart_path}"
    )
    return file_path


async def update_dy_aweme_image(aweme_id, pic_content, extension_file_name):
    """
    Update Douyin note image
    Args:
        aweme_id:
        pic_content:
        extension_file_name:

    Returns:

    """

    await DouYinImage().store_image({"aweme_id": aweme_id, "pic_content": pic_content, "extension_file_name": extension_file_name})


async def update_dy_aweme_video(aweme_id, video_content, extension_file_name):
    """
    Update Douyin short video
    Args:
        aweme_id:
        video_content:
        extension_file_name:

    Returns:

    """

    await DouYinVideo().store_video({"aweme_id": aweme_id, "video_content": video_content, "extension_file_name": extension_file_name})
