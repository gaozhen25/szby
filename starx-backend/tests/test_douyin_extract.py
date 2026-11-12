from app.services.extract_service.platforms.douyin import douyin_images, play_addr_urls


def _image(name: str) -> dict:
    return {"url_list": [f"https://example.test/{name}.webp"]}


def test_douyin_images_only_returns_primary_aweme_images():
    primary_images = [_image(f"original-{index}") for index in range(4)]
    render_data = {
        "loaderData": {
            "videoInfoRes": {
                "item_list": [
                    {
                        "aweme_id": "7617009389544069222",
                        "desc": "图文作品",
                        "images": primary_images,
                        "image_infos": {
                            "label_large_list": [
                                {
                                    "name": "gear_480p",
                                    "images": [_image(f"480p-{index}") for index in range(4)],
                                },
                                {
                                    "name": "gear_960p",
                                    "images": [_image(f"960p-{index}") for index in range(4)],
                                },
                            ]
                        },
                    }
                ]
            }
        }
    }

    assert douyin_images(render_data, "") == [
        f"https://example.test/original-{index}.webp" for index in range(4)
    ]


def test_douyin_images_keeps_legacy_tree_fallback_without_aweme_card():
    render_data = {
        "legacy_detail": {
            "images": [_image("first"), _image("second")],
        }
    }

    assert douyin_images(render_data, "") == [
        "https://example.test/first.webp",
        "https://example.test/second.webp",
    ]


def test_play_addr_urls_prefers_mediaspider_h264_cdn_url():
    video = {
        "play_addr_h264": {
            "url_list": [
                "https://www.douyin.com/aweme/v1/playwm/?video_id=watermarked",
                "https://v5-dy.example.test/video/tos/cn/no-watermark",
            ]
        },
        "play_addr_256": {
            "url_list": ["https://v5-dy.example.test/video/tos/cn/low-resolution"]
        },
        "play_addr": {
            "url_list": ["https://www.douyin.com/aweme/v1/play/?video_id=fallback"]
        },
    }

    assert play_addr_urls(video) == [
        "https://v5-dy.example.test/video/tos/cn/no-watermark"
    ]


def test_play_addr_urls_uses_last_generic_play_url_without_mp4_suffix():
    video = {
        "play_addr": {
            "url_list": [
                "https://www.douyin.com/aweme/v1/playwm/?video_id=watermarked",
                "https://v5-dy.example.test/video/tos/cn/no-watermark",
            ]
        }
    }

    assert play_addr_urls(video) == [
        "https://v5-dy.example.test/video/tos/cn/no-watermark"
    ]


def test_play_addr_urls_converts_single_share_page_playwm_url():
    video = {
        "play_addr": {
            "url_list": [
                "https://aweme.snssdk.com/aweme/v1/playwm/"
                "?line=0&ratio=720p&video_id=video-1"
            ]
        }
    }

    assert play_addr_urls(video) == [
        "https://aweme.snssdk.com/aweme/v1/play/"
        "?line=0&ratio=720p&video_id=video-1"
    ]
