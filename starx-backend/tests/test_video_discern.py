import json
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.ai_service import default_ai_service


import logging
logging.basicConfig(level=logging.WARNING)

async def run_video_view():
    # video_url = "https://oss.zycx.info/extract/douyin/821ef7bebb0d4befbb44a641d441178b.mp4"
    video_url = "https://oss.zycx.info/extract/douyin/4c17a9c913704d58a6b84422076f1823.mp4"
    response = await default_ai_service.video_view(
        user_prompt="请分析视频内容",
        system_prompt="你是一个视频解析助手。请根据用户提供的视频链接，分析视频内容并返回详细描述。",
        video_url=video_url,
    )
    print("Video view response:", response)
    print("Video view response json:", json.dumps(response))
    
if __name__ == "__main__":
    import asyncio
    asyncio.run(run_video_view())
