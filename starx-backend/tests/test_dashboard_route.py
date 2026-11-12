from app.api.routes.dashboard import select_dashboard_platform


def test_dashboard_platform_falls_back_to_the_only_configured_platform():
    assert select_dashboard_platform("抖音", ["小红书"]) == "小红书"
    assert select_dashboard_platform("", ["小红书"]) == "小红书"


def test_dashboard_platform_preserves_an_available_explicit_selection():
    assert select_dashboard_platform("小红书", ["抖音", "小红书"]) == "小红书"
    assert select_dashboard_platform("抖音", ["抖音", "小红书"]) == "抖音"


def test_dashboard_platform_is_empty_when_no_social_account_is_configured():
    assert select_dashboard_platform("抖音", []) == ""
