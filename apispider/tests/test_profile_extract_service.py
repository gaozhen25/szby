import json
from urllib.parse import quote

import pytest

from app.services.extract_service.extract_service import UnsupportedPlatformError
from app.services.extract_service.profile_service import ProfileExtractService
from app.services.extract_service.public_browser import RenderedPublicPage
from app.services.extract_service.profiles.base import count_value
from app.services.extract_service.profiles.douyin import DouyinProfileExtractor
from app.services.extract_service.profiles.rednote import RednoteProfileExtractor


def _script(script_id: str, payload: dict) -> str:
    data = quote(json.dumps(payload, ensure_ascii=False))
    return f'<script id="{script_id}">{data}</script>'


def test_count_value_supports_platform_abbreviations():
    assert count_value("97.4万") == 974_000
    assert count_value("5558.3万") == 55_583_000
    assert count_value("10+") == 10
    assert count_value(None) is None


def test_douyin_profile_parser_extracts_metrics_and_first_n_works():
    payload = {
        "loaderData": {
            "user": {
                "nickname": "示例抖音博主",
                "unique_id": "sample-id",
                "sec_uid": "MS4wLjAB-example",
                "signature": "这是简介",
                "following_count": 139,
                "follower_count": 974_000,
                "total_favorited": 55_583_000,
                "aweme_count": 88,
                "avatar_larger": {"url_list": ["https://img.example/avatar.jpg"]},
            },
            "posts": [
                {
                    "aweme_id": str(index),
                    "desc": f"作品 {index}",
                    "create_time": 1_700_000_000 + index,
                    "video": {"cover": {"url_list": [f"https://img.example/{index}.jpg"]}},
                }
                for index in range(3)
            ],
        }
    }
    html = _script("RENDER_DATA", payload)
    extractor = DouyinProfileExtractor(
        "https://www.douyin.com/user/MS4wLjAB-example", limit=2
    )

    result = extractor.parse(html, "https://www.douyin.com/user/MS4wLjAB-example")

    assert result.name == "示例抖音博主"
    assert result.following == 139
    assert result.followers == 974_000
    assert result.liked == 55_583_000
    assert result.works_count == 88
    assert [item.url for item in result.works] == [
        "https://www.douyin.com/video/0",
        "https://www.douyin.com/video/1",
    ]


def test_rednote_profile_parser_preserves_labels_and_xsec_work_links():
    state = {
        "user": {
            "userPageData": {
                "basicInfo": {
                    "nickname": "示例小红书博主",
                    "redId": "sample-red-id",
                    "desc": "小红书简介",
                    "imageb": "https://img.example/avatar.jpg",
                },
                "interactions": [
                    {"type": "follows", "count": "139"},
                    {"type": "fans", "count": "97.4万"},
                    {"type": "interaction", "count": "5558.3万"},
                ],
                "notesCount": 66,
            },
            "notes": [
                [
                    {
                        "noteCard": {
                            "noteId": "note-1",
                            "xsecToken": "token+/=",
                            "displayTitle": "第一条笔记",
                            "cover": {
                                "urlDefault": "https://img.example/note-1.jpg"
                            },
                        }
                    },
                    {
                        "noteCard": {
                            "noteId": "note-2",
                            "displayTitle": "第二条笔记",
                            "cover": {
                                "urlDefault": "https://img.example/note-2.jpg"
                            },
                        }
                    },
                ]
            ],
        }
    }
    html = (
        "<html><body><script>window.__INITIAL_STATE__="
        + json.dumps(state, ensure_ascii=False)
        + ";</script></body></html>"
    )
    extractor = RednoteProfileExtractor(
        "https://www.xiaohongshu.com/user/profile/sample", limit=1
    )

    result = extractor.parse(html, "https://www.xiaohongshu.com/user/profile/sample")

    assert result.name == "示例小红书博主"
    assert result.followers == 974_000
    assert result.metric_labels["liked"] == "5558.3万"
    assert result.works_count == 66
    assert len(result.works) == 1
    assert result.works[0].url.startswith("https://www.xiaohongshu.com/explore/note-1?")
    assert "xsec_token=token%2B%2F%3D" in result.works[0].url


