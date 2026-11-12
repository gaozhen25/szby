import json

import pytest
from pydantic import ValidationError

from app.services.account_report.domain.models import (
    AccountReportPayload,
    ContentEvidence,
    KeywordPlan,
)
from app.services.account_report.evidence import build_report_evidence, normalize_metric
from app.services.account_report.evidence.hot_contents import select_balanced_hot_contents
from app.services.account_report.generation.prompts import (
    build_account_report_prompt,
    parse_account_report,
)
from app.services.account_report.generation.sections import (
    build_report_section_prompt,
    get_report_section_spec,
)
from app.services.mediaspider.models import CrawlResult


def _result(platform: str, *, contents=None, creators=None, comments=None) -> CrawlResult:
    return CrawlResult(
        platform=platform,
        crawl_type="search",
        contents=contents or [],
        creators=creators or [],
        comments=comments or [],
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 0), (12, 12), ("1,234", 1234), ("3.2万+", 32000), ("0.8亿", 80000000), ("--", 0)],
)
def test_normalize_metric_supports_platform_display_values(raw, expected):
    assert normalize_metric(raw) == expected


def test_hot_content_selection_picks_highest_liked():
    candidates = []
    for index in range(12):
        candidates.append(
            ContentEvidence(
                platform="xhs" if index % 2 else "dy",
                content_id=f"n{index}",
                content_type="image" if index % 3 else "video",
                liked_count=index * 100,
                source_keyword=f"词{index % 4}",
            )
        )

    selected = select_balanced_hot_contents(candidates, platforms=["小红书", "抖音"])

    assert len(selected) == 8
    # 双平台各 4：各自点赞 Top，再按点赞总排序
    assert sum(1 for item in selected if item.platform == "dy") == 4
    assert sum(1 for item in selected if item.platform == "xhs") == 4
    assert [item.content_id for item in selected] == [f"n{index}" for index in range(11, 3, -1)]
    assert [item.liked_count for item in selected] == [1100, 1000, 900, 800, 700, 600, 500, 400]


def test_hot_content_selection_takes_two_per_keyword_first():
    candidates = []
    for keyword_index in range(4):
        keyword = f"词{keyword_index}"
        for rank in range(5):
            candidates.append(
                ContentEvidence(
                    platform="dy",
                    content_id=f"k{keyword_index}-r{rank}",
                    content_type="video",
                    liked_count=1000 - keyword_index * 10 - rank,
                    source_keyword=keyword,
                )
            )

    selected = select_balanced_hot_contents(candidates, platforms=["抖音"])

    assert len(selected) == 8
    assert {item.source_keyword for item in selected} == {"词0", "词1", "词2", "词3"}
    assert all(
        sum(1 for item in selected if item.source_keyword == keyword) == 2
        for keyword in ("词0", "词1", "词2", "词3")
    )
    assert {item.content_id for item in selected} == {
        "k0-r0",
        "k0-r1",
        "k1-r0",
        "k1-r1",
        "k2-r0",
        "k2-r1",
        "k3-r0",
        "k3-r1",
    }


def test_hot_content_selection_dual_platform_half_by_likes():
    candidates = [
        ContentEvidence(platform="dy", content_id="dy-low", content_type="video", liked_count=10),
        ContentEvidence(platform="dy", content_id="dy-high", content_type="video", liked_count=900),
        ContentEvidence(platform="dy", content_id="dy-mid", content_type="video", liked_count=400),
        ContentEvidence(platform="xhs", content_id="xhs-mid", content_type="image", liked_count=500),
        ContentEvidence(platform="xhs", content_id="xhs-top", content_type="image", liked_count=1200),
        ContentEvidence(platform="xhs", content_id="xhs-low", content_type="image", liked_count=50),
    ]

    selected = select_balanced_hot_contents(
        candidates, platforms=["抖音", "小红书"], limit=4
    )

    assert len(selected) == 4
    assert sum(1 for item in selected if item.platform == "dy") == 2
    assert sum(1 for item in selected if item.platform == "xhs") == 2
    assert {item.content_id for item in selected} == {
        "dy-high",
        "dy-mid",
        "xhs-top",
        "xhs-mid",
    }
    assert [item.content_id for item in selected] == [
        "xhs-top",
        "dy-high",
        "xhs-mid",
        "dy-mid",
    ]


def test_hot_content_selection_single_platform_ignores_other_side_quota():
    candidates = [
        ContentEvidence(platform="dy", content_id="dy-low", content_type="video", liked_count=10),
        ContentEvidence(platform="dy", content_id="dy-high", content_type="video", liked_count=900),
        ContentEvidence(platform="xhs", content_id="xhs-mid", content_type="image", liked_count=500),
        ContentEvidence(platform="xhs", content_id="xhs-top", content_type="image", liked_count=1200),
    ]

    selected = select_balanced_hot_contents(candidates, platforms=["抖音"], limit=3)

    # 账号仅抖音：配额全给抖音；不足时用另一边回填，最终仍按点赞排序
    assert [item.content_id for item in selected] == ["xhs-top", "dy-high", "dy-low"]
    assert sum(1 for item in selected if item.platform == "dy") == 2

