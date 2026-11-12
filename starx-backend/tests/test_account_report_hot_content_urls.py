from app.services.account_report.domain.models import AccountReportPayload
from app.services.account_report.evidence import build_report_evidence
from app.services.account_report.workflows import report as report_workflow
from app.services.account_report.workflows.persistence import build_report_persistence_payload
from app.services.mediaspider.models import CrawlResult


def _report_with_hot_content(public_url: str, cover_url: str = "") -> AccountReportPayload:
    return AccountReportPayload.model_validate(
        {
            "similarAccounts": [],
            "complianceRules": [
                {
                    "riskLevel": "low",
                    "expression": "避免绝对化表达",
                    "reason": "行业常见风险",
                    "suggestion": "使用客观描述",
                }
            ],
            "targetUserProfile": {
                "assumption": "",
                "categories": [
                    {
                        "categoryName": name,
                        "purchaseMotivation": "需要真实体验支持决策。",
                        "maleProfile": {"applicable": True, "description": "关注具体使用效果的男性用户。"},
                        "femaleProfile": {"applicable": True, "description": "关注具体使用效果的女性用户。"},
                    }
                    for name in ("实测决策者", "替代方案失效者", "场景准备者")
                ],
                "priorityRanking": {
                    "rankedCategories": [
                        {"categoryName": name, "contentAttraction": "high", "trustDifficulty": "medium", "paymentLikelihood": "high", "repurchaseLikelihood": "medium", "reason": "需求具体。"}
                        for name in ("实测决策者", "替代方案失效者", "场景准备者")
                    ],
                    "priorityCategory": "实测决策者",
                    "priorityReason": "最容易由实测内容建立信任。",
                },
                "positioningReminder": {
                    "commonMisjudgment": "把围观者视为购买者。",
                    "hypothesisToValidate": "真实对比能否带来咨询。",
                },
            },
            "hotContents": [
                {
                    "platform": "小红书",
                    "contentId": "6a411e68000000000701114b",
                    "title": "爆款笔记",
                    "selectionReason": "互动表现突出",
                    "publicUrl": public_url,
                    "coverUrl": cover_url,
                }
            ],
            "topBloggers": [],
            "contentStrategy": {
                "contentPillars": ["产品实测"],
                "tone": ["客观"],
                "opportunities": ["细分场景"],
                "avoidDirections": ["夸大承诺"],
            },
            "sourceMeta": {
                "platforms": ["小红书"],
                "keywords": ["产品实测", "真实体验", "使用对比"],
                "sampleCount": 1,
            },
        }
    )


def test_persistence_uses_complete_trusted_note_url_after_ai_selection():
    complete_url = (
        "https://www.xiaohongshu.com/explore/6a411e68000000000701114b"
        "?xsec_token=ABsEQjfB8dALwX2ljCtVLnK3wzfUu9tWlrIFgxVCVfq50%3D"
        "&xsec_source=pc_search"
    )
    evidence = build_report_evidence(
        [],
        [
            CrawlResult(
                platform="xhs",
                crawl_type="search",
                contents=[
                    {
                        "note_id": "6a411e68000000000701114b",
                        "note_url": complete_url,
                        "cover_url": "https://cdn.example.test/trusted-cover.webp",
                        "title": "爆款笔记",
                        "liked_count": "1.2万",
                        "collected_count": 3456,
                        "comment_count": 78,
                        "share_count": 90,
                    }
                ],
            )
        ],
        set(),
    )
    ai_report = _report_with_hot_content(
        "https://www.xiaohongshu.com/explore/6a411e68000000000701114b"
    )

    filtered = report_workflow._filter_report_candidates(ai_report, evidence)
    merged = report_workflow._merge_hot_content_urls(filtered, evidence)
    persisted = build_report_persistence_payload(merged)

    assert persisted["hotContents"][0]["publicUrl"] == complete_url
    assert persisted["hotContents"][0]["coverUrl"] == "https://cdn.example.test/trusted-cover.webp"
    metrics = persisted["hotContents"][0]["metrics"]
    assert metrics["likedCount"] == 12_000
    assert metrics["collectedCount"] == 3456
    assert metrics["commentCount"] == 78
    assert metrics["shareCount"] == 90
    assert metrics["engagementScore"] == 19_506
