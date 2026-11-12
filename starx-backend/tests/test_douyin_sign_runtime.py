from concurrent.futures import ThreadPoolExecutor
import threading

from app.services.mediaspider.http_platforms.douyin import help as douyin_help


def _reset_thread_local(monkeypatch):
    monkeypatch.setattr(douyin_help, "_THREAD_LOCAL", threading.local())


def test_douyin_sign_runtime_uses_in_process_quickjs(monkeypatch):
    _reset_thread_local(monkeypatch)
    calls = []

    class FakeFunction:
        def __call__(self, query, user_agent):
            calls.append(("call", query, user_agent))
            return "signed"

    class FakeContext:
        def eval(self, source):
            calls.append(("eval", source))

        def get(self, name):
            calls.append(("get", name))
            return FakeFunction()

    monkeypatch.setattr(douyin_help.quickjs, "Context", FakeContext)

    assert douyin_help.get_a_bogus("aid=6383", "Mozilla/5.0") == "signed"
    assert calls[0] == ("eval", douyin_help._JS_SOURCE)
    assert ("get", "sign_datail") in calls
    assert ("call", "aid=6383", "Mozilla/5.0") in calls


def test_douyin_sign_context_is_isolated_per_worker_thread(monkeypatch):
    _reset_thread_local(monkeypatch)
    created_on_threads = []

    class FakeFunction:
        def __call__(self, _query, _user_agent):
            return threading.get_ident()

    class FakeContext:
        def __init__(self):
            created_on_threads.append(threading.get_ident())

        def eval(self, _source):
            return None

        def get(self, _name):
            return FakeFunction()

    monkeypatch.setattr(douyin_help.quickjs, "Context", FakeContext)

    barrier = threading.Barrier(4)

    def sign(index):
        barrier.wait()
        return douyin_help.get_a_bogus(f"aid={index}", "Mozilla/5.0")

    with ThreadPoolExecutor(max_workers=4) as pool:
        result_threads = list(pool.map(sign, range(4)))

    assert len(set(result_threads)) == 4
    assert sorted(created_on_threads) == sorted(result_threads)
