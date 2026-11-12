"""Tests for Douyin IM media resolution."""

from __future__ import annotations

import base64

from boss_cli.douyin_web.im_media import (
    pick_im_image_url,
    remember_inline_pic,
    resolve_media_bytes,
    sniff_content_type,
    try_decrypt_image,
)
from boss_cli.douyin_web.payload import allowed_media_url


def test_allowed_media_url_douyinstatic():
    assert allowed_media_url("https://sf26-sign.douyinstatic.com/douyin-user-audio-file/a.mpeg")


def test_sniff_heic_is_image_not_audio():
    data = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00"
    assert sniff_content_type(data, "https://x/a.heic") == "image/heic"
    assert sniff_content_type(b"\x00\x00\x00\x1cftypM4A \x00\x00\x00\x00", "https://x/a.mpeg") == "audio/mp4"


def test_pick_im_image_url_prefers_large_variant():
    urls = [
        "https://p3-sign.douyinpic.com/foo~tplv-x-get:.image?x=1",
        "https://p3-sign.douyinpic.com/foo~tplv-x-get:large.image?x=1",
        "https://p3-sign.douyinpic.com/foo~tplv-x-get:thumb.image?x=1",
    ]
    picked = pick_im_image_url(urls)
    assert "large.image" in picked


def test_resolve_inline_webp_preview():
    webp = b"RIFF\x24\x00\x00\x00WEBPVP8 "
    inline = base64.b64encode(webp).decode()
    remember_inline_pic("mid-1", inline)
    out = resolve_media_bytes(b"", mid="mid-1")
    assert out is not None
    data, ctype = out
    assert data == webp
    assert ctype == "image/webp"


def test_try_decrypt_passthrough_jpeg():
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 20
    assert try_decrypt_image(jpeg, "") == jpeg
