from app.extract import (
    ExtractError,
    _best_image,
    _classify_video_bytes,
    _from_aweme,
    _select_xhs_video,
    _xhs_file_url,
    _xhs_video_candidates,
    as_mp4_start,
    detect,
    extract_urls,
    pick,
)
import pytest


def test_pick_douyin_paste():
    text = "复制打开抖音 https://v.douyin.com/iysEh9UH/ 直接观看"
    url, platform = pick(text)
    assert platform == "douyin"
    assert "douyin.com" in url


def test_pick_jingxuan_share_keeps_short_link():
    text = "3.51 K@j.pd 09/16 hBG:/ 天定鬼王 https://v.douyin.com/i66u1Y1a/ 复制此链接，打开Dou音搜索，直接观看视频！"
    url, platform = pick(text)
    assert platform == "douyin"
    assert url == "https://v.douyin.com/i66u1Y1a/"


def test_pick_ignores_zero_width_inside_url():
    url, platform = pick("https://v.douyin.com/\u200bi66u1Y1a/")
    assert platform == "douyin"
    assert url == "https://v.douyin.com/i66u1Y1a/"


def test_command_without_short_link():
    text = "3.53 ytr:/ f@b.aA 03/31 :9pm 【抖音精选App独家】复制此链接，打开Dou音搜索，直接观看视频！"
    with pytest.raises(ExtractError, match="没有 v.douyin.com"):
        pick(text)


def test_pick_xhs_fullwidth():
    text = "笔记 http://xhslink.com/a/HFNEzlEk7tP3，复制本条信息"
    urls = extract_urls(text)
    assert urls[0] == "http://xhslink.com/a/HFNEzlEk7tP3"
    assert detect(urls[0]) == "xhs"


def test_reject_other():
    with pytest.raises(ExtractError):
        pick("https://example.com/a")


def test_xhs_file_id_drops_style_suffix():
    url = _xhs_file_url({
        "fileId": "notes_pre_post/abc123",
        "url": "http://sns-webpic-qc.xhscdn.com/notes_pre_post/abc123!h5_1080jpg",
    })
    assert url == "https://sns-img-qc.xhscdn.com/notes_pre_post/abc123"


def test_douyin_image_skips_watermark_template():
    picked = _best_image([
        "https://p.douyinpic.com/a~tplv-dy-water-v2:x.jpeg",
        "https://p.douyinpic.com/a~tplv-dy-aweme-images:q75.webp",
        "https://p.douyinpic.com/a~tplv-dy-aweme-images:q75.jpeg",
    ])
    assert picked.endswith("q75.jpeg")
    assert "water" not in picked


def test_xhs_video_keeps_origin_even_when_mov():
    note = {
        "video": {
            "consumer": {"originVideoKey": "pre_post/origin"},
            "media": {"stream": {
                "h265": [{"masterUrl": "https://sns-video-bd.xhscdn.com/a.m3u8", "size": 9}],
                "h264": [{"masterUrl": "http://sns-video-bd.xhscdn.com/play.mp4", "size": 3}],
            }},
        }
    }
    candidates = _xhs_video_candidates(note)
    assert [label for label, _ in candidates] == ["origin", "h264"]
    assert candidates[1][1].startswith("https://")
    assert _select_xhs_video(candidates, ["mov", "mp4"]).endswith("/pre_post/origin")
    assert _select_xhs_video(candidates, ["mp4", "mp4"]).endswith("/pre_post/origin")
    assert _select_xhs_video(candidates, ["hls", "mp4"]).endswith("play.mp4")
    rewritten = as_mp4_start(b"\x00\x00\x00\x14ftypqt  rest")
    assert rewritten[8:12] == b"mp42"
    assert as_mp4_start(b"\x00\x00\x00\x18ftypisom")[8:12] == b"isom"


def test_classify_mp4_mov_hls():
    assert _classify_video_bytes(b"\x00\x00\x00\x18ftypisom", "", "") == "mp4"
    assert _classify_video_bytes(b"\x00\x00\x00\x14ftypqt  ", "", "") == "mov"
    assert _classify_video_bytes(b"#EXTM3U\n", "", "https://cdn/a.m3u8") == "hls"


def test_douyin_note_is_images_not_video():
    got = _from_aweme(
        {
            "aweme_id": "1",
            "desc": "图文 #标签",
            "author": {"nickname": "甲"},
            "images": [{
                "url_list": ["https://p.douyinpic.com/a~tplv-dy-aweme-images:q75.jpeg"],
                "download_url_list": ["https://p.douyinpic.com/a~tplv-dy-water-v2:x.jpeg"],
            }],
            "video": {"play_addr": {"uri": "https://example.douyin.com/not-a-video"}},
        },
        "1",
        "https://v.douyin.com/x",
        "https://www.douyin.com/note/1",
        "share.page",
    )
    assert got.kind == "image"
    assert len(got.medias) == 1
    assert got.medias[0].cover == got.medias[0].url
    assert "tplv-dy-water" not in got.medias[0].url
    assert got.tags == ["标签"]
    assert got.comments == []
    assert got.comment_count is None


def test_public_comments_are_kept():
    from app.extract import Comment

    got = _from_aweme(
        {
            "aweme_id": "1",
            "desc": "图文",
            "author": {"nickname": "甲"},
            "statistics": {"comment_count": "3"},
            "comment_list": [{"text": "好看", "user": {"nickname": "乙"}}],
            "images": [{"url_list": ["https://p.douyinpic.com/a.jpeg"]}],
        },
        "1",
        "https://v.douyin.com/x",
        "https://www.douyin.com/note/1",
        "share.page",
    )
    assert got.comment_count == 3
    assert got.comments == [Comment("乙", "好看")]