def test_koubo_tags_require_detection_or_existing_tag():
    from app.services.account_report.evidence.hot_contents import koubo_tags_for_item

    dy_video = ContentEvidence(platform="dy", content_id="v1", content_type="video")
    xhs_video = ContentEvidence(platform="xhs", content_id="v2", content_type="video")
    dy_image = ContentEvidence(platform="dy", content_id="i1", content_type="image")

    assert koubo_tags_for_item(dy_video) == []
    assert koubo_tags_for_item(dy_video, detected=True) == ["口播"]
    assert koubo_tags_for_item(dy_video, ["热门"], detected=True) == ["热门", "口播"]
    assert koubo_tags_for_item(xhs_video, detected=True) == ["口播"]
    assert koubo_tags_for_item(dy_image, detected=True) == []


def test_hot_content_selection_excludes_previous_batch_ids():
    candidates = [
        ContentEvidence(
            platform="dy",
            content_id=f"video-{index}",
            content_type="video",
            liked_count=index * 10,
        )
        for index in range(12)
    ]
    selected = select_balanced_hot_contents(
        candidates,
        platforms=["抖音"],
        exclude_keys={("dy", f"video-{index}") for index in range(8)},
    )

    ids = {item.content_id for item in selected}
    assert ids == {"video-8", "video-9", "video-10", "video-11"}
    assert [item.content_id for item in selected] == ["video-11", "video-10", "video-9", "video-8"]
    assert len(selected) == 4


def test_hot_content_selection_fills_to_limit_by_likes_when_types_imbalanced():
    candidates = [
        ContentEvidence(
            platform="dy",
            content_id=f"video-{index}",
            content_type="video",
            liked_count=1000 - index,
        )
        for index in range(10)
    ] + [
        ContentEvidence(
            platform="xhs",
            content_id=f"image-{index}",
            content_type="image",
            liked_count=50 - index,
        )
        for index in range(2)
    ]

    selected = select_balanced_hot_contents(
        candidates, platforms=["抖音", "小红书"]
    )

    assert len(selected) == 8
    assert sum(1 for item in selected if item.platform == "dy") == 6
    assert sum(1 for item in selected if item.platform == "xhs") == 2
    assert {item.content_id for item in selected} == {
        *(f"video-{index}" for index in range(6)),
        "image-0",
        "image-1",
    }


def test_hot_content_score_is_normalized_within_platform_and_content_type():
    evidence = build_report_evidence(
        [],
        [
            _result(
                "xhs",
                contents=[
                    {
                        "note_id": "xhs-low",
                        "liked_count": 10,
                        "content_type": "image",
                        "source_keyword": "露营",
                    },
                    {
                        "note_id": "xhs-high",
                        "liked_count": 100,
                        "content_type": "image",
                        "source_keyword": "露营",
                    },
                ],
            ),
            _result(
                "dy",
                contents=[
                    {
                        "aweme_id": "dy-low",
                        "liked_count": 1_000,
                        "content_type": "video",
                        "source_keyword": "露营",
                    },
                    {
                        "aweme_id": "dy-high",
                        "liked_count": 10_000,
                        "content_type": "video",
                        "source_keyword": "露营",
                    },
                ],
            ),
        ],
        set(),
    )

    scores = {item.content_id: item.hot_score for item in evidence.industry.hot_contents}
    assert scores["xhs-high"] > scores["xhs-low"]
    assert scores["dy-high"] > scores["dy-low"]
    assert scores["xhs-high"] == scores["dy-high"]


def test_similar_account_ranking_prefers_higher_follower_count():
    evidence = build_report_evidence(
        [
            _result(
                "xhs",
                creators=[{"user_id": "owner", "fans_count": 10_000}],
            )
        ],
        [
            _result(
                "xhs",
                creators=[
                    {
                        "user_id": "large",
                        "fans_count": 5_000_000,
                        "matched_queries": ["露营"],
                        "evidence_completeness": 0.8,
                    },
                    {
                        "user_id": "peer",
                        "fans_count": 15_000,
                        "matched_queries": ["露营"],
                        "evidence_completeness": 0.8,
                    },
                ],
            )
        ],
        {"owner"},
    )

    assert evidence.industry.similar_accounts[0].fans_count == 5_000_000
    assert (
        evidence.industry.similar_accounts[0].similarity_score
        > evidence.industry.similar_accounts[1].similarity_score
    )


