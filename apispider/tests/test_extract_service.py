import requests
from bs4 import BeautifulSoup

from app.services.extract_service.douyin_profile_resolver import (
    canonical_douyin_profile_url,
    profile_resolution_from_search,
)
from app.services.extract_service.extract_service import ExtractService
from app.services.mediaspider.models import CrawlResult
from app.services.extract_service.platforms.feigua import Feigua
from app.services.extract_service.platforms.rednote import Rednote
from app.services.extract_service.reference_service import (
    ExtractReferenceService,
    extract_first_url,
)


class FakeExtractor:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload

    def extract(self, url: str) -> dict:
        return self.payload or {
            "platform": "douyin",
            "url": url,
            "resolved_url": "https://www.douyin.com/video/123",
            "type": "mixed",
            "title": "失败者联盟",
            "description": "正文内容",
            "images": ["https://source.example.test/cover.webp"],
            "videos": ["https://source.example.test/video.mp4"],
            "cover": "https://source.example.test/cover.webp",
            "raw": {},
        }


class FakeStorage:
    def __init__(self):
        self.uploads = []

    def put_bytes(self, key, data, content_type):
        self.uploads.append((key, data, content_type))
        return f"https://oss.example.test/{key}"


class FakeResponse:
    def __init__(self, content: bytes, content_type: str, headers: dict[str, str] | None = None):
        self.content = content
        self.headers = {"Content-Type": content_type, **(headers or {})}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=1024 * 1024):  # noqa: ARG002
        yield self.content


class FakeSession:
    def __init__(self):
        self.requests = []

    def get(self, url, timeout=None, headers=None, stream=None):  # noqa: ARG002
        self.requests.append(url)
        if url.endswith(".mp4"):
            return FakeResponse(b"video-bytes", "video/mp4")
        return FakeResponse(b"image-bytes", "image/webp")


class TimeoutVideoSession(FakeSession):
    def get(self, url, timeout=None, headers=None, stream=None):  # noqa: ARG002
        if url.endswith(".mp4"):
            raise requests.ReadTimeout("video download timed out")
        return super().get(url, timeout=timeout, headers=headers, stream=stream)


class QueueMediaSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)

    def get(self, url, timeout=None, headers=None, stream=None):  # noqa: ARG002
        return self.responses.pop(0)


def test_extract_service_imports_platform_extractors():
    service = ExtractService()

    assert service.detect_platform("https://v.douyin.com/xdSvtgg4xpo/") == "douyin"
    assert service.detect_platform("https://dsp.feigua.cn/bloggeropen/ABC") == "feigua"


def test_feigua_extracts_profile_metrics_and_douyin_qr_payload():
    html = """
    <html><head><title>测试播主-飞瓜数据</title></head><body>
      <div class="owner-info">
        <div class="avatar"><img src="https://img.example.test/avatar.webp"></div>
        <div class="info">
          <div class="nickname">测试播主
            <a><div data-qrcodesrc="https://www.iesdouyin.com/share/user/123456"></div>查看抖音主页</a>
          </div>
          <ul><li>抖音号：<span>douyin-test</span></li></ul>
        </div>
        <div class="intro">简介：<span>这是账号简介</span></div>
      </div>
      <div class="owner-data">
        <div class="row">
          <div>粉丝数 <span>308.1w</span></div>
          <div>作品数 <span>798</span></div>
          <div>飞瓜指数 <span>941.7</span></div>
        </div>
        <div class="row">
          <div>昨日排名打败 <span>97.32%的播主</span></div>
          <div>近一周排名打败 <span>93.10%的播主</span></div>
        </div>
        <div class="row">
          <div>总点赞 <span>9085.0w</span></div>
          <div>平均点赞 <span>11.4w</span></div>
        </div>
        <div class="row">
          <div>集均评论 <i title="说明"></i><br><span>5423</span></div>
          <div>集均分享 <span>3922</span></div>
        </div>
      </div>
      <div id="js-over-view-filter">
        <button data-value="近7天">近7天</button>
        <button data-value="30天">30天</button>
        <button data-value="90天">90天</button>
      </div>
      <div id="js-over-view-section">
        <div class="js-blogger-overview"><div><h5>最新作品数</h5><p>9</p></div><div><h5>粉丝增量</h5><p>2134</p></div></div>
        <div class="js-blogger-overview"><div><h5>新增点赞</h5><p>37.7w</p></div></div>
        <div class="js-blogger-overview"><div><h5>新增直播</h5><p>--</p></div></div>
      </div>
    </body></html>
    """

    result = Feigua("https://dsp.feigua.cn/bloggeropen/ABC").parse(
        html,
        BeautifulSoup(html, "html.parser"),
        "https://dsp.feigua.cn/bloggeropen/ABC",
    )

    assert result.content_type == "profile"
    assert result.title == "测试播主"
    assert result.description == "这是账号简介"
    assert result.images == ["https://img.example.test/avatar.webp"]
    assert result.raw["profile"] == {
        "nickname": "测试播主",
        "douyin_id": "douyin-test",
        "biography": "这是账号简介",
        "avatar_url": "https://img.example.test/avatar.webp",
        "douyin_share_url": "https://www.iesdouyin.com/share/user/123456",
        "douyin_profile_url": None,
    }
    assert result.raw["metrics"] == {
        "followers_count": 3_081_000,
        "works_count": 798,
        "feigua_index": 941.7,
        "yesterday_rank_beaten_percent": 97.32,
        "week_rank_beaten_percent": 93.1,
        "total_likes": 90_850_000,
        "average_likes": 114_000,
        "average_comments": 5423,
        "average_shares": 3922,
    }
    assert result.raw["metric_displays"]["week_rank_beaten_percent"] == "93.10%的播主"
    assert result.raw["overview"]["7d"] == {"latest_works": 9, "followers_change": 2134}
    assert result.raw["overview"]["30d"] == {"likes_change": 377_000}
    assert result.raw["overview"]["90d"] == {"live_streams_change": None}
    assert result.raw["qr"] == {
        "payload": "https://www.iesdouyin.com/share/user/123456",
        "source": "data-qrcodesrc",
    }


