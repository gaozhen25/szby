import hashlib

import httpx
import pytest
from fastapi.testclient import TestClient

from app.extract import ExtractError, Extracted, Media
from app.fetch import SaveError, save_remote
from app.main import create_app
from app.oss import MemoryStore, OssStore, StoreError, plain_store_error

KEY = "test-key"
HEADERS = {"X-Api-Key": KEY}


def fake_extract(text: str) -> Extracted:
    if "拒绝" in text:
        raise ExtractError("unsupported_link", "只支持抖音和小红书分享链接")
    cid = "same" if "same" in text else hashlib.sha1(text.encode()).hexdigest()[:12]
    platform = "xhs" if "xhs" in text else "douyin"
    if "video" in text:
        medias = [Media("video", f"https://v.douyinvod.com/{cid}.mp4", quality="原片", ext="mp4", no_watermark=True)]
        cover = f"https://p.douyinpic.com/{cid}-cover.jpeg"
        kind = "video"
    else:
        if "拆开" in text:
            medias = [
                Media("image", f"https://p.douyinpic.com/{cid}-1.jpeg", quality="原图", ext="jpg", no_watermark=True, cover=f"https://p.douyinpic.com/{cid}-1.jpeg"),
                Media("image", f"https://p.douyinpic.com/{cid}-2.jpeg", quality="原图", ext="jpg", no_watermark=True, cover=f"https://p.douyinpic.com/{cid}-2.jpeg"),
            ]
            cover = medias[0].url
        else:
            url = f"https://p.douyinpic.com/{cid}.jpeg"
            medias = [Media("image", url, quality="原图", ext="jpg", no_watermark=True, cover=url)]
            cover = url
        kind = "image"
    return Extracted(
        platform=platform,
        content_id=cid,
        source_url=f"https://v.douyin.com/{cid}/",
        canonical_url=f"https://www.douyin.com/video/{cid}",
        title=f"标题{cid}",
        content=f"正文 {text[:24]}",
        author="作者",
        cover=cover,
        tags=["旅行"],
        kind=kind,
        medias=medias,
        via="test",
    )


def fake_receive(url, *, want_mp4, max_bytes):
    return b"\x00\x00\x00\x14ftypqt  hello" if want_mp4 else b"jpeg-bytes"


def client_for(tmp_path, monkeypatch, receive=fake_receive):
    monkeypatch.setattr("app.intake.extract", fake_extract)
    store = MemoryStore(receive=receive)
    return TestClient(create_app(tmp_path, api_key=KEY, store=store)), store


