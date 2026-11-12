import ast
from pathlib import Path

import pytest

from app.services.account_report.collection.owner_identity import parse_planned_owner_id


@pytest.mark.parametrize(
    ("platform", "url", "expected"),
    [
        ("xhs", "https://www.xiaohongshu.com/user/profile/xhs-owner?xsec_token=secret", "xhs-owner"),
        ("dy", "https://www.douyin.com/user/MS4wLjABAAAA-owner?from_tab_name=main", "MS4wLjABAAAA-owner"),
        ("ks", "https://www.kuaishou.com/profile/ks-owner", "ks-owner"),
    ],
)
def test_parse_planned_owner_id_supports_profile_paths_without_query(platform, url, expected):
    assert parse_planned_owner_id(platform, url) == expected


@pytest.mark.parametrize(
    ("platform", "url"),
    [
        ("xhs", "https://xhslink.com/short-code"),
        ("dy", "https://v.douyin.com/short-code"),
        ("ks", "https://v.kuaishou.com/short-code"),
        ("xhs", "https://www.xiaohongshu.com/explore/note-id"),
        ("dy", "javascript:alert(1)"),
        ("dy", "https://www.douyin.com/user/foo%2Fbar"),
        ("xhs", "https://www.xiaohongshu.com/user/profile/foo%20bar"),
        ("ks", "https://www.kuaishou.com/profile/foo%0Abar"),
    ],
)
def test_short_or_invalid_urls_do_not_claim_a_verified_owner(platform, url):
    assert parse_planned_owner_id(platform, url) is None


def test_owner_identity_parser_has_no_platform_runtime_imports():
    path = (
        Path(__file__).parents[1]
        / "app/services/account_report/collection/owner_identity.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ] + [
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    ]
    assert all("mediaspider.platforms" not in name for name in imports)


def test_account_report_workflow_has_no_platform_helper_imports():
    path = (
        Path(__file__).parents[1]
        / "app/services/account_report/workflows/report.py"
    )
    source = path.read_text(encoding="utf-8")
    assert "mediaspider.platforms" not in source