def test_report_evidence_separates_current_account_from_industry_candidates():
    current = _result(
        "xhs",
        contents=[
            {
                "note_id": "own-1",
                "creator_hash": "owner",
                "title": "自己的高赞作品",
                "liked_count": 999999,
            }
        ],
        creators=[
            {"creator_hash": "owner", "nickname": "自己的账号", "fans_count": 1000}
        ],
    )
    industry = _result(
        "xhs",
        contents=[
            {
                "note_id": "industry-1",
                "creator_hash": "peer",
                "title": "行业样本",
                "liked_count": 100,
            }
        ],
        creators=[
            {"creator_hash": "peer", "nickname": "行业账号", "fans_count": 2000}
        ],
    )

    evidence = build_report_evidence([current], [industry], {"owner"})

    assert [item.content_id for item in evidence.current_account.contents] == [
        "own-1"
    ]
    assert [item.content_id for item in evidence.industry.hot_contents] == [
        "industry-1"
    ]
    assert all(
        item.creator_hash != evidence.owner_hashes[0]
        for item in evidence.industry.similar_accounts
    )


def test_unknown_owner_keeps_all_keyword_industry_evidence():
    evidence = build_report_evidence(
        [],
        [
            _result(
                "xhs",
                contents=[
                    {
                        "note_id": "possible-self",
                        "user_id": "unknown-self",
                        "title": "可能属于当前账号",
                    },
                    {
                        "note_id": "industry-note",
                        "user_id": "industry-author",
                        "title": "行业样本",
                    },
                ],
                creators=[
                    {"user_id": "unknown-self", "nickname": "未知账号"},
                    {"user_id": "industry-author", "nickname": "行业账号"},
                ],
            )
        ],
        set(),
    )

    assert {item.content_id for item in evidence.industry.hot_contents} == {
        "possible-self",
        "industry-note",
    }
    assert len(evidence.industry.similar_accounts) == 2


def test_current_and_industry_comments_share_one_bounded_budget():
    def result_with_comments(platform, prefix):
        contents = [
            {
                "note_id" if platform == "xhs" else "aweme_id": f"{prefix}-{index}",
                "creator_hash": f"{prefix}-author",
            }
            for index in range(5)
        ]
        comments = [
            {
                "note_id" if platform == "xhs" else "aweme_id": f"{prefix}-{index % 5}",
                "content": f"{prefix} 第 {index} 条有效反馈内容",
            }
            for index in range(15)
        ]
        return _result(platform, contents=contents, comments=comments)

    evidence = build_report_evidence(
        [result_with_comments("xhs", "current")],
        [result_with_comments("dy", "industry")],
        set(),
    )

    comments = [
        *evidence.current_account.comments,
        *evidence.industry.comments,
    ]
    assert len(comments) == 20
    assert len(evidence.current_account.comments) == 10
    assert len(evidence.industry.comments) == 10
    assert all(
        sum(
            item.platform == platform and item.content_id == content_id
            for item in comments
        )
        <= 3
        for platform, content_id in {
            (item.platform, item.content_id) for item in comments
        }
    )


def test_prompt_names_current_account_and_industry_evidence_separately():
    evidence = build_report_evidence(
        [_result("xhs", contents=[{"note_id": "own", "creator_hash": "owner"}])],
        [
            _result(
                "xhs",
                contents=[{"note_id": "industry", "creator_hash": "peer"}],
            )
        ],
        {"owner"},
    )

    prompt = build_account_report_prompt(
        {"account": {"industry": "美妆"}},
        evidence,
        {"platforms": ["小红书"]},
    )

    assert '"currentAccountEvidence"' in prompt
    assert '"industryEvidence"' in prompt
    assert "不得用当前账号作品填充行业热门内容" in prompt


def test_creator_display_data_is_preserved_but_removed_from_ai_prompt():
    complete_note_url = (
        "https://www.xiaohongshu.com/explore/note-1"
        "?xsec_token=public-note-token%3D&xsec_source=pc_search"
    )
    evidence = build_report_evidence(
        [],
        [
            _result(
                "xhs",
                contents=[
                    {
                        "note_id": "note-1",
                        "creator_hash": "0123456789abcdef",
                        "nickname": "公***称",
                        "note_url": complete_note_url,
                    }
                ],
                creators=[
                    {
                        "creator_hash": "0123456789abcdef",
                        "nickname": "公***称",
                        "display_name": "公开博主名称",
                        "profile_url": (
                            "https://www.xiaohongshu.com/user/profile/public-id"
                        ),
                        "avatar": "https://sns-avatar.example.test/public-id.png",
                    }
                ],
            )
        ],
        set(),
    )

    creator = evidence.industry.similar_accounts[0]
    assert creator.display_name == "公开博主名称"
    assert creator.profile_url.endswith("/public-id")
    assert creator.avatar_url.endswith("/public-id.png")

    prompt = build_account_report_prompt(
        {"account": {"industry": "美妆"}},
        evidence,
        {"platforms": ["小红书"]},
    )
    assert creator.name in prompt
    assert complete_note_url in prompt
    assert "公开博主名称" not in prompt
    assert "/user/profile/public-id" not in prompt
    assert '"profileUrl"' not in prompt
    assert '"displayName"' not in prompt
    assert '"avatarUrl"' not in prompt


