import threading
import time

from app.services.mediaspider.http_platforms.xhs.client import XhsClient


def _note(index: int) -> dict:
    return {
        "note_id": f"note-{index}",
        "title": f"列表标题 {index}",
        "cover": f"http://sns-webpic-qc.xhscdn.com/list-{index}.webp",
        "xsec_token": f"token-{index}",
        "xsec_source": "pc_feed",
    }


def test_creator_enrichment_limits_detail_requests_and_keeps_all_list_items(
    monkeypatch,
):
    client = XhsClient(cookie="safe-cookie")
    active = 0
    maximum_active = 0
    called = []
    lock = threading.Lock()

    def fake_detail(note_id, xsec_token, xsec_source, *, session=None):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
            called.append(note_id)
        time.sleep(0.02)
        with lock:
            active -= 1
        index = note_id.rsplit("-", 1)[-1]
        return {
            "note_id": note_id,
            "title": f"详情标题 {index}",
            "cover": f"http://sns-webpic-qc.xhscdn.com/detail-{index}.webp",
            "xsec_token": xsec_token,
            "xsec_source": xsec_source,
        }

    monkeypatch.setattr(client, "get_note_by_id", fake_detail)

    contents = client.enrich_notes_with_detail(
        [_note(index) for index in range(4)],
        interval=0,
        detail_limit=2,
        max_concurrency=2,
    )

    assert set(called) == {"note-0", "note-1"}
    assert maximum_active == 2
    assert len(contents) == 4
    assert contents[0]["title"] == "详情标题 0"
    assert contents[1]["title"] == "详情标题 1"
    assert contents[2]["title"] == "列表标题 2"
    assert contents[2]["cover_url"] == (
        "https://sns-webpic-qc.xhscdn.com/list-2.webp"
    )


def test_creator_enrichment_keeps_list_item_without_access_token():
    client = XhsClient(cookie="safe-cookie")

    contents = client.enrich_notes_with_detail(
        [{
            "note_id": "note-without-token",
            "title": "列表仍应保留",
            "cover": "http://sns-webpic-qc.xhscdn.com/list.webp",
        }],
        interval=0,
        detail_limit=1,
        max_concurrency=2,
    )

    assert len(contents) == 1
    assert contents[0]["title"] == "列表仍应保留"


def test_creator_enrichment_uses_profile_token_and_preserves_list_metrics(
    monkeypatch,
):
    client = XhsClient(cookie="safe-cookie")
    called = []

    def fake_detail(note_id, xsec_token, xsec_source, *, session=None):
        called.append((note_id, xsec_token, xsec_source))
        return {
            "note_id": note_id,
            "title": "详情标题",
            "interact_info": {
                "liked_count": "120",
                "comment_count": None,
                "share_count": "",
            },
        }

    monkeypatch.setattr(client, "get_note_by_id", fake_detail)

    contents = client.enrich_notes_with_detail(
        [{
            "note_id": "note-with-profile-token",
            "title": "列表标题",
            "interact_info": {
                "liked_count": "100",
                "comment_count": "12",
                "share_count": "5",
            },
        }],
        default_xsec_token="profile-token",
        default_xsec_source="pc_feed",
        interval=0,
        detail_limit=1,
    )

    assert called == [
        ("note-with-profile-token", "profile-token", "pc_feed")
    ]
    assert contents[0]["title"] == "详情标题"
    assert contents[0]["liked_count"] == "120"
    assert contents[0]["comment_count"] == "12"
    assert contents[0]["share_count"] == "5"


def test_creator_enrichment_detail_session_inherits_proxies(monkeypatch):
    proxies = {"http": "http://u:p@1.2.3.4:8000", "https": "http://u:p@1.2.3.4:8000"}
    client = XhsClient(cookie="safe-cookie", proxies=proxies)
    seen = []

    def fake_detail(note_id, xsec_token, xsec_source, *, session=None):
        assert session is not None
        seen.append(dict(session.proxies))
        return {"note_id": note_id, "title": "详情"}

    monkeypatch.setattr(client, "get_note_by_id", fake_detail)
    client.enrich_notes_with_detail(
        [_note(0)],
        interval=0,
        detail_limit=1,
        max_concurrency=1,
    )
    assert seen == [proxies]
