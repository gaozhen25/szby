import asyncio
import sys
from pathlib import Path

# Ensure the starx-backend root is on sys.path so `app.*` imports work
# regardless of how this script is invoked.
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from app.services.online_search.models import OnlineSearchRequest
from app.services.online_search.service import default_online_search_service


async def main() -> None:
    req = OnlineSearchRequest(
        query="推荐几个抖音上真实存在的擦边博主 只用返回主链接",
        needSummary=False,
    )
    res = await default_online_search_service.search(req)
    print(res)


if __name__ == "__main__":
    asyncio.run(main())