def test_content_only_creator_candidates_inherit_public_display_fields():
    evidence = build_report_evidence(
        [],
        [
            _result(
                "xhs",
                contents=[
                    {
                        "note_id": "note-1",
                        "creator_hash": "0123456789abcdef",
                        "nickname": "公***称",
                        "display_name": "公开博主名称",
                        "profile_url": (
                            "https://www.xiaohongshu.com/user/profile/public-id"
                        ),
                        "avatar": "https://sns-avatar.example.test/public-id.png",
                    }
                ],
            )
        ],
        set(),
    )

    creator = evidence.industry.similar_accounts[0]
    assert creator.display_name == "公开博主名称"
    assert creator.profile_url.endswith("/public-id")
    assert creator.avatar_url.endswith("/public-id.png")

    prompt = build_account_report_prompt(
        {"account": {"industry": "美妆"}},
        evidence,
        {"platforms": ["小红书"]},
    )
    assert "公开博主名称" not in prompt
    assert "/user/profile/public-id" not in prompt


def test_report_prompt_requires_evidence_and_predictive_industry_compliance_rules():
    prompt = build_account_report_prompt(
        {
            "account": {
                "industry": "美妆",
                "productService": "功效护肤",
                "platforms": ["小红书"],
            }
        },
        build_report_evidence([], [], set()),
        {"platforms": ["小红书"]},
    )

    assert "证据复盘风险" in prompt
    assert "行业预防风险" in prompt
    assert "即使公开样本中暂未出现" in prompt
    assert "不得把预防性风险描述为当前账号已经违规" in prompt
    assert "不得编造法规编号、处罚结果或平台公告" in prompt


def test_build_report_evidence_adapts_platforms_deduplicates_and_excludes_owner():
    crawl_results = [
        _result(
            "xhs",
            contents=[
                {
                    "note_id": "same",
                    "note_url": "https://xhs/same",
                    "title": "旧版本",
                    "creator_hash": "owner",
                    "liked_count": "1万",
                },
                {
                    "note_id": "hot",
                    "note_url": "https://xhs/hot",
                    "title": "小红书爆款",
                    "desc": "正文",
                    "creator_hash": "competitor",
                    "liked_count": "3.2万",
                    "collected_count": "100",
                    "source_keyword": "通勤妆",
                },
            ],
            creators=[
                {"creator_hash": "owner", "nickname": "自有账号", "fans_count": "9万"},
                {"creator_hash": "competitor", "nickname": "竞品", "fans_count": "2万"},
            ],
        ),
        _result(
            "xhs",
            contents=[
                {
                    "note_id": "same",
                    "title": "新版本",
                    "creator_hash": "other",
                    "liked_count": "2万",
                }
            ],
        ),
        _result(
            "dy",
            contents=[
                {
                    "aweme_id": "dy-1",
                    "aweme_url": "https://douyin/dy-1",
                    "title": "抖音视频",
                    "creator_hash": "dy-author",
                    "liked_count": 500,
                    "comment_count": 100,
                }
            ],
        ),
        _result(
            "ks",
            contents=[
                {
                    "video_id": "ks-1",
                    "video_url": "https://kuaishou/ks-1",
                    "title": "快手视频",
                    "creator_hash": "ks-author",
                    "liked_count": 400,
                }
            ],
        ),
    ]

    evidence = build_report_evidence([], crawl_results, {"owner"})
    industry = evidence.industry

    assert industry.hot_contents[0].title == "小红书爆款"
    assert industry.hot_contents[0].liked_count == 32000
    assert len([item for item in industry.hot_contents if item.platform == "xhs" and item.content_id == "same"]) == 1
    assert {item.platform for item in industry.hot_contents} == {"xhs", "dy", "ks"}
    assert all(item.creator_hash != evidence.owner_hashes[0] for item in industry.similar_accounts)
    assert all(len(item.creator_hash) == 16 for item in industry.hot_contents)


def test_build_report_evidence_ranks_and_truncates_before_prompting():
    contents = [
        {
            "aweme_id": f"item-{index}",
            "creator_hash": f"creator-{index}",
            "liked_count": index,
        }
        for index in range(30)
    ]
    creators = [
        {"creator_hash": f"creator-{index}", "fans_count": index * 100}
        for index in range(50)
    ]

    evidence = build_report_evidence(
        [], [_result("dy", contents=contents, creators=creators)], set()
    )

    assert len(evidence.industry.hot_contents) == 30
    assert evidence.industry.hot_contents[0].liked_count == 29
    assert len(evidence.industry.similar_accounts) == 40


