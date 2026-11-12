import json
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uuid import uuid4

from app.core.config import settings
from app.services.autophone_service import AutophonePublishRequest, default_autophone_service


def _require_autophone_credentials() -> None:
    if settings.autophone_client_id and settings.autophone_client_secret:
        return

    raise SystemExit(
        "Autophone credentials are not configured. Set "
        "STARX_AUTOPHONE_CLIENT_ID and STARX_AUTOPHONE_CLIENT_SECRET in "
        "starx-backend/.env, or export AUTOPHONE_CLIENT_ID and "
        "AUTOPHONE_CLIENT_SECRET before running this manual publish test."
    )


async def run_autophone_publish():
    _require_autophone_credentials()
    # android_id = "a7ab047ed1e6f82d"
    android_id = "10ccb305de4adcc5"
    # video_url = "https://oss.zycx.info/extract/douyin/34a69e82f6564402b472bacb49a447b0.mp4"
    asset_url = "https://oss.zycx.info/starx/generation/acc004f210a/wf_2757c64fdb0340f5a4f1ae0c0d587d82/results/ga_0c462a2795b94132bbb3f54dd724f317.png"
    request_data = {
        "external_id": str(uuid4()),
        "platform": "douyin",
        "android_id": android_id,
        "asset_list": [asset_url],
        "visibility": 1,
        "copy_to_album": True,
        "filename": "test_video.mp4",
        "description": "This is a test video.",
    }

    request = AutophonePublishRequest(**request_data)
    response = default_autophone_service.publish(request)
    print("Autophone publish response:", response)
    print("Autophone publish response json:", json.dumps(response))


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_autophone_publish())