def test_feigua_ignores_non_douyin_qr_payloads():
    html = '<div data-qrcodesrc="https://notdouyin.com/share/user/123456"></div>'

    result = Feigua("https://dsp.feigua.cn/bloggeropen/ABC").parse(
        html,
        BeautifulSoup(html, "html.parser"),
        "https://dsp.feigua.cn/bloggeropen/ABC",
    )

    assert result.raw["profile"]["douyin_profile_url"] is None


def test_douyin_profile_resolution_matches_feigua_nickname():
    expected_url = (
        "https://www.douyin.com/user/"
        "MS4wLjABAAAA0BtoecGNUNWw-bgXisgD0PdYDIRlAHFuqDqmIKoIVhc"
    )
    result = CrawlResult(
        platform="dy",
        crawl_type="search",
        contents=[
            {"display_name": "其他播主", "profile_url": "https://www.douyin.com/user/MS4wLjABAAAA_other"},
            {"display_name": "山海/全网no.1工作室", "profile_url": f"{expected_url}?from_tab_name=main"},
        ],
    )

    resolution = profile_resolution_from_search(
        result,
        expected_nickname="山海/全网no.1工作室",
    )

    assert resolution == {
        "status": "resolved",
        "method": "douyin_id_search",
        "profile_url": expected_url,
        "reason": None,
    }


def test_canonical_douyin_profile_url_rejects_legacy_uid_and_untrusted_host():
    assert canonical_douyin_profile_url("https://www.iesdouyin.com/share/user/106543846290") is None
    assert canonical_douyin_profile_url("https://notdouyin.com/user/MS4wLjABAAAA_fake") is None


def test_feigua_extract_enriches_profile_with_resolved_douyin_url(monkeypatch):
    html = """
    <div class="owner-info">
      <div class="nickname">测试播主</div>
      <div class="info"><li>抖音号：<span>douyin-test</span></li></div>
      <div data-qrcodesrc="https://www.iesdouyin.com/share/user/123456"></div>
    </div>
    """
    expected_url = "https://www.douyin.com/user/MS4wLjABAAAA_test"
    calls = []
    extractor = Feigua(
        "https://dsp.feigua.cn/bloggeropen/ABC",
        profile_resolver=lambda douyin_id, nickname: (
            calls.append((douyin_id, nickname))
            or {
                "status": "resolved",
                "method": "douyin_id_search",
                "profile_url": expected_url,
                "reason": None,
            }
        ),
    )
    response = type(
        "Response",
        (),
        {
            "text": html,
            "url": "https://dsp.feigua.cn/bloggeropen/ABC",
        },
    )()
    monkeypatch.setattr(extractor, "fetch", lambda: response)

    result = extractor.extract()

    assert calls == [("douyin-test", "测试播主")]
    assert result.raw["profile"]["douyin_profile_url"] == expected_url
    assert result.raw["douyin_profile_resolution"]["status"] == "resolved"