def test_batch_saves_and_library_roundtrip(tmp_path, monkeypatch):
    client, store = client_for(tmp_path, monkeypatch)
    res = client.post(
        "/api/v1/parse",
        headers=HEADERS,
        json={"texts": ["https://v.douyin.com/one", "这是一条拒绝的链接", "xhs https://xhslink.com/two"]},
    )
    body = res.json()
    assert res.status_code == 200
    assert body["saved"] == 2
    assert body["failed"] == 1
    assert body["results"][1]["error"]["code"] == "unsupported_link"
    item = body["results"][0]
    asset = item["assets"][0]
    assert item["created"] is True
    assert asset["saved"] is True
    assert asset["type"] == "image"
    assert asset["href"].endswith("/file")
    assert "正文" in asset["source"]["content"]
    assert store.objects[asset["oss_key"]] == b"jpeg-bytes"

    by_tag = client.get("/api/v1/library", headers=HEADERS, params={"q": "旅行"})
    assert by_tag.json()["total"] == 2
    assert {item["source"]["platform"] for item in by_tag.json()["items"]} == {"douyin", "xhs"}

    listed = client.get("/api/v1/library", headers=HEADERS, params={"platform": "douyin", "tag": "旅行", "q": "标题"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == asset["id"]

    xhs = client.get("/api/v1/library", headers=HEADERS, params={"platform": "xhs", "type": "image"})
    assert xhs.json()["total"] == 1

    fetched = client.get(f"/api/v1/library/{asset['id']}", headers={"Authorization": f"Bearer {KEY}"})
    assert fetched.json()["item"]["source"]["content_id"] == asset["source"]["content_id"]

    downloaded = client.get(asset["href"], headers=HEADERS)
    assert downloaded.status_code == 200
    assert downloaded.content == b"jpeg-bytes"
    assert downloaded.headers["content-type"].startswith("image/jpeg")


def test_upsert_keeps_note_and_failed_refresh(tmp_path, monkeypatch):
    calls = {"n": 0}

    def flaky(url, *, want_mp4, max_bytes):
        calls["n"] += 1
        if calls["n"] > 1:
            raise SaveError("upstream 500")
        return fake_receive(url, want_mp4=want_mp4, max_bytes=max_bytes)

    client, store = client_for(tmp_path, monkeypatch, receive=flaky)
    first = client.post("/api/v1/parse", headers=HEADERS, json={"texts": ["same one"]}).json()
    asset_id = first["results"][0]["assets"][0]["id"]
    patched = client.patch(
        f"/api/v1/library/{asset_id}",
        headers=HEADERS,
        json={"note": "留给后期", "labels": ["已选", "已选", "  "], "category": "人物"},
    )
    assert patched.json()["item"]["labels"] == ["已选"]
    assert patched.json()["item"]["category"] == "人物"

    second = client.post(
        "/api/v1/parse",
        headers=HEADERS,
        json={"texts": ["same two"], "refresh_files": True},
    ).json()
    again = second["results"][0]
    assert again["created"] is False
    assert again["assets"][0]["id"] == asset_id
    assert again["assets"][0]["note"] == "留给后期"
    assert again["assets"][0]["labels"] == ["已选"]
    assert again["assets"][0]["category"] == "人物"
    assert again["assets"][0]["saved"] is True
    assert again["assets"][0]["error"] == "upstream 500"

    gone = client.delete(f"/api/v1/library/{asset_id}", headers=HEADERS)
    assert gone.json()["ok"] is True
    assert client.get(f"/api/v1/library/{asset_id}", headers=HEADERS).status_code == 404
    assert store.objects == {}


def test_page_parse_does_not_save_and_auth_is_required(tmp_path, monkeypatch):
    client, _store = client_for(tmp_path, monkeypatch)
    page = client.post("/api/parse", json={"text": "https://v.douyin.com/page"})
    assert page.status_code == 200
    assert client.get("/api/v1/library", headers=HEADERS).json()["total"] == 0
    denied = client.post("/api/v1/parse", json={"texts": ["https://v.douyin.com/x"]})
    assert denied.status_code == 401


def test_download_false_and_batch_limits(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("should not download")

    client, _store = client_for(tmp_path, monkeypatch, receive=boom)
    skipped = client.post(
        "/api/v1/parse",
        headers=HEADERS,
        json={"texts": ["https://v.douyin.com/meta"], "download": False},
    )
    assert skipped.status_code == 200
    assert skipped.json()["results"][0]["assets"][0]["saved"] is False

    one_paste = client.post(
        "/api/v1/parse",
        headers=HEADERS,
        json={"text": "复制打开抖音\nhttps://v.douyin.com/only-one 观看", "download": False},
    )
    assert one_paste.json()["total"] == 1

    many = client.post(
        "/api/v1/parse",
        headers=HEADERS,
        json={"text": "\n".join(f"https://v.douyin.com/{i}" for i in range(21)), "download": False},
    )
    assert many.status_code == 422
    assert many.json()["detail"]["code"] == "too_many"
    assert client.post("/api/v1/parse", headers=HEADERS, json={}).status_code == 422


def test_reported_counts_stay_with_the_parsed_share(tmp_path, monkeypatch):
    client, _store = client_for(tmp_path, monkeypatch)
    res = client.post(
        "/api/v1/parse",
        headers=HEADERS,
        json={
            "items": [
                {
                    "text": "https://v.douyin.com/reported",
                    "likedCount": 12,
                    "收藏": 4,
                    "play_count": 90,
                }
            ],
            "download": False,
        },
    )
    assert res.status_code == 200
    source = res.json()["results"][0]["source"]
    assert source["like_count"] == 12
    assert source["collect_count"] == 4
    assert source["reported"]["play_count"] == 90
    again = client.post(
        "/api/v1/parse",
        headers=HEADERS,
        json={"texts": ["https://v.douyin.com/reported"], "download": False},
    )
    kept = again.json()["results"][0]["source"]
    assert kept["like_count"] == 12
    assert kept["collect_count"] == 4
    assert kept["reported"]["play_count"] == 90


def test_caller_record_is_stored_with_the_share(tmp_path, monkeypatch):
    client, _store = client_for(tmp_path, monkeypatch)
    record = {
        "index": 1,
        "platform": "douyin",
        "title": "生命随年月流去",
        "author": "花花",
        "zanCount": 1649000,
        "commentCount": 12000,
        "comments": [
            {"nickname": "田空题", "content": "不收徒！谢谢", "zanCount": 8198, "isZan": False, "isAuthor": False, "ip": "福建"}
        ],
        "liked": False,
        "shareLink": "https://v.douyin.com/reported-record",
        "collectedAt": 1793328490129,
    }
    res = client.post("/api/v1/parse", headers=HEADERS, json=record)
    assert res.status_code == 200
    source = res.json()["results"][0]["source"]
    assert source["like_count"] == 1649000
    assert source["comment_count"] == 12000
    assert source["comments"][0]["author"] == "田空题"
    assert source["comments"][0]["text"] == "不收徒！谢谢"
    assert source["comments"][0]["zanCount"] == 8198
    assert source["comments"][0]["ip"] == "福建"
    assert source["reported"]["liked"] is False
    assert source["reported"]["collectedAt"] == 1793328490129
    assert source["reported"]["author"] == "花花"
    batch = client.post("/api/v1/parse", headers=HEADERS, json=[record, {**record, "shareLink": "https://v.douyin.com/second-record", "index": 2}])
    assert batch.status_code == 200
    assert batch.json()["saved"] == 2


def test_one_post_is_stored_as_separate_assets(tmp_path, monkeypatch):
    client, store = client_for(tmp_path, monkeypatch)
    res = client.post("/api/v1/parse", headers=HEADERS, json={"texts": ["拆开的图文"]})
    body = res.json()["results"][0]
    assert res.status_code == 200
    assert len(body["assets"]) == 2
    assert body["assets"][0]["source"]["id"] == body["assets"][1]["source"]["id"]
    assert body["assets"][0]["id"] != body["assets"][1]["id"]
    assert {item["ordinal"] for item in body["assets"]} == {0, 1}
    listed = client.get("/api/v1/library", headers=HEADERS, params={"source_id": body["source"]["id"]})
    assert listed.json()["total"] == 2
    assert len(store.objects) == 2
    client.post("/api/v1/parse", headers=HEADERS, json={"texts": ["另一条"]})
    grouped = client.get("/api/v1/library", headers=HEADERS, params={"group": "source", "q": "正文"})
    works = grouped.json()
    assert works["grouped"] == "source"
    assert works["total"] == 2
    assert works["asset_total"] == 3
    assert sorted(len(item["assets"]) for item in works["items"]) == [1, 2]
    flat = client.get("/api/v1/library", headers=HEADERS, params={"q": "正文"})
    assert flat.json()["total"] == 3
    assert "grouped" not in flat.json()


def test_oss_put_remote_streams_without_temp_file(monkeypatch, tmp_path):
    import app.fetch as fetch_mod

    monkeypatch.setattr(fetch_mod, "_http", None)
    monkeypatch.setenv("OSS_ACCESS_KEY_ID", "test-id")
    monkeypatch.setenv("OSS_ACCESS_KEY_SECRET", "test-secret")
    monkeypatch.setenv("OSS_BUCKET", "szby")
    monkeypatch.setenv("OSS_REGION", "cn-hangzhou")
    monkeypatch.setenv("OSS_ENDPOINT", "https://oss-cn-hangzhou.aliyuncs.com")
    monkeypatch.setenv("OSS_UPLOAD_DIR", "gallery")
    monkeypatch.setenv("OSS_USE_CNAME", "false")
    store = OssStore.from_env()
    assert store is not None
    captured: dict[str, object] = {}

    class Resp:
        status_code = 200
        url = "https://v.douyinvod.com/clip.mp4"
        headers = {"content-length": "16"}

        def iter_bytes(self, chunk_size=None):
            yield b"\x00\x00\x00\x14ftypqt  rest"

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    class Client:
        def __init__(self, **_k):
            pass

        def stream(self, method, url, headers=None):
            return Resp()

    class FakeAuth:
        def __init__(self, access_key, secret):
            pass

    class FakeBucket:
        def __init__(self, auth, endpoint, bucket, region=None, is_cname=False):
            pass

        def put_object(self, object_key, data, headers=None):
            captured["key"] = object_key
            captured["body"] = data.read()
            captured["len"] = getattr(data, "len", None)
            captured["content_type"] = (headers or {}).get("Content-Type")

    import sys
    import types

    fake = types.ModuleType("oss2")
    fake.Auth = FakeAuth
    fake.Bucket = FakeBucket
    monkeypatch.setitem(sys.modules, "oss2", fake)
    monkeypatch.setattr(httpx, "Client", Client)
    nbytes = store.put_remote("gallery/v/0.mp4", "https://v.douyinvod.com/clip.mp4", want_mp4=True, max_bytes=1000)
    assert nbytes == 16
    assert captured["body"][8:12] == b"mp42"
    assert captured["len"] == 16
    assert captured["content_type"] == "video/mp4"


def test_private_bucket_uses_official_endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("OSS_ACCESS_KEY_ID", "test-id")
    monkeypatch.setenv("OSS_ACCESS_KEY_SECRET", "test-secret")
    monkeypatch.setenv("OSS_BUCKET", "szby")
    monkeypatch.setenv("OSS_REGION", "cn-hangzhou")
    monkeypatch.setenv("OSS_ENDPOINT", "https://oss.humanlike.life")
    monkeypatch.setenv("OSS_UPLOAD_DIR", "gallery")
    monkeypatch.setenv("OSS_USE_CNAME", "true")
    store = OssStore.from_env()
    assert store is not None
    key = store.object_key("abc", 0, "jpg")
    assert key == "gallery/abc/0.jpg"
    assert store.api_endpoint == "https://oss-cn-hangzhou.aliyuncs.com"
    assert store.client_cname is False
    assert store.api_host == "szby.oss-cn-hangzhou.aliyuncs.com"

    captured: dict[str, object] = {}

    class FakeAuth:
        def __init__(self, access_key, secret):
            captured["access_key"] = access_key

    class FakeBucket:
        def __init__(self, auth, endpoint, bucket, region=None, is_cname=False):
            captured["endpoint"] = endpoint
            captured["bucket"] = bucket
            captured["region"] = region
            captured["is_cname"] = is_cname

        def put_object(self, object_key, data, headers=None):
            captured["key"] = object_key
            captured["content_type"] = (headers or {}).get("Content-Type")
            captured["body"] = data.read()
            if captured.get("deny"):
                raise RuntimeError("AccessDenied You have no right to access this object because of bucket acl")

    import sys
    import types

    fake = types.ModuleType("oss2")
    fake.Auth = FakeAuth
    fake.Bucket = FakeBucket
    monkeypatch.setitem(sys.modules, "oss2", fake)
    sample = tmp_path / "a.jpg"
    sample.write_bytes(b"jpeg")
    store.put_file(key, sample, "image/jpeg")
    assert captured["endpoint"] == "https://oss-cn-hangzhou.aliyuncs.com"
    assert captured["bucket"] == "szby"
    assert captured["is_cname"] is False
    assert captured["key"] == key
    assert captured["content_type"] == "image/jpeg"
    assert captured["body"] == b"jpeg"

    captured["deny"] = True
    store._bucket = None
    with pytest.raises(StoreError, match="不是这个桶的主人"):
        store.put_file(key, sample, "image/jpeg")
    assert "AccessDenied" not in plain_store_error("AccessDenied bucket acl")


def test_save_remote_rejects_host_and_rewrites_mov(tmp_path, monkeypatch):
    import app.fetch as fetch_mod

    monkeypatch.setattr(fetch_mod, "_http", None)
    with pytest.raises(SaveError):
        save_remote("https://example.com/a.jpg", tmp_path / "a.jpg", want_mp4=False, max_bytes=1000)

    class Resp:
        status_code = 200
        url = "https://v.douyinvod.com/a.mp4"
        headers = {}

        def raise_for_status(self):
            return None

        def iter_bytes(self, chunk_size=None):
            yield b"\x00\x00\x00\x14ftypqt  rest"

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    class Client:
        def __init__(self, **_k):
            pass

        def stream(self, method, url, headers=None):
            return Resp()

    monkeypatch.setattr(httpx, "Client", Client)
    dest = tmp_path / "a.mp4"
    size = save_remote("https://v.douyinvod.com/a.mp4", dest, want_mp4=True, max_bytes=1000)
    assert dest.read_bytes()[8:12] == b"mp42"
    assert size == dest.stat().st_size


def test_admin_login_uses_username_and_password(tmp_path, monkeypatch):
    monkeypatch.setenv("GALLERY_ADMIN_USER", "admin")
    monkeypatch.setenv("GALLERY_ADMIN_PASSWORD", "secret-pass")
    client, _store = client_for(tmp_path, monkeypatch)
    bad = client.post("/api/admin/login", json={"username": "admin", "password": "nope"})
    assert bad.status_code == 401
    ok = client.post("/api/admin/login", json={"username": "admin", "password": "secret-pass"})
    assert ok.status_code == 200
    me = client.get("/api/admin/me")
    assert me.status_code == 200
