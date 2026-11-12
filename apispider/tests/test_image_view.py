import json
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.ai_service import default_ai_service


import logging
logging.basicConfig(level=logging.WARNING)

async def run_image_view():
    response = await default_ai_service.image_view(
       prompt="描述以下照片",
       image_url="https://oss.zycx.info/extract/rednote/987efcf6913d4f9b874a8bcd417fd6ca.jpg",
    )
    print("Image view response:", response)
    # print("Image view response json:", json.dumps(response))

if __name__ == "__main__":
    import asyncio
    asyncio.run(run_image_view())
