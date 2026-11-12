# -*- coding: utf-8 -*-
"""小红书 Web 私信：会话列表 + 历史消息 + 轮询新消息。

接口（需 cookie + x-s 签名）:
  GET /api/im/web/v3/chats
  GET /api/im/web/messages/history?chat_user_id=&last_id=&start_id=&limit=
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .client import XhsClient

CHATS_URI = "/api/im/web/v3/chats"
HISTORY_URI = "/api/im/web/messages/history"


def sanitize_filename(name: str) -> str:
    text = str(name or "").strip() or "unknown"
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in text)[:80]


def account_summary(client: XhsClient) -> Dict[str, str]:
    """当前 cookie 账号摘要。"""
    me = client.user_me()
    return {
        "user_id": str(me.get("user_id") or ""),
        "nickname": str(me.get("nickname") or ""),
        "red_id": str(me.get("red_id") or ""),
    }


def resolve_client_by_nick(nick: str) -> Tuple[XhsClient, Dict[str, str]]:
    """按昵称 / 小红书号 / user_id 在 xhs/cookies.json 账号中匹配。"""
    from .credentials import _load_store, _to_credential

    needle = (nick or "").strip().lower()
    if not needle:
        raise ValueError("empty nick")
    errors: List[str] = []
    store = _load_store()
    for raw in store.get("accounts") or []:
        try:
            acc = _to_credential(raw)
            client = XhsClient(cookie=acc.cookie)
            summary = account_summary(client)
            keys = {
                summary.get("nickname", "").lower(),
                summary.get("red_id", "").lower(),
                summary.get("user_id", "").lower(),
                acc.name.lower(),
            }
            if needle in keys:
                return client, summary
        except Exception as exc:
            errors.append(f"{raw.get('name')}:{exc}")
    hint = f" tried={errors}" if errors else ""
    raise RuntimeError(f"no xhs cookie matched nick={nick!r}{hint}")


def parse_message_content(raw: Any) -> Tuple[str, Optional[int]]:
    """解析 content 字段，返回 (可读文本, content_type)。"""
    if raw is None:
        return "", None
    if isinstance(raw, dict):
        text = raw.get("content") or raw.get("text") or raw.get("front_chain") or ""
        return str(text), raw.get("content_type")
    if isinstance(raw, str):
        s = raw.strip()
        if s.startswith("{"):
            try:
                obj = json.loads(s)
                if isinstance(obj, dict):
                    text = (
                        obj.get("content")
                        or obj.get("text")
                        or obj.get("front_chain")
                        or obj.get("frontChain")
                        or ""
                    )
                    ctype = obj.get("content_type")
                    if isinstance(text, str) and text.startswith("{"):
                        try:
                            inner = json.loads(text)
                            if isinstance(inner, dict):
                                text = (
                                    inner.get("content")
                                    or inner.get("text")
                                    or text
                                )
                        except Exception:
                            pass
                    if not text:
                        text = obj.get("front_chain") or obj.get("frontChain") or ""
                    return str(text), ctype
            except Exception:
                pass
        return s, None
    return str(raw), None


def _format_time(created_at: Any) -> str:
    if created_at is None:
        return ""
    try:
        ts = int(created_at)
        if ts > 1_000_000_000_000:
            ts //= 1000
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(created_at or "")


def normalize_message(
    m: Dict[str, Any],
    *,
    my_uid: str = "",
    peer_name: str = "",
) -> Dict[str, Any]:
    text, ctype = parse_message_content(m.get("content"))
    sender_id = str(m.get("sender_id") or "")
    if my_uid and sender_id == str(my_uid):
        sender_label = "我"
    elif peer_name:
        sender_label = peer_name
    else:
        sender_label = sender_id or "?"
    return {
        "id": m.get("id"),
        "store_id": m.get("store_id"),
        "sender_id": sender_id,
        "receiver_id": m.get("receiver_id"),
        "sender": sender_label,
        "content_type": ctype,
        "text": text,
        "created_at": m.get("created_at"),
        "time": _format_time(m.get("created_at")),
        "revoked": bool(m.get("revoked")),
        "uuid": m.get("uuid"),
    }


def list_chats(
    client: XhsClient,
    *,
    limit: int = 100,
    page: int = 0,
) -> Dict[str, Any]:
    """拉会话列表。"""
    return client._request(
        "GET",
        CHATS_URI,
        params={
            "limit": str(limit),
            "complete": "true",
            "page": str(page),
            "source": "pc",
        },
    )


def fetch_history(
    client: XhsClient,
    chat_user_id: str,
    *,
    last_id: int,
    start_id: int = 0,
    limit: int = 30,
) -> List[Dict[str, Any]]:
    """拉单个会话一页历史，返回 out_message_list。"""
    data = client._request(
        "GET",
        HISTORY_URI,
        params={
            "chat_user_id": str(chat_user_id),
            "last_id": str(last_id),
            "start_id": str(start_id),
            "limit": str(limit),
        },
    )
    if isinstance(data, dict):
        return list(data.get("out_message_list") or data.get("messages") or [])
    if isinstance(data, list):
        return data
    return []


def fetch_since(
    client: XhsClient,
    chat_user_id: str,
    *,
    since_store_id: int,
    max_store_id: int,
    page_size: int = 30,
) -> List[Dict[str, Any]]:
    """拉 store_id > since_store_id 的新消息（升序）。"""
    if max_store_id <= since_store_id:
        return []
    messages: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    last_id = int(max_store_id)
    start_id = int(since_store_id)
    while last_id > start_id:
        batch = fetch_history(
            client,
            chat_user_id,
            last_id=last_id,
            start_id=start_id,
            limit=page_size,
        )
        if not batch:
            break
        store_ids: List[int] = []
        for m in batch:
            mid = str(m.get("id") or m.get("store_id") or "")
            if not mid or mid in seen:
                continue
            seen.add(mid)
            messages.append(m)
            try:
                store_ids.append(int(m.get("store_id")))
            except Exception:
                pass
        if len(batch) < page_size or not store_ids:
            break
        min_sid = min(store_ids)
        if min_sid <= start_id + 1:
            break
        last_id = min_sid - 1
    messages.sort(key=lambda m: int(m.get("store_id") or 0))
    return messages


def fetch_recent_history(
    client: XhsClient,
    chat_user_id: str,
    *,
    max_store_id: int,
    limit: int = 80,
    page_size: int = 30,
) -> List[Dict[str, Any]]:
    """只拉最近 limit 条消息（打开会话时用，避免翻全量历史）。"""
    if max_store_id <= 0:
        return []
    start_id = max(0, int(max_store_id) - int(limit))
    return fetch_since(
        client,
        chat_user_id,
        since_store_id=start_id,
        max_store_id=max_store_id,
        page_size=page_size,
    )


def fetch_all_history(
    client: XhsClient,
    chat_user_id: str,
    *,
    max_store_id: int,
    page_size: int = 30,
) -> List[Dict[str, Any]]:
    """翻页拉完一个会话的全部历史（按 store_id 升序）。"""
    return fetch_since(
        client,
        chat_user_id,
        since_store_id=0,
        max_store_id=max_store_id or 1,
        page_size=page_size,
    )


def conversation_filename(peer: str, chat_user_id: str = "") -> str:
    base = sanitize_filename(peer or chat_user_id or "unknown", default="unknown")
    suffix = sanitize_filename(chat_user_id, default="") if chat_user_id else ""
    if suffix and suffix not in base:
        return f"{base}_{suffix}.json"
    return f"{base}.json"


SEND_URI = "/api/im/web/message"

SEND_URI_CANDIDATES = (
    "/api/im/web/v2/messages/send",
    "/api/im/web/v2/message/send",
    "/api/im/web/v3/message",
    "/api/im/web/v3/message/send",
    "/api/im/web/v2/message",
    "/api/im/web/v2/message/send",
    "/api/im/web/message",
    "/api/im/web/message/send",
    "/api/im/web/messages/send",
    "/api/im/web/v1/message/send",
)


def _wrap_text_content(text: str) -> str:
    return json.dumps(
        {
            "content": text,
            "content_type": 1,
            "not_front_chain": False,
            "not_unread_count": False,
            "front_chain": text,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _peer_name_for_chat(client: XhsClient, chat_user_id: str) -> str:
    try:
        chats = list_chats(client, limit=100).get("chats") or []
        for ch in chats:
            if str(ch.get("chat_user_id") or "") == str(chat_user_id):
                info = ch.get("info") or {}
                return str(info.get("nickname") or info.get("user_name") or "")
    except Exception:
        pass
    return ""


def resolve_chat_target(
    client: XhsClient,
    target: str,
    *,
    chat_limit: int = 100,
) -> Tuple[str, str]:
    """把昵称 / 小红书号 / chat_user_id 解析为 (chat_user_id, peer_name)。

    先按昵称/user_id 精确匹配会话列表，再按子串匹配；都失败则报错。
    """
    target = (target or "").strip()
    if not target:
        raise ValueError("empty target")
    chats = (list_chats(client, limit=chat_limit).get("chats") or [])
    for ch in chats:
        info = ch.get("info") or {}
        nm = str(info.get("nickname") or info.get("user_name") or "").strip()
        uid = str(ch.get("chat_user_id") or "")
        if nm == target or uid == target:
            return uid, nm
    for ch in chats:
        info = ch.get("info") or {}
        nm = str(info.get("nickname") or info.get("user_name") or "").strip()
        uid = str(ch.get("chat_user_id") or "")
        if target and (target in nm or target in uid):
            return uid, nm
    raise RuntimeError(
        f"未找到会话「{target}」：请先用 boss xhs im dump 查看会话列表，"
        f"再传入对方的 chat_user_id"
    )


def send_text(
    client: XhsClient,
    chat_user_id: str,
    text: str,
    *,
    headed: bool = False,
    peer_name: str = "",
) -> Dict[str, Any]:
    """发送文本私信（PC Web）。

    优先级：
      1) 纯 WebSocket 直发（im_ws，最快，~1-2s，免浏览器）
      2) HTTP 候选接口（兼容历史）
      3) Playwright 浏览器 UI 发送（最后兜底）
    """
    content_text = (text or "").strip()
    if not content_text:
        raise ValueError("empty text")
    chat_user_id = str(chat_user_id or "").strip()
    if not chat_user_id:
        raise ValueError("chat_user_id required")

    # 1) 纯 WS 直发（主链路，消息体为明文 protobuf）
    ws_exc: Optional[Exception] = None
    try:
        from .im_ws import send_text_ws

        summary = account_summary(client)
        my_uid = str(summary.get("user_id") or "")
        my_nick = str(summary.get("nickname") or "")
        if my_uid:
            ws_res = send_text_ws(
                client.cookie,
                from_uid=my_uid,
                to_uid=chat_user_id,
                content=content_text,
                nickname=my_nick,
            )
            if ws_res.get("ok"):
                return ws_res
            raise RuntimeError(f"WS 发送未确认: {json.dumps(ws_res.get('ack') or {}, ensure_ascii=False)[:200]}")
    except Exception as exc:
        ws_exc = exc

    inner = _wrap_text_content(content_text)
    msg_uuid = str(uuid.uuid4())
    payload_variants = [
        {
            "receiver_id": chat_user_id,
            "content": inner,
            "content_type": 1,
            "uuid": msg_uuid,
        },
        {
            "chat_user_id": chat_user_id,
            "receiver_id": chat_user_id,
            "content": inner,
            "content_type": 1,
            "uuid": msg_uuid,
        },
        {
            "receiver_id": chat_user_id,
            "content": content_text,
            "content_type": 1,
            "uuid": msg_uuid,
        },
    ]
    last_exc: Optional[Exception] = None
    for uri in SEND_URI_CANDIDATES:
        for payload in payload_variants:
            try:
                return client._request("POST", uri, payload=payload)
            except Exception as exc:
                last_exc = exc
                if "404" not in str(exc):
                    raise
    try:
        return send_text_browser(
            client.cookie,
            chat_user_id,
            content_text,
            headed=headed,
            peer_name=peer_name or _peer_name_for_chat(client, chat_user_id),
        )
    except Exception as browser_exc:
        raise RuntimeError(
            f"发送失败: WS({ws_exc}); HTTP 接口({last_exc}); "
            f"浏览器回退({browser_exc})"
        ) from browser_exc


def send_text_browser(
    cookie: str,
    chat_user_id: str,
    text: str,
    *,
    headed: bool = False,
    timeout: float = 60,
    peer_name: str = "",
) -> Dict[str, Any]:
    """Playwright 模拟网页发信（HTTP 404 时的回退）。"""
    import asyncio

    return asyncio.run(
        _send_text_browser_async(
            cookie,
            chat_user_id,
            text,
            headed=headed,
            timeout=timeout,
            peer_name=peer_name,
        )
    )


async def _send_text_browser_async(
    cookie: str,
    chat_user_id: str,
    text: str,
    *,
    headed: bool = False,
    timeout: float = 60,
    peer_name: str = "",
) -> Dict[str, Any]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError("未安装 playwright") from exc

    from .login_util import find_chrome, parse_cookie_header

    ck = parse_cookie_header(cookie)
    domain = ".xiaohongshu.com"
    pw_cookies = [
        {
            "name": k,
            "value": v,
            "domain": domain,
            "path": "/",
        }
        for k, v in ck.items()
        if v
    ]

    captured: Dict[str, Any] = {"ok": False, "url": ""}

    async def _on_response(resp):
        url = resp.url
        if "edith.xiaohongshu.com/api/im/" not in url or resp.request.method != "POST":
            return
        if any(x in url for x in ("/read", "/messages/read")):
            return
        if resp.status != 200:
            return
        try:
            data = await resp.json()
        except Exception:
            return
        if data.get("success") or data.get("code") == 0:
            captured["ok"] = True
            captured["url"] = url
            captured["data"] = data

    async with async_playwright() as p:
        chrome = find_chrome()
        launch_kwargs = {
            "headless": not headed,
            "args": ["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        }
        if chrome:
            launch_kwargs["executable_path"] = chrome
        browser = await p.chromium.launch(**launch_kwargs)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        )
        if pw_cookies:
            await context.add_cookies(pw_cookies)
        page = await context.new_page()
        page.on("response", _on_response)

        await page.goto(
            "https://www.xiaohongshu.com/explore",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        await page.wait_for_timeout(1200)

        # 侧边栏「消息」→ /chat 私信页
        await page.locator("text=消息").first.click(timeout=8000)
        await page.wait_for_timeout(2500)
        if "/chat" not in page.url:
            await page.goto(
                "https://www.xiaohongshu.com/chat",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            await page.wait_for_timeout(2000)

        opened = False
        for sel in (
            f"text={peer_name}" if peer_name else "",
            f"[data-user-id='{chat_user_id}']",
            f"a[href*='{chat_user_id}']",
        ):
            if not sel:
                continue
            try:
                loc = page.locator(sel).first
                if await loc.count():
                    await loc.click(timeout=5000)
                    opened = True
                    break
            except Exception:
                continue
        if not opened:
            raise RuntimeError(f"未找到会话「{peer_name or chat_user_id}」，请确认 cookie 有效")

        await page.wait_for_timeout(1200)
        box = page.locator("[contenteditable='true']").first
        if not await box.count() or not await box.is_visible():
            raise RuntimeError("未找到私信输入框")
        await box.click(timeout=3000)
        await box.fill(text)
        await page.wait_for_timeout(300)

        sent_click = False
        for sel in ("button:has-text('发送')", "[class*='send-btn']", "[class*='Send']"):
            try:
                btn = page.locator(sel).first
                if await btn.count() and await btn.is_visible():
                    await btn.click(timeout=3000)
                    sent_click = True
                    break
            except Exception:
                continue
        if not sent_click:
            # Enter 发送（已聚焦输入框，避免误发换行）
            await box.press("Enter")

        # 双路径成功判定：
        #  1) 捕获到 send_message 接口成功响应（返回 message_id）
        #  2) 输入框被清空 = 消息已提交（DOM 侧兜底）
        deadline = time.time() + timeout
        dom_hit = False
        while time.time() < deadline:
            if captured.get("ok"):
                resp_data = captured.get("data") or {}
                inner = resp_data.get("data") or {}
                mid = (
                    inner.get("message_id")
                    if isinstance(inner, dict)
                    else None
                )
                await browser.close()
                return {
                    "ok": True,
                    "via": "browser_ui",
                    "endpoint": captured.get("url"),
                    "message_id": mid,
                    "result": resp_data,
                }
            if not dom_hit:
                try:
                    cur = (await box.inner_text() or "").strip()
                    if not cur:
                        dom_hit = True
                except Exception:
                    pass
            if dom_hit:
                await page.wait_for_timeout(600)
                await browser.close()
                return {
                    "ok": True,
                    "via": "browser_ui",
                    "endpoint": captured.get("url") or "dom-cleared",
                    "message_id": None,
                    "result": {},
                }
            await page.wait_for_timeout(400)

        await browser.close()
        raise RuntimeError(
            "已在私信页输入并发送，但未确认成功；"
            "可设置 headed=true 观察浏览器，或在 Network 中抓取 send 接口 URL"
        )


def dump_all_conversations(
    client: XhsClient,
    *,
    chat_limit: int = 100,
    page_size: int = 30,
) -> Dict[str, Any]:
    """会话列表 + 每个会话完整历史。"""
    me = client.user_me()
    my_uid = str(me.get("user_id") or "")
    chats = (list_chats(client, limit=chat_limit).get("chats") or [])
    conversations: List[Dict[str, Any]] = []
    for ch in chats:
        info = ch.get("info") or {}
        peer = str(info.get("nickname") or info.get("user_name") or "")
        chat_uid = str(ch.get("chat_user_id") or "")
        max_sid = int(ch.get("max_store_id") or 0)
        raw_msgs = fetch_all_history(
            client, chat_uid, max_store_id=max_sid, page_size=page_size
        )
        messages = [
            normalize_message(m, my_uid=my_uid, peer_name=peer) for m in raw_msgs
        ]
        conversations.append(
            {
                "title": peer or chat_uid,
                "peer": peer,
                "chat_user_id": chat_uid,
                "avatar": info.get("avatar") or "",
                "follow_status": info.get("follow_status"),
                "is_friend": info.get("is_friend"),
                "last_msg_content": ch.get("last_msg_content"),
                "last_msg_time": ch.get("last_msg_time"),
                "max_store_id": max_sid,
                "message_count": len(messages),
                "messages": messages,
            }
        )
    return {
        "platform": "xhs",
        "crawl_type": "im",
        "account": {
            "user_id": my_uid,
            "nickname": me.get("nickname"),
            "red_id": me.get("red_id"),
        },
        "conversation_count": len(conversations),
        "conversations": conversations,
    }


def format_message_line(conv_peer: str, msg: Dict[str, Any]) -> str:
    when = str(msg.get("time") or "")
    prefix = f"[{when}] " if when else ""
    return (
        f"{prefix}【会话:{conv_peer}】【来自:{msg.get('sender')}】"
        f"【store:{msg.get('store_id')}】{msg.get('text') or ''}"
    )


def poll_new_messages(
    client: XhsClient,
    seen: Set[str],
    *,
    seed_only: bool = False,
    chat_limit: int = 100,
    page_size: int = 30,
    chat_watermarks: Optional[Dict[str, int]] = None,
) -> List[Tuple[str, Dict[str, Any]]]:
    """轮询：返回 [(peer, normalized_msg), ...]。

    chat_watermarks: chat_user_id -> 已处理到的 max store_id（增量拉取）。
    seed_only=True 时只把已有消息记入 seen，不返回。
    """
    me = client.user_me()
    my_uid = str(me.get("user_id") or "")
    watermarks = chat_watermarks if chat_watermarks is not None else {}
    chats = (list_chats(client, limit=chat_limit).get("chats") or [])
    fresh: List[Tuple[str, Dict[str, Any]]] = []
    for ch in chats:
        info = ch.get("info") or {}
        peer = str(info.get("nickname") or info.get("user_name") or "")
        chat_uid = str(ch.get("chat_user_id") or "")
        max_sid = int(ch.get("max_store_id") or 0)
        since_sid = int(watermarks.get(chat_uid, 0))
        if seed_only or since_sid <= 0:
            raw_msgs = fetch_all_history(
                client, chat_uid, max_store_id=max_sid, page_size=page_size
            )
        else:
            raw_msgs = fetch_since(
                client,
                chat_uid,
                since_store_id=since_sid,
                max_store_id=max_sid,
                page_size=page_size,
            )
        if max_sid > since_sid:
            watermarks[chat_uid] = max_sid
        for m in raw_msgs:
            mid = str(m.get("id") or f"{chat_uid}:{m.get('store_id')}")
            if mid in seen:
                continue
            seen.add(mid)
            if seed_only:
                continue
            nm = normalize_message(m, my_uid=my_uid, peer_name=peer)
            fresh.append((peer, nm))
    return fresh


def run_poll_loop(
    client: XhsClient,
    *,
    interval: float = 2.0,
    seconds: int = 0,
    on_message: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    chat_limit: int = 100,
    list_refresh: float = 30.0,
) -> None:
    """持续轮询新私信。seconds<=0 表示一直听。"""
    seen: Set[str] = set()
    watermarks: Dict[str, int] = {}
    print("[im] seeding existing messages…", flush=True)
    try:
        poll_new_messages(
            client,
            seen,
            seed_only=True,
            chat_limit=chat_limit,
            chat_watermarks=watermarks,
        )
    except Exception as exc:
        print(f"[im] seed err: {exc}", flush=True)
        raise
    print(
        f"[im] seeded {len(seen)} msgs across {len(watermarks)} conversations, watching…",
        flush=True,
    )
    start = time.time()
    last_list = start
    while True:
        if seconds > 0 and (time.time() - start) >= seconds:
            break
        if (time.time() - last_list) >= max(5.0, float(list_refresh)):
            watermarks.clear()
            last_list = time.time()
        try:
            fresh = poll_new_messages(
                client,
                seen,
                chat_limit=chat_limit,
                chat_watermarks=watermarks,
            )
            for peer, msg in fresh:
                line = format_message_line(peer, msg)
                if on_message:
                    on_message(peer, msg)
                else:
                    print("[im]", line, flush=True)
        except Exception as e:
            print(f"[im] err: {e}", flush=True)
        time.sleep(max(0.5, interval))
