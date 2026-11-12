import sys
from pathlib import Path

# Ensure the starx-backend root is on sys.path so `app.*` imports work
# regardless of how this script is invoked.
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


from app.services.tikhub_service import TikHubCrawlService  # noqa: E402

# 切换平台: "xhs" | "dy"
PLATFORM = "dy"

CREATOR_URLS = {
    "xhs": "https://www.xiaohongshu.com/user/profile/67505011000000000800be3a?xsec_token=AB1FUGlM59C2TS1OMYqaIkBxW27FMf3u0jpJq7pAek6TE=&xsec_source=pc_note",
    "dy": (
        "https://www.douyin.com/user/MS4wLjABAAAAbgtaK3APZ4mKdXBXbQoozThh9d0wU-G_9V5RBvixwSeNeuA6hFS3FyxFPgw_aVpD?from_tab_name=main&relation=1&vid=7638586784636505378"
    ),
}


async def main():
    service = TikHubCrawlService()
    creator_url = CREATOR_URLS[PLATFORM]
    result = await service.crawl_by_creator(
        creator_url=creator_url,
        max_notes_count=5,
        enable_comments=False,
    )
    print(
        {
            "platform": result.platform,
            "crawl_type": result.crawl_type,
            "creator_url": creator_url,
            "content_count": result.content_count,
            "comment_count": result.comment_count,
            "creator_count": result.creator_count,
            "contents": result.contents,
            "creators": result.creators,
        }
    )


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
