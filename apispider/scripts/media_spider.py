import sys
from pathlib import Path

# Ensure the starx-backend root is on sys.path so `app.*` imports work
# regardless of how this script is invoked.
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


from app.services.tikhub_service import TikHubCrawlService  # noqa: E402


async def main():
    service = TikHubCrawlService()
    result = await service.crawl_by_keyword(
        keywords=["赫哥留学", "高端留学咨询", "顶尖学府留学"],
        platform="dy",
        max_notes_count=5,
    )
    print(result)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