def test_rednote_profile_keeps_works_when_note_id_blank():
    state = {
        "user": {
            "userPageData": {
                "basicInfo": {
                    "nickname": "茶叶盒盒",
                    "redId": "huahuachen_",
                    "desc": "不是卖茶叶的\n🎵茶叶盒盒",
                    "imageb": "https://img.example/avatar.jpg",
                },
                "interactions": [],
            },
            "notes": [
                [
                    {
                        "id": "",
                        "noteCard": {
                            "noteId": "",
                            "xsecToken": "ABtoken",
                            "displayTitle": "置顶笔记",
                            "cover": {
                                "urlDefault": (
                                    "http://sns-webpic-qc.xhscdn.com/cover/"
                                    "1040g2sg31clndrskgc7!nc_n_nwebp_mw_1"
                                )
                            },
                        },
                    }
                ]
            ],
        }
    }
    html = (
        "<html><body><script>window.__INITIAL_STATE__="
        + json.dumps(state, ensure_ascii=False)
        + ";</script></body></html>"
    )
    result = RednoteProfileExtractor(
        "https://www.xiaohongshu.com/user/profile/sample", limit=3
    ).parse(html, "https://www.xiaohongshu.com/user/profile/sample")

    assert result.description.startswith("不是卖茶叶的")
    assert len(result.works) == 1
    assert result.works[0].id == "xsec:ABtoken"
    assert result.works[0].title == "置顶笔记"
    assert result.works[0].cover
    assert result.works[0].url == ""


def test_profile_service_accepts_only_supported_profile_urls():
    service = ProfileExtractService()

    assert (
        service.detect_platform("https://www.douyin.com/user/abc?from_tab_name=main")
        == "douyin"
    )
    assert (
        service.detect_platform("https://www.xiaohongshu.com/user/profile/abc")
        == "rednote"
    )
    with pytest.raises(UnsupportedPlatformError):
        service.detect_platform("https://www.douyin.com/video/123")
    with pytest.raises(UnsupportedPlatformError):
        service.detect_platform("https://notdouyin.com/user/abc")


def test_douyin_profile_public_request_does_not_send_cookie_header():
    payload = {
        "user": {
            "nickname": "无 Cookie 博主",
            "sec_uid": "MS4wLjAB-public",
            "follower_count": 1,
        }
    }

    class Response:
        text = _script("RENDER_DATA", payload)
        url = "https://www.douyin.com/user/MS4wLjAB-public"

        @staticmethod
        def raise_for_status():
            return None

    class Session:
        def get(self, _url, **kwargs):
            assert "Cookie" not in kwargs["headers"]
            return Response()

    result = ProfileExtractService(session=Session()).extract(
        "https://www.douyin.com/user/MS4wLjAB-public"
    )

    assert result["name"] == "无 Cookie 博主"


def test_douyin_profile_uses_anonymous_browser_when_http_returns_challenge():
    rendered_html = """
    <html><body>
      <div data-e2e="user-detail">
        <img alt="小屁屁头像" src="https://img.example/avatar.jpg">
        <div data-e2e="user-info">
          <h1><span>小屁屁</span></h1>
          <div data-e2e="user-info-follow"><div>139</div><div>关注</div></div>
          <div data-e2e="user-info-fans"><div>97.2万</div><div>粉丝</div></div>
          <div data-e2e="user-info-like"><div>5558.3万</div><div>获赞</div></div>
          <p><span>抖音号：73426294572</span><span>IP属地：江苏</span></p>
          <div><span>公开简介</span><span>更多</span></div>
        </div>
        <span data-e2e="user-tab-count">418</span>
        <div data-e2e="user-post-list">
          <a href="https://www.douyin.com/video/100?from=profile">
            <img src="https://img.example/100.jpg">第一条作品
          </a>
          <a href="https://www.douyin.com/video/101">第二条作品</a>
        </div>
      </div>
      <a href="https://www.douyin.com/video/999">页面推荐视频</a>
    </body></html>
    """

    class Response:
        text = "<html><body><script>window.location.reload()</script></body></html>"
        url = "https://www.douyin.com/user/MS4wLjAB-public"

        @staticmethod
        def raise_for_status():
            return None

    class Session:
        @staticmethod
        def get(_url, **_kwargs):
            return Response()

    class Renderer:
        calls = []

        def render(self, url, *, timeout):
            self.calls.append((url, timeout))
            return RenderedPublicPage(rendered_html, url)

    renderer = Renderer()
    result = ProfileExtractService(
        session=Session(), browser_renderer=renderer
    ).extract("https://www.douyin.com/user/MS4wLjAB-public", limit=1)

    assert renderer.calls == [
        ("https://www.douyin.com/user/MS4wLjAB-public", 10)
    ]
    assert result["name"] == "小屁屁"
    assert result["accountId"] == "73426294572"
    assert result["followers"] == 972_000
    assert result["liked"] == 55_583_000
    assert result["worksCount"] == 418
    assert result["description"] == "公开简介"
    assert [item["id"] for item in result["works"]] == ["100"]


