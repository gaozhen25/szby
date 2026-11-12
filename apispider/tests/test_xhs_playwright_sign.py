import importlib
import inspect

import pytest

from app.services.mediaspider.platforms.xhs.playwright_sign import sign_with_xhshow
from xhshow.core.crypto import CryptoProcessor


def test_xhshow_010_post_signature_does_not_duplicate_sign_state():
    assert "hex_md5_path" in inspect.signature(CryptoProcessor.build_payload_array).parameters

    headers = sign_with_xhshow(
        "/api/sns/web/v1/search/notes",
        {"keyword": "探店", "page": 1},
        "a1=1234567890abcdef1234567890abcdef1234567890abcdef1234",
        method="POST",
    )

    assert {"x-s", "x-t", "x-s-common", "x-b3-traceid"} <= set(headers)
    assert headers["x-s"]


def test_xhshow_010_get_signature_supports_hex_md5_path():
    headers = sign_with_xhshow(
        "/api/sns/web/v1/search/notes",
        {"keyword": "探店", "page": 1},
        "a1=1234567890abcdef1234567890abcdef1234567890abcdef1234",
        method="GET",
    )

    assert {"x-s", "x-t", "x-s-common", "x-b3-traceid"} <= set(headers)
    assert headers["x-s"]


def test_xhshow_patch_is_idempotent():
    from app.services.mediaspider.platforms.xhs import playwright_sign

    before = CryptoProcessor.build_payload_array
    playwright_sign._patch_xhshow_a3_hash()
    assert CryptoProcessor.build_payload_array is before


def test_xhshow_patch_supports_legacy_signature(monkeypatch):
    from app.services.mediaspider.platforms.xhs import playwright_sign

    calls = []

    def legacy_build(self, hex_parameter, a1_value,
                     app_identifier="xhs-pc-web", string_param="",
                     timestamp=None, sign_state=None):
        calls.append((
            hex_parameter, a1_value, app_identifier,
            string_param, timestamp, sign_state,
        ))
        return [0] * 144

    monkeypatch.setattr(CryptoProcessor, "build_payload_array", legacy_build)
    playwright_sign._patch_xhshow_a3_hash()

    payload = CryptoProcessor.build_payload_array(
        object(), "hex", "a1", "app", "{body}", 1.5, "state",
    )

    assert len(payload) == 144
    assert calls == [("hex", "a1", "app", "{body}", 1.5, "state")]


def test_xhshow_patch_rejects_unknown_signature(monkeypatch):
    from app.services.mediaspider.platforms.xhs import playwright_sign

    def unsupported_build(self, hex_parameter):
        return []

    monkeypatch.setattr(CryptoProcessor, "build_payload_array", unsupported_build)

    with pytest.raises(
        RuntimeError,
        match="不支持的 xhshow build_payload_array 签名",
    ):
        playwright_sign._patch_xhshow_a3_hash()


def test_xhshow_patch_rejects_inserted_required_parameter(monkeypatch):
    from app.services.mediaspider.platforms.xhs import playwright_sign

    def unsupported_build(self, hex_parameter, required_value, a1_value,
                          app_identifier="xhs-pc-web", string_param="",
                          timestamp=None, sign_state=None):
        return []

    monkeypatch.setattr(CryptoProcessor, "build_payload_array", unsupported_build)

    with pytest.raises(
        RuntimeError,
        match="不支持的 xhshow build_payload_array 签名",
    ):
        playwright_sign._patch_xhshow_a3_hash()


def test_xhshow_patch_rejects_keyword_only_parameter(monkeypatch):
    from app.services.mediaspider.platforms.xhs import playwright_sign

    def unsupported_build(self, hex_parameter, a1_value,
                          app_identifier="xhs-pc-web", string_param="",
                          timestamp=None, *, sign_state=None):
        return []

    monkeypatch.setattr(CryptoProcessor, "build_payload_array", unsupported_build)

    with pytest.raises(
        RuntimeError,
        match="不支持的 xhshow build_payload_array 签名",
    ):
        playwright_sign._patch_xhshow_a3_hash()


def test_xhshow_import_defers_unknown_signature_failure_until_signing(monkeypatch):
    from app.services.mediaspider.platforms.xhs import playwright_sign

    def unsupported_build(self, hex_parameter, raw_signature_secret):
        return []

    try:
        with monkeypatch.context() as patch:
            patch.setattr(
                CryptoProcessor,
                "build_payload_array",
                unsupported_build,
            )

            module = importlib.reload(playwright_sign)

            with pytest.raises(
                RuntimeError,
                match="不支持的 xhshow build_payload_array 签名",
            ) as error:
                module.sign_with_xhshow(
                    "/api/sns/web/v1/search/notes",
                    {"keyword": "探店"},
                    "a1=fixed",
                    method="GET",
                )

            assert "raw_signature_secret" not in str(error.value)
    finally:
        importlib.reload(playwright_sign)
