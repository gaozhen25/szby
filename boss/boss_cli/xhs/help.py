# -*- coding: utf-8 -*-
"""
小红书新版签名（XYS_ + x-s-common）

依赖开源库 xhshow（MIT）: https://github.com/Cloxl/xhshow
GET a3 修复同 MediaCrawler（xhshow issue #104）
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Union
from urllib.parse import quote

_XHSHOW_LEGACY = (
    "self",
    "hex_parameter",
    "a1_value",
    "app_identifier",
    "string_param",
    "timestamp",
    "sign_state",
)
_XHSHOW_HEX_MD5 = (
    "self",
    "hex_parameter",
    "hex_md5_path",
    "a1_value",
    "app_identifier",
    "string_param",
    "timestamp",
    "sign_state",
)


def _repair_get_a3(payload, processor, string_param: str):
    if "{" in string_param:
        return payload
    correct_md5_hex = hashlib.md5(string_param.encode("utf-8")).hexdigest()
    correct_md5_bytes = [int(correct_md5_hex[i : i + 2], 16) for i in range(0, 32, 2)]
    seed_byte = payload[4]
    ts_bytes = payload[8:16]
    correct_a3_hash = processor._custom_hash_v2(list(ts_bytes) + correct_md5_bytes)
    for i in range(16):
        payload[128 + i] = correct_a3_hash[i] ^ seed_byte
    return payload


def _patch_xhshow_a3_hash() -> None:
    from xhshow.core.crypto import CryptoProcessor

    current = CryptoProcessor.build_payload_array
    if getattr(current, "__js_reverse_a3_patch__", False):
        return

    names = tuple(inspect.signature(current).parameters)
    if names == _XHSHOW_HEX_MD5:

        def patched(
            self,
            hex_parameter,
            hex_md5_path,
            a1_value,
            app_identifier="xhs-pc-web",
            string_param="",
            timestamp=None,
            sign_state=None,
        ):
            payload = current(
                self,
                hex_parameter,
                hex_md5_path,
                a1_value,
                app_identifier,
                string_param,
                timestamp,
                sign_state,
            )
            return _repair_get_a3(payload, self, string_param)

    elif names == _XHSHOW_LEGACY:

        def patched(
            self,
            hex_parameter,
            a1_value,
            app_identifier="xhs-pc-web",
            string_param="",
            timestamp=None,
            sign_state=None,
        ):
            payload = current(
                self,
                hex_parameter,
                a1_value,
                app_identifier,
                string_param,
                timestamp,
                sign_state,
            )
            return _repair_get_a3(payload, self, string_param)

    else:
        raise RuntimeError(f"不支持的 xhshow build_payload_array 签名: {names}")

    patched.__js_reverse_a3_patch__ = True
    CryptoProcessor.build_payload_array = patched


def build_sign_string(
    uri: str, data: Optional[Union[Dict, str]] = None, method: str = "GET"
) -> str:
    if method.upper() == "POST":
        c = uri
        if data is not None:
            if isinstance(data, dict):
                c += json.dumps(data, separators=(",", ":"), ensure_ascii=False)
            else:
                c += data
        return c
    if not data or (isinstance(data, dict) and not data):
        return uri
    if isinstance(data, dict):
        params = []
        for key, value in data.items():
            if isinstance(value, list):
                value_str = ",".join(str(v) for v in value)
            elif value is not None:
                value_str = str(value)
            else:
                value_str = ""
            params.append(f"{key}={quote(value_str, safe=',')}")
        return f"{uri}?{'&'.join(params)}"
    if isinstance(data, str):
        return f"{uri}?{data}"
    return uri


def sign_headers(
    uri: str,
    cookie_str: str,
    data: Optional[Union[Dict, str]] = None,
    method: str = "GET",
) -> Dict[str, Any]:
    """生成 x-s / x-t / x-s-common / x-b3-traceid"""
    _patch_xhshow_a3_hash()
    from xhshow import Xhshow

    client = Xhshow()
    if method.upper() == "POST":
        headers = client.sign_headers_post(
            uri=uri,
            cookies=cookie_str,
            payload=data if isinstance(data, dict) else {},
        )
        return {
            "x-s": headers.get("x-s", ""),
            "x-t": str(headers.get("x-t", "")),
            "x-s-common": headers.get("x-s-common", ""),
            "x-b3-traceid": headers.get("x-b3-traceid", ""),
        }

    content_string = build_sign_string(uri, data, method)
    cookie_dict = client._parse_cookies(cookie_str)
    a1_value = cookie_dict.get("a1", "")
    ts = time.time()
    d_value = hashlib.md5(content_string.encode("utf-8")).hexdigest()

    builder = client.crypto_processor.build_payload_array
    kwargs = {
        "hex_parameter": d_value,
        "a1_value": a1_value,
        "app_identifier": "xhs-pc-web",
        "string_param": content_string,
        "timestamp": ts,
    }
    if "hex_md5_path" in inspect.signature(builder).parameters:
        kwargs["hex_md5_path"] = d_value
    payload_array = builder(**kwargs)
    xor_result = client.crypto_processor.bit_ops.xor_transform_array(payload_array)
    config = client.config
    x3_b64 = client.crypto_processor.b64encoder.encode_x3(
        xor_result[: config.PAYLOAD_LENGTH]
    )
    sig_data = config.SIGNATURE_DATA_TEMPLATE.copy()
    sig_data["x3"] = config.X3_PREFIX + x3_b64
    x_s = config.XYS_PREFIX + client.crypto_processor.b64encoder.encode(
        json.dumps(sig_data, separators=(",", ":"), ensure_ascii=False)
    )
    return {
        "x-s": x_s,
        "x-s-common": client.sign_xs_common(cookie_dict),
        "x-t": str(client.get_x_t(ts)),
        "x-b3-traceid": client.get_b3_trace_id(),
    }


def _resolve_cookie_path(cookie_file: str) -> Optional[str]:
    """按优先级查找 cookie 文件：传入路径 / cookies/ / 项目根 / cwd。"""
    candidates = [cookie_file]
    name = Path(cookie_file).name
    root = Path(__file__).resolve().parents[2]
    candidates.extend(
        [
            str(root / "cookies" / name),
            str(root / name),
            str(Path.cwd() / "cookies" / name),
            str(Path.cwd() / name),
        ]
    )
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def load_cookie(cookie_file: str = "xhs_cookie.txt") -> str:
    """优先读项目 xhs/cookies.json / 环境变量 / 旧版 txt。"""
    from .credentials import load_xhs_cookie

    # 显式传入旧路径时仍支持
    if cookie_file and cookie_file != "xhs_cookie.txt":
        path = _resolve_cookie_path(cookie_file)
        if path:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read().strip()
            if text.startswith("{"):
                import json as _json

                data = _json.loads(text)
                accounts = data.get("accounts") if isinstance(data, dict) else None
                if isinstance(accounts, list) and accounts:
                    cookie = str(accounts[0].get("cookie") or "").strip()
                    if cookie:
                        return cookie
                raw = data.get("xhs") if isinstance(data, dict) else None
                if isinstance(raw, list) and raw:
                    return str(raw[0] or "").strip()
            lines = [
                line.strip()
                for line in text.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            cookie = " ".join(lines).strip()
            if cookie:
                return cookie
    return load_xhs_cookie().cookie