def test_douyin_browser_public_api_payloads_override_rounded_dom_metrics():
    rendered_html = """
    <div data-e2e="user-detail">
      <div data-e2e="user-info">
        <h1>页面昵称</h1>
        <div data-e2e="user-info-follow"><span>139</span><span>关注</span></div>
        <div data-e2e="user-info-fans"><span>97.2万</span><span>粉丝</span></div>
        <div data-e2e="user-info-like"><span>5558.3万</span><span>获赞</span></div>
      </div>
      <span data-e2e="user-tab-count">418</span>
      <div data-e2e="user-post-list"></div>
    </div>
    """

    class Response:
        text = "<script>window.location.reload()</script>"
        url = "https://www.douyin.com/user/MS4wLjAB-public"

        @staticmethod
        def raise_for_status():
            return None

    class Session:
        @staticmethod
        def get(_url, **_kwargs):
            return Response()

    class Renderer:
        @staticmethod
        def render(url, *, timeout):  # noqa: ARG004
            return RenderedPublicPage(
                rendered_html,
                url,
                payloads=(
                    {
                        "user": {
                            "nickname": "接口昵称",
                            "unique_id": "exact-id",
                            "following_count": 139,
                            "follower_count": 972_345,
                            "total_favorited": 55_583_210,
                            "aweme_count": 418,
                        }
                    },
                    {
                        "aweme_list": [
                            {"aweme_id": "200", "desc": "接口作品"}
                        ]
                    },
                ),
            )

    result = ProfileExtractService(
        session=Session(), browser_renderer=Renderer()
    ).extract("https://www.douyin.com/user/MS4wLjAB-public", limit=3)

    assert result["name"] == "接口昵称"
    assert result["followers"] == 972_345
    assert result["liked"] == 55_583_210
    assert result["metricLabels"]["followers"] == "972345"
    assert result["works"][0]["url"] == "https://www.douyin.com/video/200"


def test_douyin_partial_public_api_payload_does_not_erase_dom_metrics():
    rendered_html = """
    <div data-e2e="user-detail">
      <img alt="页面昵称头像" src="https://img.example/avatar.jpg">
      <div data-e2e="user-info">
        <h1>页面昵称</h1>
        <div data-e2e="user-info-follow"><span>关注</span><span>139</span></div>
        <div data-e2e="user-info-fans"><span>粉丝</span><span>97.2万</span></div>
        <div data-e2e="user-info-like"><span>获赞</span><span>5558.3万</span></div>
      </div>
      <span data-e2e="user-tab-count">418</span>
      <div data-e2e="user-post-list"></div>
    </div>
    """

    class Response:
        text = "<script>window.location.reload()</script>"
        url = "https://www.douyin.com/user/MS4wLjAB-public"

        @staticmethod
        def raise_for_status():
            return None

    class Session:
        @staticmethod
        def get(_url, **_kwargs):
            return Response()

    class Renderer:
        @staticmethod
        def render(url, *, timeout):  # noqa: ARG004
            return RenderedPublicPage(
                rendered_html,
                url,
                payloads=(
                    {
                        "user": {
                            "nickname": "接口昵称",
                            "unique_id": "exact-id",
                            "following_count": None,
                            "follower_count": None,
                            "total_favorited": None,
                            "aweme_count": 418,
                        }
                    },
                ),
            )

    result = ProfileExtractService(
        session=Session(), browser_renderer=Renderer()
    ).extract("https://www.douyin.com/user/MS4wLjAB-public")

    assert result["name"] == "接口昵称"
    assert result["avatar"] == "https://img.example/avatar.jpg"
    assert result["following"] == 139
    assert result["followers"] == 972_000
    assert result["liked"] == 55_583_000
    assert result["metricLabels"]["followers"] == "97.2万"