def test_rednote_title_uses_note_card_not_footer_links():
    html = """
    <html><head><title>你们最满意的身材照是什么呀？ - 小红书</title>
    <meta property="og:title" content="你们最满意的身材照是什么呀？ - 小红书" />
    <script>window.__INITIAL_STATE__={
      "global":{"footer":[{"title":"小红书_沪ICP备","link":"/"}]},
      "note":{"noteDetailMap":{"abc":{"note":{
        "noteId":"6a46560300000000220140e6",
        "title":"你们最满意的身材照是什么呀？",
        "desc":"#想穿漂亮衣服[话题]#",
        "imageList":[{"urlDefault":"https://sns-img.example.test/a.jpg"}],
        "type":"normal"
      }}}}
    }</script></head><body></body></html>
    """
    result = Rednote("https://www.xiaohongshu.com/explore/abc").parse(
        html,
        BeautifulSoup(html, "html.parser"),
        "https://www.xiaohongshu.com/explore/abc",
    )

    assert result.title == "你们最满意的身材照是什么呀？"
    assert result.description == "#想穿漂亮衣服[话题]#"


def test_extract_first_url_from_complex_share_text():
    text = "8.25 复制打开抖音，看看【GBD的图文作品】失败者联盟。https://v.douyin.com/xdSvtgg4xpo/ ATl:/ r@e.oq"

    assert extract_first_url(text) == "https://v.douyin.com/xdSvtgg4xpo/"


def test_extract_reference_returns_external_media_without_download_or_upload():
    storage = FakeStorage()
    media_session = FakeSession()
    service = ExtractReferenceService(
        extractor=FakeExtractor(),
        storage=storage,
        media_session=media_session,
    )

    result = service.extract_from_text("看看 https://v.douyin.com/xdSvtgg4xpo/ ATl:/")

    assert result["title"] == "失败者联盟"
    assert result["images"] == [
        {
            "sourceUrl": "https://source.example.test/cover.webp",
            "url": "https://source.example.test/cover.webp",
            "contentType": "",
            "kind": "image",
            "storageStatus": "external",
        }
    ]
    assert result["videos"][0]["url"] == "https://source.example.test/video.mp4"
    assert media_session.requests == []
    assert storage.uploads == []


def test_extract_reference_does_not_download_media_during_parsing():
    storage = FakeStorage()
    service = ExtractReferenceService(
        extractor=FakeExtractor(),
        storage=storage,
        media_session=TimeoutVideoSession(),
    )

    result = service.extract_from_text("看看 https://v.douyin.com/xdSvtgg4xpo/ ATl:/")

    assert result["images"][0]["url"] == "https://source.example.test/cover.webp"
    assert result["videos"][0]["url"] == "https://source.example.test/video.mp4"
    assert storage.uploads == []


def test_extract_reference_defers_media_size_validation_until_persistence(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "max_extract_media_bytes", 4)
    storage = FakeStorage()
    service = ExtractReferenceService(
        extractor=FakeExtractor(
            {
                "platform": "rednote",
                "url": "https://example.test/post",
                "resolved_url": "https://example.test/post",
                "type": "image",
                "title": "",
                "description": "",
                "images": ["https://example.test/a.png"],
                "videos": [],
                "raw": {},
            }
        ),
        storage=storage,
        media_session=QueueMediaSession([FakeResponse(b"12345", "image/png", headers={"Content-Length": "5"})]),
    )

    result = service.extract_from_text("看看 https://example.test/post")

    assert result["images"][0]["url"] == "https://example.test/a.png"
    assert storage.uploads == []


def test_extract_reference_limits_media_item_count(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "max_extract_media_items", 1)
    storage = FakeStorage()
    service = ExtractReferenceService(
        extractor=FakeExtractor(
            {
                "platform": "rednote",
                "url": "https://example.test/post",
                "resolved_url": "https://example.test/post",
                "type": "image",
                "title": "",
                "description": "",
                "images": ["https://example.test/a.png", "https://example.test/b.png"],
                "videos": [],
                "raw": {},
            }
        ),
        storage=storage,
        media_session=QueueMediaSession([
            FakeResponse(b"1", "image/png"),
            FakeResponse(b"2", "image/png"),
        ]),
    )

    result = service.extract_from_text("看看 https://example.test/post")

    assert len(result["images"]) == 1
    assert storage.uploads == []
