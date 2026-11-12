from app.services.account_report.crawl_options import account_report_runtime_options


class StubRuntimeSettings:
    def __init__(
        self,
        global_limit: int,
        report_limit: int = 10,
        *,
        enable_sub_comments: bool = True,
        enable_cdp_mode: bool = False,
        cdp_connect_existing: bool = False,
        cdp_debug_port: int = 9222,
    ) -> None:
        self.global_limit = global_limit
        self.ACCOUNT_REPORT_MAX_NOTES_PER_KEYWORD = report_limit
        self.enable_sub_comments = enable_sub_comments
        self.enable_cdp_mode = enable_cdp_mode
        self.cdp_connect_existing = cdp_connect_existing
        self.cdp_debug_port = cdp_debug_port

    def mediaspider_runtime_options(self, platform: str) -> dict[str, object]:
        return {
            "cookies": f"{platform}-sentinel",
            "max_notes_count": self.global_limit,
            "max_comments_count": 20,
            "max_concurrency": 3,
            "enable_comments": True,
            "enable_sub_comments": self.enable_sub_comments,
            "enable_cdp_mode": self.enable_cdp_mode,
            "cdp_connect_existing": self.cdp_connect_existing,
            "cdp_debug_port": self.cdp_debug_port,
        }


def test_account_report_caps_global_note_limit_at_report_limit():
    options = account_report_runtime_options(StubRuntimeSettings(30), "xhs")

    assert options["max_notes_count"] == 10
    assert options["max_comments_count"] == 20
    assert options["max_concurrency"] == 3


def test_account_report_preserves_lower_global_note_limit():
    options = account_report_runtime_options(StubRuntimeSettings(6), "dy")

    assert options["max_notes_count"] == 6


def test_account_report_returns_a_copy_of_global_options():
    configured = StubRuntimeSettings(30)
    original = configured.mediaspider_runtime_options("xhs")

    options = account_report_runtime_options(configured, "xhs")

    assert options is not original
    assert original["max_notes_count"] == 30


def test_account_report_disables_comments_by_default():
    options = account_report_runtime_options(StubRuntimeSettings(30), "xhs")

    assert options["enable_comments"] is False
    assert options["enable_sub_comments"] is False


def test_account_report_enables_comments_explicitly_and_preserves_sub_comment_limit():
    options = account_report_runtime_options(
        StubRuntimeSettings(30),
        "xhs",
        reference_comments=True,
    )

    assert options["enable_comments"] is True
    assert options["enable_sub_comments"] is True

    without_sub_comments = account_report_runtime_options(
        StubRuntimeSettings(30, enable_sub_comments=False),
        "xhs",
        reference_comments=True,
    )
    assert without_sub_comments["enable_comments"] is True
    assert without_sub_comments["enable_sub_comments"] is False


def test_account_report_isolates_launched_cdp_ports_by_platform():
    settings = StubRuntimeSettings(30, enable_cdp_mode=True, cdp_debug_port=9333)

    ports = {
        platform: account_report_runtime_options(settings, platform)["cdp_debug_port"]
        for platform in ("xhs", "dy", "ks")
    }

    assert ports == {"xhs": 9333, "dy": 9334, "ks": 9335}


def test_account_report_preserves_existing_browser_cdp_port():
    settings = StubRuntimeSettings(
        30,
        enable_cdp_mode=True,
        cdp_connect_existing=True,
        cdp_debug_port=9333,
    )

    assert account_report_runtime_options(settings, "dy")["cdp_debug_port"] == 9333
