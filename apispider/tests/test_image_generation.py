import json
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.ai_service import default_ai_service


import logging
logging.basicConfig(level=logging.WARNING)

async def run_image_generation():
    response = await default_ai_service.image_generation(
       prompt="请生成一张未来城市的科幻风格插画",
    )
    print("Image generation response:", response)
    print("Image generation response json:", json.dumps(response))

if __name__ == "__main__":
    import asyncio
    asyncio.run(run_image_generation())
