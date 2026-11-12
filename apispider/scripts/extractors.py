"""调试公开主页 / 创作者采集。

默认走「访客 Playwright」路径：不需要 TikHub Key，也不需要 cookies.json。

用法:
  conda activate starx
  python scripts/extractors.py              # 访客采集（推荐，无 Key）
  python scripts/extractors.py --profile    # 轻量公开页解析
  python scripts/extractors.py --tikhub     # TikHub（需 STARX_TIKHUB_API_KEY）
  python scripts/extractors.py --video      # 单条抖音分享链
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from app.core.config import settings
from app.services.extract_service.extract_service import ExtractService
from app.services.extract_service.guest_creator_crawl import GuestCreatorCrawlService
from app.services.extract_service.profile_service import ProfileExtractService
from app.services.tikhub_service import TikHubCrawlService

XHS_PROFILE = (
    "https://www.xiaohongshu.com/user/profile/5decf4f6000000000100a8b3"
    "?xsec_token=ABr8PsAPjBZJw9LTf1KhPPx9pZ609CuGD21EctM2cYR7w=&xsec_source=pc_note"
)
DY_PROFILE = (
    "https://www.douyin.com/user/"
    "MS4wLjABAAAACwqFzA-WEw2ifTxjsnx8TASTBa_x0tryFJ_SKiv6ZmKTdlV9ALMlal9JjtrEF_c0"
    "?from_tab_name=main"
)


def _print(label: str, payload: object) -> None:
    print(f"\n[{label}]")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _profile_summary(result: dict) -> dict:
    return {
        "name": result.get("name"),
        "accountId": result.get("accountId"),
        "description": result.get("description"),
        "following": result.get("following"),
        "followers": result.get("followers"),
        "liked": result.get("liked"),
        "worksCount": result.get("worksCount"),
        "works": result.get("works"),
        "rawSource": (result.get("raw") or {}).get("source"),
    }


def extra_douyin_video() -> None:
    extractor = ExtractService(timeout=10)
    _print("抖音视频", extractor.extract("https://v.douyin.com/gwKAvZ-TbE8/"))


def extra_profile() -> None:
    service = ProfileExtractService()
    for label, url in (("小红书公开页", XHS_PROFILE), ("抖音公开页", DY_PROFILE)):
        _print(label, _profile_summary(service.extract(url, limit=5)))


def extra_guest() -> None:
    service = GuestCreatorCrawlService(timeout=45)
    for label, url in (("小红书访客采集", XHS_PROFILE), ("抖音访客采集", DY_PROFILE)):
        result = service.crawl_by_creator(url, limit=10)
        _print(label, _profile_summary(result.to_dict()))


async def extra_tikhub_creators() -> None:
    if not (settings.tikhub_api_key or "").strip():
        raise SystemExit(
            "未配置 STARX_TIKHUB_API_KEY。\n"
            "无 Key 请直接运行: python scripts/extractors.py\n"
            "或: python scripts/extractors.py --profile"
        )
    service = TikHubCrawlService()
    for label, url in (("小红书 TikHub", XHS_PROFILE), ("抖音 TikHub", DY_PROFILE)):
        result = await service.crawl_by_creator(
            creator_url=url,
            max_notes_count=5,
            enable_comments=False,
        )
        creators = result.creators or []
        creator = creators[0] if creators else {}
        _print(
            label,
            {
                "platform": result.platform,
                "creator": {
                    "nickname": creator.get("nickname") or creator.get("name"),
                    "description": creator.get("bio")
                    or creator.get("description")
                    or creator.get("signature"),
                    "user_id": creator.get("user_id") or creator.get("sec_user_id"),
                },
                "content_count": result.content_count,
                "contents": [
                    {
                        "content_id": item.get("content_id"),
                        "title": item.get("title") or item.get("desc"),
                        "url": item.get("content_url") or item.get("share_url"),
                    }
                    for item in (result.contents or [])[:5]
                ],
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="调试无 Key 主页/作品采集")
    parser.add_argument("--profile", action="store_true", help="轻量公开页解析")
    parser.add_argument("--tikhub", action="store_true", help="TikHub（需要 API Key）")
    parser.add_argument("--video", action="store_true", help="解析单条抖音分享链")
    args = parser.parse_args()
    if args.video:
        extra_douyin_video()
        return
    if args.profile:
        extra_profile()
        return
    if args.tikhub:
        asyncio.run(extra_tikhub_creators())
        return
    extra_guest()


if __name__ == "__main__":
    main()
