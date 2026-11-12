from pathlib import Path

from message_adapter.platforms.host_client import discover_host_account


def test_wecom_login_requires_startup_success_in_qkzd_logs(tmp_path: Path):
    root = tmp_path / "qkzd" / "logs"
    root.mkdir(parents=True)
    (root / "client.log").write_text(
        '启动成功\n{"corp_id":"1","user_id":"1688","username":"教练"}\n',
        encoding="utf-8",
    )

    assert discover_host_account("wecom", roots=[tmp_path / "qkzd"]) == {
        "platform_actor_id": "1688",
        "nickname": "教练",
    }
    assert discover_host_account("wechat", roots=[tmp_path / "qkzd"]) is None


def test_wechat_log_is_not_treated_as_wecom(tmp_path: Path):
    root = tmp_path / "qkzd"
    root.mkdir()
    (root / "wechat.log").write_text(
        '个人微信\n启动成功\n{"user_id":"42","username":"小王"}\n',
        encoding="utf-8",
    )

    assert discover_host_account("wechat", roots=[root])["platform_actor_id"] == "42"
    assert discover_host_account("wecom", roots=[root]) is None
