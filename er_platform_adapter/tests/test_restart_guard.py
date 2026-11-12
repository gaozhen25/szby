from message_adapter.restart_guard import guard_process_args, should_restart


def test_any_exit_restarts():
    assert should_restart(0) is True
    assert should_restart(1) is True


def test_guard_command_watches_the_connector_pid():
    assert guard_process_args(r"C:\adapter\adapter.exe", 42) == [
        r"C:\adapter\adapter.exe",
        "_restart-guard",
        "--pid",
        "42",
    ]