def test_comments_are_bounded_desensitized_prompt_only_evidence():
    comments = []
    for index in range(30):
        comments.append(
            {
                "note_id": "note-1" if index < 10 else f"note-{index}",
                "content": (
                    f"第{index}条真实反馈，联系 13800138000 "
                    "https://secret.example/path?token=SENTINEL_TOKEN @raw-user "
                    "Cookie=COOKIE_SECRET Authorization: Bearer AUTH_SECRET token=RAW_TOKEN"
                ),
                "user_id": f"raw-commenter-{index}",
                "nickname": f"评论者{index}",
                "like_count": 30 - index,
            }
        )
    contents = [
        {"note_id": "note-1", "user_id": "author-1", "title": "样本"},
        *[
            {"note_id": f"note-{index}", "user_id": f"author-{index}", "title": f"样本{index}"}
            for index in range(10, 30)
        ],
    ]
    evidence = build_report_evidence(
        [],
        [_result("xhs", contents=contents, comments=comments)],
        set(),
    )

    assert len(evidence.industry.comments) <= 20
    assert len([item for item in evidence.industry.comments if item.content_id == "note-1"]) <= 3
    serialized = evidence.model_dump_json()
    assert "真实反馈" in serialized
    assert "raw-commenter" not in serialized
    assert "评论者" not in serialized
    assert "13800138000" not in serialized
    assert "SENTINEL_TOKEN" not in serialized
    assert "COOKIE_SECRET" not in serialized
    assert "AUTH_SECRET" not in serialized
    assert "RAW_TOKEN" not in serialized
    assert "secret.example" not in serialized
    assert "@raw-user" not in serialized

    prompt = build_account_report_prompt(
        {"account": {"industry": "美妆"}},
        evidence,
        {"platforms": ["小红书"]},
    )
    assert "真实反馈" in prompt
    assert "SENTINEL_TOKEN" not in prompt


def test_comments_never_enter_the_ai_report_persistence_contract():
    payload = _valid_report_dict()
    payload["comments"] = [{"text": "must-not-persist"}]
    report = AccountReportPayload.model_validate(payload)
    assert "comments" not in report.model_dump(mode="json", by_alias=True)


def test_non_string_or_structured_comment_payload_cannot_enter_prompt_evidence():
    evidence = build_report_evidence(
        [],
        [
            _result(
                "xhs",
                contents=[{"note_id": "note-1", "user_id": "author"}],
                comments=[
                    {
                        "note_id": "note-1",
                        "content": {"token": "NESTED_SECRET", "user_id": "raw-user"},
                    },
                    {
                        "note_id": "note-1",
                        "content": "反馈 {'token': 'TEXT_SECRET', 'user_id': 'text-user'}",
                    },
                ],
            )
        ],
        set(),
    )
    serialized = evidence.model_dump_json()
    assert "NESTED_SECRET" not in serialized
    assert "raw-user" not in serialized
    assert "TEXT_SECRET" not in serialized
    assert "text-user" not in serialized


def test_comment_contact_details_are_removed_and_prompt_forbids_verbatim_output():
    evidence = build_report_evidence(
        [],
        [
            _result(
                "xhs",
                contents=[{"note_id": "note-1", "user_id": "author"}],
                comments=[
                    {
                        "note_id": "note-1",
                        "content": (
                            "邮箱contact@example.com请联系 身份证 11010519491231002X "
                            "QQ号码12345678 微信:wx_contact_88 vx:wx_contact_99 "
                            "wechat:another_contact 座机(010)87654321 或400-123-4567"
                        ),
                    }
                ],
            )
        ],
        set(),
    )
    prompt = build_account_report_prompt(
        {"account": {"industry": "美妆"}},
        evidence,
        {"platforms": ["小红书"]},
    )
    assert "contact@example.com" not in prompt
    assert "11010519491231002X" not in prompt
    assert "12345678" not in prompt
    assert "wx_contact_88" not in prompt
    assert "wx_contact_99" not in prompt
    assert "another_contact" not in prompt
    assert "(010)87654321" not in prompt
    assert "400-123-4567" not in prompt
    assert "仅用于聚合" in prompt
    assert "不得逐字引用" in prompt


def test_comment_contact_connecting_words_are_desensitized_before_prompting():
    evidence = build_report_evidence(
        [],
        [
            _result(
                "xhs",
                contents=[{"note_id": "note-1", "user_id": "author"}],
                comments=[
                    {
                        "note_id": "note-1",
                        "content": (
                            "我的微信是WECHAT_SENTINEL，微信号为WX_SENTINEL，"
                            "QQ号是123456789"
                        ),
                    }
                ],
            )
        ],
        set(),
    )
    prompt = build_account_report_prompt({}, evidence, {"platforms": ["小红书"]})
    assert "WECHAT_SENTINEL" not in prompt
    assert "WX_SENTINEL" not in prompt
    assert "123456789" not in prompt


