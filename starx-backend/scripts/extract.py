import requests
import sys
from pathlib import Path

# Ensure the starx-backend root is on sys.path so `app.*` imports work
# regardless of how this script is invoked.
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from app.services.extract_service.extract_service import ExtractService
from app.services.extract_service.profile_service import ProfileExtractService

def extra_douyin_video():

    extractor = ExtractService(timeout=10)

    url = "https://v.douyin.com/l8gIKRJpqMw"
    print(f"[抖音]:{extractor.extract(url)}")

def extra_xhs_url():
    extractor = ExtractService(timeout=10)

    url = "https://www.xiaohongshu.com/explore/6a06d3570000000007011d44?xsec_token=YBvSdtDJ8GiCNncQ0HbWlFV7Tgl5B33BESJ1S1BTktNHk%3D&xsec_source=pc_search"
    print(f"[xhs]:{extractor.extract(url)}")

def extra_feigua():

    extractor = ExtractService(timeout=10)
    url = "https://dsp.feigua.cn/bloggeropen/DE50D13CB6A33884?chl=zhitou%2C1713756129"



    print(extractor.extract(url))

def extra_profile():
    service  = ProfileExtractService()
    print(f"[小红书]{service.extract("https://www.xiaohongshu.com/user/profile/5decf4f6000000000100a8b3?xsec_token=ABr8PsAPjBZJw9LTf1KhPPx9pZ609CuGD21EctM2cYR7w=&xsec_source=pc_note")}")
    print(f"[抖音]{service.extract("https://www.douyin.com/user/MS4wLjABAAAACwqFzA-WEw2ifTxjsnx8TASTBa_x0tryFJ_SKiv6ZmKTdlV9ALMlal9JjtrEF_c0?from_tab_name=main")}")
if __name__ == "__main__":
    # extra_feigua()
    # extra_profile()
    extra_xhs_url()
    # extra_douyin_video()