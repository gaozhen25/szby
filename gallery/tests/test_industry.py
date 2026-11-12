from app.industry import _clean_label, classify_industry


def test_clean_label_keeps_short_industry_name():
    assert _clean_label("美妆") == "美妆"
    assert _clean_label("「健身」") == "健身"
    assert _clean_label("其他") == "其他"
    assert _clean_label("") == ""


def test_classify_uses_ark_response(monkeypatch):
    monkeypatch.setenv("ARK_API_KEY", "test-key")

    class Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"output": [{"content": [{"type": "output_text", "text": "健身"}]}]}

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def post(self, url, headers=None, json=None):
            assert "Bearer test-key" in headers["Authorization"]
            assert json["model"]
            assert "标题" in json["input"][0]["content"][0]["text"]
            return Resp()

    monkeypatch.setattr("app.industry.httpx.Client", Client)
    assert classify_industry("滑雪教学", ["滑雪", "运动"], "冬天去阿勒泰") == "健身"


def test_classify_skips_without_key(monkeypatch):
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    assert classify_industry("标题", ["标签"]) == ""


def test_parse_stores_industry(tmp_path, monkeypatch):
    monkeypatch.setattr("app.industry.classify_industry", lambda *args, **kwargs: "美妆")
    from tests.test_library import client_for, HEADERS

    client, _store = client_for(tmp_path, monkeypatch)
    res = client.post("/api/v1/parse", headers=HEADERS, json={"texts": ["https://v.douyin.com/industry"], "download": False})
    assert res.status_code == 200
    source = res.json()["results"][0]["source"]
    assert source["industry"] == "美妆"
    listed = client.get("/api/v1/library", headers=HEADERS, params={"industry": "美妆", "group": "source"})
    assert listed.json()["total"] == 1