def test_raw_hex_ids_are_hashed_and_names_are_masked_at_report_boundary():
    raw_hex_id = "0123456789abcdef"
    evidence = build_report_evidence(
        [],
        [
            _result(
                "dy",
                contents=[
                    {
                        "aweme_id": "raw-author",
                        "author_id": raw_hex_id,
                        "nickname": "原始作者姓名",
                        "liked_count": 1,
                    },
                    {
                        "aweme_id": "trusted-author",
                        "creator_hash": raw_hex_id,
                        "nickname": "另一个原始姓名",
                        "liked_count": 2,
                    },
                ],
                creators=[
                    {"id": raw_hex_id, "nickname": "创作者原名", "fans_count": 10},
                    {"creator_hash": raw_hex_id, "nickname": "可信创作者名", "fans_count": 20},
                ],
            )
        ],
        set(),
    )

    raw_item = next(item for item in evidence.industry.hot_contents if item.content_id == "raw-author")
    trusted_item = next(item for item in evidence.industry.hot_contents if item.content_id == "trusted-author")
    assert raw_item.creator_hash != raw_hex_id
    assert trusted_item.creator_hash == raw_hex_id
    assert raw_item.creator_name == "原***名"
    assert trusted_item.creator_name == "另***名"
    assert all(item.name not in {"创作者原名", "可信创作者名"} for item in evidence.industry.similar_accounts)


@pytest.mark.parametrize("raw", ["12abc", "3万亿", "1.2万foo", "1++", "万3"])
def test_normalize_metric_rejects_partially_valid_or_ambiguous_values(raw):
    assert normalize_metric(raw) == 0


def _valid_report_dict():
    return {
        "similarAccounts": [
            {"platform": "小红书", "creatorHash": "abc", "name": "同类账号", "similarityReason": "定位相似"}
        ],
        "complianceRules": [
            {"riskLevel": "high", "expression": "最有效", "reason": "绝对化", "suggestion": "多数用户反馈"}
        ],
        "targetUserProfile": {
            "assumption": "",
            "categories": [
                {
                    "categoryName": name,
                    "purchaseMotivation": "在明确场景中获得可靠方案。",
                    "maleProfile": {"applicable": True, "description": "现实中可辨认的男性用户画像。"},
                    "femaleProfile": {"applicable": True, "description": "现实中可辨认的女性用户画像。"},
                }
                for name in ("通勤应急者", "状态重建者", "场合准备者")
            ],
            "priorityRanking": {
                "rankedCategories": [
                    {
                        "categoryName": name,
                        "contentAttraction": "high",
                        "trustDifficulty": "medium",
                        "paymentLikelihood": "high",
                        "repurchaseLikelihood": "medium",
                        "reason": "需求具体且可被内容验证。",
                    }
                    for name in ("通勤应急者", "状态重建者", "场合准备者")
                ],
                "priorityCategory": "通勤应急者",
                "priorityReason": "需求发生频率最高。",
            },
            "positioningReminder": {
                "commonMisjudgment": "把泛兴趣误判为购买意向。",
                "hypothesisToValidate": "场景化实测是否带来更多咨询。",
            },
        },
        "hotContents": [
            {"platform": "抖音", "contentId": "1", "title": "通勤实测", "selectionReason": "互动高"}
        ],
        "sourceMeta": {
            "platforms": ["小红书", "抖音"],
            "keywords": ["通勤妆", "敏感肌", "底妆实测", "妆前打底"],
            "sampleCount": 20,
        },
    }


def test_keyword_plan_requires_exactly_five_unique_short_terms():
    assert KeywordPlan(
        keywords=[" 通勤妆 ", "敏感肌", "底妆测评", "妆前打底", "底妆实测"]
    ).keywords == ["通勤妆", "敏感肌", "底妆测评", "妆前打底", "底妆实测"]
    with pytest.raises(ValidationError):
        KeywordPlan(keywords=["通勤妆", "通勤妆", "敏感肌", "底妆测评", "妆前打底"])
    with pytest.raises(ValidationError):
        KeywordPlan(keywords=["通勤妆", "敏感肌", "底妆测评", "妆前打底"])
    with pytest.raises(ValidationError):
        KeywordPlan(
            keywords=["通勤妆", "敏感肌", "底妆测评", "妆前打底", "持妆喷雾", "伪素颜"]
        )
    with pytest.raises(ValidationError):
        KeywordPlan(
            keywords=["这是一个明显超过十二个字符的检索关键词", "敏感肌", "底妆", "妆前", "打底"]
        )


