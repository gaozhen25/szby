from app.services.competitor_monitoring.normalizers import normalize_account
from app.services.mediaspider.http_platforms.douyin.normalize import (
    normalize_creator as normalize_douyin_creator,
)
from app.services.mediaspider.http_platforms.xhs.normalize import (
    normalize_creator as normalize_xhs_creator,
)
from app.services.mediaspider.runtime.collector import build_safe_creator


def test_douyin_creator_keeps_current_and_max_fans_separate():
    creator = normalize_douyin_creator(
        "MS4wLjABAAAA-metrics",
        {
            "nickname": "指标账号",
            "follower_count": 120,
            "fans_count": 130,
            "max_follower_count": 500,
        },
    )

    assert creator is not None
    assert creator["fans_count"] == 120
    assert creator["max_fans_count"] == 500


def test_douyin_max_fans_does_not_fall_back_to_current_fans():
    creator = normalize_douyin_creator(
        "MS4wLjABAAAA-max-only",
        {
            "nickname": "仅最大值账号",
            "max_follower_count": 500,
        },
    )

    assert creator is not None
    assert creator["fans_count"] is None
    assert creator["max_fans_count"] == 500


def test_xhs_creator_exposes_both_fans_fields_when_available():
    creator = normalize_xhs_creator(
        "xhs-user-id",
        {
            "basicInfo": {
                "nickname": "小红书指标账号",
                "maxFollowerCount": 260,
            },
            "interactions": [{"type": "fans", "count": 200}],
        },
    )

    assert creator is not None
    assert creator["fans_count"] == 200
    assert creator["max_fans_count"] == 260


def test_safe_creator_contract_does_not_merge_max_into_current():
    creator = build_safe_creator(
        "dy",
        "raw-user",
        {
            "nickname": "安全账号",
            "follower_count": 300,
            "max_follower_count": 900,
        },
    )

    assert creator["fans_count"] == 300
    assert creator["max_fans_count"] == 900


def test_competitor_metrics_continue_using_current_fans():
    normalized = normalize_account(
        "dy",
        {
            "display_name": "竞品账号",
            "fans_count": 400,
            "max_fans_count": 1000,
        },
    )

    assert normalized.metrics["followers"] == 400
