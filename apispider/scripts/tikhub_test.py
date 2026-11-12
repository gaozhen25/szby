import sys
from pathlib import Path

# Ensure the starx-backend root is on sys.path so `app.*` imports work
# regardless of how this script is invoked.
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


from app.services.tikhub_service import TikHubCrawlService

async def by_keywords():
    service = TikHubCrawlService()
    result =  await service.crawl_by_keyword(
        keywords=["王者荣耀陪玩"],
        platform= "dy",
        max_notes_count = 10,
    )
    print(f"[keyword_result]:{result}")

async def by_creator():
    service = TikHubCrawlService()
    result =  await service.crawl_by_creator(
        creator_url="https://www.douyin.com/user/MS4wLjABAAAALzDqfljfGN0zekn8wkWfPqrgaWINqYc47ZJiJWgZuAi1uaNHxtD1LNocpEvMnJZB?from_tab_name=main&vid=7634902591184440618"
    )
    print(f"[keyword_result]:{result}")

    

if __name__ == "__main__":
    import asyncio 
    # asyncio.run(by_keywords())
    asyncio.run(by_creator())