def test_reference_section_prompts_require_industry_strong_relevance():
    evidence = build_report_evidence(
        [],
        [
            _result(
                "xhs",
                contents=[
                    {
                        "note_id": "geo-note",
                        "title": "GEO优化案例",
                        "desc": "AI搜索优化内容",
                        "creator_hash": "geo-author",
                        "source_keyword": "GEO优化",
                    }
                ],
                creators=[
                    {
                        "creator_hash": "geo-author",
                        "nickname": "GEO顾问",
                        "matched_queries": ["GEO优化"],
                        "representative_contents": ["AI搜索优化案例"],
                    }
                ],
            )
        ],
        set(),
    )
    account_context = {"account": {"industry": "GEO", "productService": "AI搜索优化"}}
    source_meta = {"platforms": ["小红书"], "keywords": ["GEO优化", "AI搜索优化"]}

    similar_prompt = build_report_section_prompt(
        get_report_section_spec("similarAccounts"), account_context, evidence, source_meta
    )
    hot_prompt = build_report_section_prompt(
        get_report_section_spec("hotContents"), account_context, evidence, source_meta
    )

    assert "不要只因为" in similar_prompt or "高度垂直" in similar_prompt
    assert "泛获客" in similar_prompt or "蹭边" in similar_prompt
    assert "大学生求职" in similar_prompt
    assert "点赞" in hot_prompt
    assert "凑满 8 条" in hot_prompt
    assert "不要只因为目标客户相似" in hot_prompt
    assert "大学生求职通用模板" in hot_prompt
    assert "泛营销" in hot_prompt


def test_parse_account_report_accepts_only_complete_json_or_fenced_json():
    payload = _valid_report_dict()
    parsed = parse_account_report(f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```")

    assert isinstance(parsed, AccountReportPayload)
    summaries = parsed.compatibility_summaries()
    assert set(summaries) == {"competitors", "prohibitedWords", "targetUsers", "hotContent"}
    assert all(value.strip() for value in summaries.values())

    incomplete = dict(payload)
    del incomplete["sourceMeta"]
    with pytest.raises(ValidationError):
        parse_account_report(json.dumps(incomplete, ensure_ascii=False))
    with pytest.raises(ValueError):
        parse_account_report(f"分析如下：{json.dumps(payload, ensure_ascii=False)}")


def test_parse_account_report_accepts_bare_json_and_rejects_bad_fences_or_trailing_text():
    raw = json.dumps(_valid_report_dict(), ensure_ascii=False)
    assert parse_account_report(raw).target_user_profile.categories[0].category_name == "通勤应急者"

    with pytest.raises(ValueError):
        parse_account_report(f"```yaml\n{raw}\n```")
    with pytest.raises(ValueError):
        parse_account_report(f"```json\n{raw}\n```\n附加说明")
    with pytest.raises(ValueError):
        parse_account_report(f"```json\n{raw}")


def test_parse_account_report_normalizes_observed_llm_schema_variants():
    payload = _valid_report_dict()
    payload["complianceRules"] = [
        {
            "riskLevel": "高",
            "originalExpression": "全网第一",
            "reason": "属于绝对化表达",
            "suggestedExpression": "受到不少用户欢迎",
            "platforms": ["小红书"],
        },
        {
            "riskLevel": "中",
            "originalText": "到店使用套餐",
            "reason": "适用条件不够清晰",
            "alternative": "到店后按套餐说明使用",
        },
    ]
    parsed = parse_account_report(json.dumps(payload, ensure_ascii=False))

    assert [item.risk_level for item in parsed.compliance_rules] == ["high", "medium"]
    assert parsed.compliance_rules[0].expression == "全网第一"
    assert parsed.compliance_rules[0].suggestion == "受到不少用户欢迎"
    assert parsed.compliance_rules[1].expression == "到店使用套餐"
    assert parsed.compliance_rules[1].suggestion == "到店后按套餐说明使用"


def test_account_report_prompt_declares_exact_nested_json_contract():
    prompt = build_account_report_prompt(
        {"account": {"industry": "餐饮"}},
        build_report_evidence([], [], set()),
        {"platforms": ["小红书"]},
    )

    assert '"riskLevel":"high"' in prompt
    assert '"expression":"原表达"' in prompt
    assert '"suggestion":"替代表达"' in prompt
    assert '"categories"' in prompt
    assert '"purchaseMotivation"' in prompt
    assert '"specificProfile"' in prompt
    assert '"priority":1' in prompt
    assert '"priorityRanking"' in prompt
    assert '"positioningReminder"' in prompt
    assert '"topBloggers"' not in prompt
    assert '"contentStrategy"' not in prompt
    assert "riskLevel 只能使用 high、medium、low" in prompt


def test_target_user_profile_requires_three_to_five_categories_and_matching_priority_order():
    payload = _valid_report_dict()
    payload["targetUserProfile"]["categories"] = payload["targetUserProfile"]["categories"][:2]
    payload["targetUserProfile"]["priorityRanking"]["rankedCategories"] = payload["targetUserProfile"]["priorityRanking"]["rankedCategories"][:2]
    with pytest.raises(ValidationError):
        AccountReportPayload.model_validate(payload)

    payload = _valid_report_dict()
    payload["targetUserProfile"]["priorityRanking"]["priorityCategory"] = "状态重建者"
    with pytest.raises(ValidationError, match="优先排序第一项"):
        AccountReportPayload.model_validate(payload)


def test_target_user_profile_accepts_new_specific_profile_contract():
    payload = _valid_report_dict()
    for index, category in enumerate(payload["targetUserProfile"]["categories"], start=1):
        category.pop("maleProfile")
        category.pop("femaleProfile")
        category["specificProfile"] = "这是一段现实中可辨认的具体用户画像，会说明当前购买场景、替代方案失效原因、真正担心的结果和咨询触发点。"
        ranking = payload["targetUserProfile"]["priorityRanking"]["rankedCategories"][index - 1]
        ranking["priority"] = index
        ranking["contentAttraction"] = "高"
        ranking["trustDifficulty"] = "中等"
        ranking["paymentLikelihood"] = "较高"
        ranking["repurchaseLikelihood"] = "较高"

    parsed = AccountReportPayload.model_validate(payload)

    assert parsed.target_user_profile.categories[0].specific_profile.startswith("这是一段现实中可辨认")
    assert parsed.target_user_profile.categories[0].male_profile is None
    assert parsed.target_user_profile.priority_ranking.ranked_categories[0].priority == 1
    assert parsed.target_user_profile.priority_ranking.ranked_categories[0].content_attraction == "高"


def test_account_report_payload_enforces_collection_limits():
    payload = _valid_report_dict()
    payload["hotContents"] = payload["hotContents"] * 21
    with pytest.raises(ValidationError):
        AccountReportPayload.model_validate(payload)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("similarAccounts", 0, "name"), "   "),
        (("complianceRules", 0, "reason"), ""),
        (("targetUserProfile", "categories", 0, "categoryName"), " \n "),
        (("targetUserProfile", "categories", 0, "purchaseMotivation"), " "),
        (("hotContents", 0, "title"), ""),
        (("sourceMeta", "platforms", 0), " "),
    ],
)
def test_account_report_payload_rejects_blank_critical_strings(path, value):
    payload = _valid_report_dict()
    target = payload
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value

    with pytest.raises(ValidationError):
        AccountReportPayload.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "count"),
    [
        ("similarAccounts", 21),
        ("complianceRules", 0),
        ("complianceRules", 21),
        ("hotContents", 21),
    ],
)
def test_account_report_payload_enforces_all_top_level_array_boundaries(field, count):
    payload = _valid_report_dict()
    original = payload[field]
    payload[field] = [] if count == 0 else original * count
    with pytest.raises(ValidationError):
        AccountReportPayload.model_validate(payload)


