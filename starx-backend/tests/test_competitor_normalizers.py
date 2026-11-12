from app.services.competitor_monitoring.normalizers import (
    metric_delta,
    normalize_account,
    normalize_account_videos,
    normalize_video,
)
from app.services.mediaspider.http_platforms.xhs.normalize import normalize_note_item


def test_metric_delta_ignores_missing_values_and_keeps_negative_changes():
    assert metric_delta(
        {"likes": 90, "comments": None, "shares": 8},
        {"likes": 100, "comments": 4, "shares": None},
    ) == {"likes": -10}


def test_normalize_douyin_video_uses_only_public_whitelisted_fields():
    normalized = normalize_video(
        "dy",
        {
            "aweme_id": "123",
            "title": "真实标题",
            "desc": "真实描述",
            "display_name": "作者",
            "profile_url": "https://www.douyin.com/user/author",
            "liked_count": 20,
            "comment_count": 3,
            "share_count": 2,
            "collected_count": 4,
            "cookie": "must-not-leak",
        },
    )

    assert normalized.platform_content_id == "123"
    assert normalized.metrics == {
        "likes": 20,
        "comments": 3,
        "shares": 2,
        "plays": None,
        "collects": 4,
    }
    assert "cookie" not in normalized.model_dump_json()


def test_normalize_account_maps_safe_creator_counts_without_guessing_missing_values():
    normalized = normalize_account(
        "xhs",
        {
            "display_name": "真实账号",
            "profile_url": "https://www.xiaohongshu.com/user/profile/a",
            "avatar": "https://cdn.example.test/avatar.jpg",
            "fans_count": "1200",
            "works_count": 30,
            "liked_count": None,
            "headers": {"Cookie": "must-not-leak"},
        },
    )

    assert normalized.name == "真实账号"
    assert normalized.avatar_url == "https://cdn.example.test/avatar.jpg"
    assert normalized.metrics == {
        "followers": 1200,
        "following": None,
        "works": 30,
        "liked": None,
    }
    assert "must-not-leak" not in normalized.model_dump_json()


def test_normalize_account_videos_keeps_first_ten_public_items_and_links():
    videos = normalize_account_videos(
        "dy",
        [
            {
                "aweme_id": str(index),
                "title": f"视频 {index}",
                "aweme_url": f"https://www.douyin.com/video/{index}",
                "cover_url": f"https://cdn.example.test/{index}.jpg",
                "create_time": 1_700_000_000 + index,
                "liked_count": index,
                "comment_count": index + 1,
                "cookie": "must-not-leak",
            }
            for index in range(12)
        ],
    )

    assert len(videos) == 10
    assert videos[0].platform_content_id == "0"
    assert videos[0].content_url == "https://www.douyin.com/video/0"
    assert videos[0].cover_url == "https://cdn.example.test/0.jpg"
    assert videos[0].metrics["comments"] == 1
    assert "must-not-leak" not in videos[0].model_dump_json()


def test_xiaohongshu_note_cover_upgrades_trusted_cdn_http_url():
    normalized = normalize_note_item(
        {
            "note_id": "note-1",
            "cover": "http://sns-webpic-qc.xhscdn.com/cover.webp",
            "user": {
                "user_id": "public-user",
                "images": "http://sns-avatar-qc.xhscdn.com/avatar.webp",
            },
        }
    )

    assert normalized is not None
    assert normalized["cover_url"] == (
        "https://sns-webpic-qc.xhscdn.com/cover.webp"
    )
    assert normalized["avatar"] == (
        "https://sns-avatar-qc.xhscdn.com/avatar.webp"
    )


def test_xiaohongshu_note_keeps_mediaspider_comment_and_share_aliases():
    normalized = normalize_note_item(
        {
            "note_id": "note-metrics",
            "liked_count": "1.2万",
            "collected_count": "80",
            "comments_count": "32",
            "shared_count": 7,
        }
    )

    assert normalized is not None
    assert normalized["liked_count"] == "1.2万"
    assert normalized["collected_count"] == "80"
    assert normalized["comment_count"] == "32"
    assert normalized["share_count"] == 7
