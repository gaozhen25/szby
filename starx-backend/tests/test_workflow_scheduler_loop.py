import asyncio

from app.services.workflow.scheduler import WorkflowScheduler


def test_scheduler_uses_one_dedicated_loop_from_sync_and_async_callers():
    scheduler = WorkflowScheduler(use_default_concurrency=False)
    sync_loop = scheduler._get_or_create_loop()

    async def inspect_from_async_context():
        caller_loop = asyncio.get_running_loop()
        return caller_loop, scheduler._get_or_create_loop()

    caller_loop, async_scheduler_loop = asyncio.run(inspect_from_async_context())
    assert sync_loop is async_scheduler_loop
    assert async_scheduler_loop is not caller_loop
    assert async_scheduler_loop.is_running()

    asyncio.run(scheduler.shutdown(timeout_seconds=2))

    assert scheduler._loop is None
    assert scheduler._loop_thread is None
    try:
        scheduler.submit("unknown", "wf_after_shutdown")
    except RuntimeError as exc:
        assert "shutting down" in str(exc)
    else:
        raise AssertionError("shutdown scheduler accepted new work")

    scheduler.start()
    restarted_loop = scheduler._get_or_create_loop()
    assert restarted_loop.is_running()
    asyncio.run(scheduler.shutdown(timeout_seconds=2))