def test_source_meta_allows_empty_keywords_for_explicit_video_channel_degradation():
    payload = _valid_report_dict()
    payload["sourceMeta"]["platforms"] = ["视频号"]
    payload["sourceMeta"]["keywords"] = []
    payload["sourceMeta"]["unsupportedPlatforms"] = ["视频号"]
    assert AccountReportPayload.model_validate(payload).source_meta.keywords == []


@pytest.mark.parametrize("supported_platform", ["xhs", "小红书", "dy", "douyin", "抖音", "ks", "kuaishou", "快手"])
def test_source_meta_rejects_empty_keywords_when_any_supported_platform_is_present(supported_platform):
    payload = _valid_report_dict()
    payload["sourceMeta"]["platforms"] = [supported_platform, "视频号"]
    payload["sourceMeta"]["keywords"] = []
    payload["sourceMeta"]["unsupportedPlatforms"] = ["视频号"]
    with pytest.raises(ValidationError):
        AccountReportPayload.model_validate(payload)


def test_source_meta_rejects_empty_keywords_without_explicit_video_channel_marker():
    payload = _valid_report_dict()
    payload["sourceMeta"]["platforms"] = ["视频号"]
    payload["sourceMeta"]["keywords"] = []
    payload["sourceMeta"]["unsupportedPlatforms"] = []
    with pytest.raises(ValidationError):
        AccountReportPayload.model_validate(payload)


def test_source_meta_nonempty_keywords_still_require_three_to_five_terms():
    payload = _valid_report_dict()
    payload["sourceMeta"]["keywords"] = ["词一", "词二"]
    with pytest.raises(ValidationError):
        AccountReportPayload.model_validate(payload)

    payload = _valid_report_dict()
    payload["sourceMeta"]["keywords"] = [f"词{index}" for index in range(6)]
    with pytest.raises(ValidationError):
        AccountReportPayload.model_validate(payload)

    payload = _valid_report_dict()
    payload["sourceMeta"]["keywords"] = [f"词{index}" for index in range(5)]
    assert len(AccountReportPayload.model_validate(payload).source_meta.keywords) == 5

    payload = _valid_report_dict()
    payload["sourceMeta"]["failedPlatforms"] = [{"platform": f"p{index}", "reason": "失败"} for index in range(11)]
    with pytest.raises(ValidationError):
        AccountReportPayload.model_validate(payload)


def test_compatibility_summaries_translate_risk_levels_to_chinese():
    summaries = AccountReportPayload.model_validate(_valid_report_dict()).compatibility_summaries()
    assert "[高]" in summaries["prohibitedWords"]
    assert "[high]" not in summaries["prohibitedWords"]
