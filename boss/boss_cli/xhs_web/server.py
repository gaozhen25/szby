# -*- coding: utf-8 -*-
"""小红书私信 · 本地网页版聊天（Flask + SSE 实时推送）。

架构：
  - 后台线程跑 im_ws.receive_messages_ws（上游 WS 长连接，实时收推送）
  - 浏览器通过 SSE（/api/stream）实时收到新消息
  - 发送走 POST /api/send → im.send_text（内部 WS 直发）
  - 会话列表 / 历史来自小红书 HTTP（im.list_chats / fetch_recent_history）

启动：
  boss xhs web [--port 8767]
"""
from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from typing import Any, Dict, List, Optional

import requests
from flask import Flask, Response, jsonify, request, send_from_directory

from boss_cli.xhs import im as im_mod
from boss_cli.xhs import im_ws
from boss_cli.xhs.client import DEFAULT_UA, XhsClient
from boss_cli.xhs_web import auto_reply as auto_reply_mod

logger = logging.getLogger("xhs_web")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=None)

# 运行时状态
STATE: Dict[str, Any] = {
    "client": None,  # XhsClient
    "me": {},  # account_summary
    "chats_cache": [],  # 最近一次会话列表
    "started": False,
}
SUBS: List[queue.Queue] = []
SUBS_LOCK = threading.Lock()


# ---------- 广播 / SSE ----------

def broadcast(event: str, data: Dict[str, Any]) -> None:
    payload = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    with SUBS_LOCK:
        subs = list(SUBS)
    dead: List[queue.Queue] = []
    for q in subs:
        try:
            q.put_nowait(payload)
        except Exception:
            dead.append(q)
    if dead:
        with SUBS_LOCK:
            for q in dead:
                if q in SUBS:
                    SUBS.remove(q)


def upstream_loop() -> None:
    """后台线程：上游 WS 实时接收 → 广播给浏览器。断线自动重连。"""
    client = STATE["client"]
    my_uid = str(STATE["me"].get("user_id") or "")
    logger.info("upstream_loop start uid=%s", my_uid)
    while True:
        try:
            for msg in im_ws.receive_messages_ws(client.cookie, my_uid):
                try:
                    ev = normalize_event(msg)
                    if not ev:
                        continue
                    if ev.get("outgoing"):
                        # 自己发的消息由前端乐观插入显示；im_ws 回推/补拉会导致与乐观插入重复，跳过
                        continue
                    logger.info(
                        "UPSTREAM MSG sender=%s text=%r kind=%s",
                        msg.get("sender"),
                        str(msg.get("text") or "")[:40],
                        ev.get("kind"),
                    )
                    # 先推消息（实时），再异步补会话卡片——绝不能在推消息前同步打 list_chats
                    broadcast("message", ev)
                    _maybe_broadcast_new_chat(ev)
                    _schedule_auto_reply(ev)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("normalize_event failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("upstream disconnected: %s; reconnect in 2s", exc)
        time.sleep(2)


# ---------- 消息归一化 ----------

def _walk_strings(obj: Any) -> List[str]:
    out: List[str] = []
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(_walk_strings(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_walk_strings(v))
    return out


def classify_url(u: str) -> str:
    low = u.lower()
    if "/audio/" in low or any(low.endswith(e) for e in (".mp3", ".m4a", ".aac", ".wav", ".amr")):
        return "audio"
    if "/chat_livephoto/" in low or "/video/" in low:
        return "video"
    if "msg-img" in low or any(e in low for e in (".jpg", ".jpeg", ".png", ".gif", ".webp")):
        return "image"
    return "other"


def extract_media(raw_inner: Any, raw_info: Any) -> Dict[str, Any]:
    """从 content JSON 里提取图片 / 语音 / 视频资源。

    真实结构（抓包验证）：
      语音 content_type=9: inner = {duration, link: "https://msg-video.xhscdn.com/audio/..."}
      图片 content_type=9: inner = {link: "https://msg-img.xhscdn.com/...", livePhotoVideo:{videoLink}, ...}
      表情 content_type=1: inner.content = "[微笑R]" 之类代码（文本）
    """
    images: List[str] = []
    audio = ""
    video = ""
    duration = 0

    def push_url(u: str) -> None:
        nonlocal audio, video
        kind = classify_url(u)
        if kind == "image":
            if u not in images:
                images.append(u)
        elif kind == "audio":
            if not audio:
                audio = u
        elif kind == "video":
            if not video:
                video = u

    # 1) 显式键名（含嵌套）
    if isinstance(raw_inner, dict):
        for k in ("image_url", "imageUrl", "pic_url", "picUrl", "url", "link"):
            v = raw_inner.get(k)
            if isinstance(v, str) and v.startswith("http"):
                push_url(v)
        for k in ("voice_url", "voiceUrl", "audio_url", "audioUrl", "audio", "sound"):
            v = raw_inner.get(k)
            if isinstance(v, str) and v.startswith("http"):
                push_url(v)
        if isinstance(raw_inner.get("duration"), (int, float)):
            duration = int(raw_inner["duration"])
        lpv = raw_inner.get("livePhotoVideo") or {}
        if isinstance(lpv, dict):
            v = lpv.get("videoLink")
            if isinstance(v, str) and v.startswith("http"):
                push_url(v)
    # 2) 兜底：扫描所有字符串里的 http 资源按 URL 分类
    if not images and not audio and not video:
        for s in _walk_strings([raw_inner, raw_info]):
            if not isinstance(s, str) or not s.startswith("http"):
                continue
            push_url(s)
    seen = set()
    images = [u for u in images if not (u in seen or seen.add(u))]
    return {"images": images, "audio": audio, "video": video, "duration": duration}


def parse_raw_content(raw_content: Any) -> "tuple[str, Any, Any]":
    """解析历史消息的 content 字段，返回 (text, inner_obj, outer_obj)。"""
    if isinstance(raw_content, dict):
        outer = raw_content
        inner = raw_content.get("content")
        text = str(raw_content.get("content") or raw_content.get("front_chain") or "")
        inner_obj = None
        if isinstance(inner, str) and inner.strip().startswith("{"):
            try:
                inner_obj = json.loads(inner)
                if isinstance(inner_obj, dict):
                    text = str(inner_obj.get("content") or inner_obj.get("front_chain") or text)
            except Exception:
                inner_obj = None
        return text, inner_obj, outer
    if isinstance(raw_content, str):
        s = raw_content.strip()
        if s.startswith("{"):
            try:
                outer = json.loads(s)
            except Exception:
                outer = None
            if isinstance(outer, dict):
                inner = outer.get("content")
                text = str(inner or outer.get("front_chain") or "")
                inner_obj = None
                if isinstance(inner, str) and inner.strip().startswith("{"):
                    try:
                        inner_obj = json.loads(inner)
                        if isinstance(inner_obj, dict):
                            text = str(inner_obj.get("content") or inner_obj.get("front_chain") or text)
                    except Exception:
                        inner_obj = None
                return text, inner_obj, outer
        return s, None, None
    return str(raw_content), None, None


def media_label(
    outer_obj: Any,
    inner_obj: Any,
    raw_text: str,
    images: List[str],
    audio: str,
    video: str,
) -> str:
    """媒体消息的展示文案：优先 front_chain，否则用占位。"""
    if not (images or audio or video):
        return raw_text
    for obj in (outer_obj, inner_obj):
        if isinstance(obj, dict):
            label = obj.get("front_chain") or obj.get("frontChain")
            if label:
                return str(label)
    if images:
        return "[图片]"
    if audio:
        return "[语音]"
    if video:
        return "[视频]"
    return raw_text


def normalize_event(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """把 im_ws 下行消息转成前端友好的结构。"""
    my_uid = str(STATE["me"].get("user_id") or "")
    sender = str(msg.get("sender") or "")
    receiver = str(msg.get("receiver") or "")
    # 以 sender 是否是自己为准判定收发方向：推送帧里的 outgoing 字段不可信（实测被置为 true）
    outgoing = bool(sender and sender == my_uid)
    chat_user_id = receiver if outgoing else sender
    if not chat_user_id:
        return None
    raw_inner = msg.get("raw_inner")
    raw_info = msg.get("raw_info")
    media = extract_media(raw_inner, raw_info)
    raw_text = str(msg.get("text") or "")
    if media["images"] or media["audio"] or media["video"]:
        kind = "media"
    else:
        kind = "text"
    text = media_label(raw_info, raw_inner, raw_text, media["images"], media["audio"], media["video"])
    return {
        "kind": kind,
        "chat_user_id": chat_user_id,
        "message_id": msg.get("message_id") or "",
        "client_uuid": msg.get("client_uuid") or "",
        "store_id": msg.get("store_id"),
        "sender": str(msg.get("sender") or ""),
        "receiver": str(msg.get("receiver") or ""),
        "outgoing": outgoing,
        "nickname": str(msg.get("nickname") or ""),
        "time": msg.get("time") or "",
        "timestamp_ms": msg.get("timestamp_ms") or 0,
        "message_type": msg.get("message_type"),
        "text": text,
        "images": media["images"],
        "audio": media["audio"],
        "video": media["video"],
        "duration": media["duration"],
        "revoked": bool(msg.get("revoked")),
    }


def normalize_history_message(m: Dict[str, Any], chat_user_id: str) -> Dict[str, Any]:
    """历史消息归一化（含图片/语音媒体提取），与实时消息同构。"""
    raw_content = m.get("content")
    text, inner_obj, outer_obj = parse_raw_content(raw_content)
    media = extract_media(inner_obj, outer_obj)
    my_uid = str(STATE["me"].get("user_id") or "")
    sender_id = str(m.get("sender_id") or "")
    outgoing = bool(sender_id and sender_id == my_uid)
    if media["images"] or media["audio"] or media["video"]:
        kind = "media"
    else:
        kind = "text"
    text = media_label(outer_obj, inner_obj, text, media["images"], media["audio"], media["video"])
    created = m.get("created_at")
    ts = 0
    try:
        ts = int(created)
    except Exception:
        pass
    if ts > 1_000_000_000_000:
        ts //= 1000
    when = ""
    if ts:
        import datetime

        when = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "kind": kind,
        "chat_user_id": chat_user_id,
        "message_id": m.get("id") or "",
        "store_id": m.get("store_id"),
        "outgoing": outgoing,
        "sender": "我" if outgoing else str(m.get("sender_id") or ""),
        "time": when,
        "timestamp_ms": (int(created) if isinstance(created, (int, float)) else 0),
        "message_type": m.get("message_type"),
        "text": text,
        "images": media["images"],
        "audio": media["audio"],
        "video": media["video"],
        "duration": media["duration"],
        "revoked": bool(m.get("revoked")),
    }


def _chat_summary(ch: Dict[str, Any]) -> Dict[str, Any]:
    """把 list_chats 原始条目压成前端会话卡片。"""
    info = ch.get("info") or {}
    return {
        "chat_user_id": str(ch.get("chat_user_id") or ""),
        "nickname": str(
            info.get("nickname")
            or info.get("user_name")
            or "?"
        ),
        "avatar": str(info.get("avatar") or ""),
        "follow_status": info.get("follow_status"),
        "is_friend": info.get("is_friend"),
        "last_msg_content": ch.get("last_msg_content") or "",
        "last_msg_time": ch.get("last_msg_time") or "",
        "max_store_id": int(ch.get("max_store_id") or 0),
    }


def _enrich_chat_async(cid: str) -> None:
    """后台刷新官方会话列表，用真实昵称/头像覆盖临时卡片。"""
    try:
        chats = load_chats()
        hit = next((c for c in chats if str(c.get("chat_user_id") or "") == cid), None)
        if hit:
            broadcast("chat", hit)
    except Exception as exc:  # noqa: BLE001
        logger.warning("enrich chat failed cid=%s err=%s", cid, exc)


def _maybe_broadcast_new_chat(ev: Dict[str, Any]) -> None:
    """WS 收到未知会话消息时，立刻推临时 chat（不阻塞），再异步补全资料。"""
    cid = str(ev.get("chat_user_id") or "")
    if not cid:
        return
    cache = list(STATE.get("chats_cache") or [])
    if any(str(c.get("chat_user_id") or "") == cid for c in cache):
        return
    # 立刻推临时卡片（零 HTTP 等待），前端左侧马上出现
    provisional = {
        "chat_user_id": cid,
        "nickname": str(ev.get("nickname") or cid),
        "avatar": str(ev.get("avatar") or ""),
        "last_msg_content": str(ev.get("text") or "")[:40],
        "last_msg_time": ev.get("timestamp_ms") or "",
        "max_store_id": ev.get("store_id") or 0,
    }
    cache = [provisional] + [c for c in cache if str(c.get("chat_user_id") or "") != cid]
    STATE["chats_cache"] = cache
    broadcast("chat", provisional)
    # 异步拉官方列表补昵称/头像（不挡消息推送）
    threading.Thread(target=_enrich_chat_async, args=(cid,), daemon=True).start()


def _auto_send(chat_user_id: str, text: str) -> Any:
    client = STATE["client"]
    return im_mod.send_text(client, chat_user_id, text)


def _auto_sent_notify(chat_user_id: str, text: str) -> None:
    """把自动回复也推到前端 SSE，网页能立刻看到。"""
    now_ms = int(time.time() * 1000)
    broadcast(
        "message",
        {
            "kind": "text",
            "chat_user_id": chat_user_id,
            "message_id": f"auto-{now_ms}",
            "store_id": None,
            "outgoing": True,
            "sender": "我",
            "nickname": str(STATE.get("me", {}).get("nickname") or "我"),
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp_ms": now_ms,
            "text": text,
            "images": [],
            "audio": "",
            "video": "",
            "duration": 0,
            "revoked": False,
        },
    )
    # 更新左侧预览
    cache = list(STATE.get("chats_cache") or [])
    hit = None
    for c in cache:
        if str(c.get("chat_user_id") or "") == chat_user_id:
            hit = c
            break
    if hit:
        hit["last_msg_content"] = text.replace("\n", " ")[:40]
        STATE["chats_cache"] = [hit] + [c for c in cache if c is not hit]
        broadcast("chat", hit)


def _schedule_auto_reply(ev: Dict[str, Any]) -> None:
    """异步跑自动回复，不阻塞收消息线程。"""
    if not auto_reply_mod.is_enabled():
        return
    if ev.get("outgoing") or ev.get("revoked"):
        return

    def _run() -> None:
        try:
            auto_reply_mod.handle_incoming(
                ev, send_fn=_auto_send, on_sent=_auto_sent_notify
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("auto_reply worker failed: %s", exc)

    threading.Thread(target=_run, daemon=True).start()


def sync_loop() -> None:
    """后台补齐：高频对比 max_store_id，补拉并广播 im_ws 断连期间漏收的新消息。

    主路径仍是 WS 实时推送；本循环只做兜底（约 2s 一轮），保证新会话/漏消息尽快补上。
    """
    seen: Dict[str, int] = {}
    bootstrapped = False
    tick = 0
    last_ids: tuple = ()
    while True:
        try:
            client = STATE.get("client")
            if not client:
                time.sleep(2)
                continue
            data = im_mod.list_chats(client, limit=100)
            raw_chats = list(data.get("chats") or [])
            summaries = [_chat_summary(ch) for ch in raw_chats if ch.get("chat_user_id")]
            STATE["chats_cache"] = summaries
            my_uid = str(STATE["me"].get("user_id") or "")

            for ch in raw_chats:
                cid = str(ch.get("chat_user_id") or "")
                try:
                    max_id = int(ch.get("max_store_id") or 0)
                except Exception:  # noqa: BLE001
                    max_id = 0
                if not cid or max_id <= 0:
                    continue
                last_seen = seen.get(cid, 0)
                if last_seen == 0:
                    seen[cid] = max_id
                    if bootstrapped:
                        summary = _chat_summary(ch)
                        logger.info(
                            "SYNC NEW CHAT cid=%s nick=%s max=%s",
                            cid,
                            summary.get("nickname"),
                            max_id,
                        )
                        broadcast("chat", summary)
                        try:
                            since = max(0, max_id - 5)
                            raw_msgs = im_mod.fetch_since(
                                client,
                                cid,
                                since_store_id=since,
                                max_store_id=max_id,
                                page_size=30,
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("sync new-chat fetch failed cid=%s err=%s", cid, exc)
                            continue
                        for raw in raw_msgs or []:
                            sender_id = str(raw.get("sender_id") or "")
                            if sender_id and sender_id == my_uid:
                                continue
                            try:
                                broadcast("message", normalize_history_message(raw, cid))
                            except Exception as exc:  # noqa: BLE001
                                logger.warning("normalize new-chat msg failed: %s", exc)
                    continue
                if max_id <= last_seen:
                    continue
                try:
                    raw_msgs = im_mod.fetch_since(
                        client, cid, since_store_id=last_seen, max_store_id=max_id, page_size=30
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("sync fetch failed cid=%s err=%s", cid, exc)
                    seen[cid] = max_id
                    continue
                events: List[Dict[str, Any]] = []
                for raw in raw_msgs or []:
                    try:
                        sid = int(raw.get("store_id") or 0)
                    except Exception:  # noqa: BLE001
                        sid = 0
                    if sid <= last_seen:
                        continue
                    sender_id = str(raw.get("sender_id") or "")
                    if sender_id and sender_id == my_uid:
                        continue
                    try:
                        events.append(normalize_history_message(raw, cid))
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("normalize_history failed cid=%s: %s", cid, exc)
                if events:
                    logger.info(
                        "SYNC BACKFILL cid=%s +%d (store %d→%d)",
                        cid,
                        len(events),
                        last_seen,
                        max_id,
                    )
                for ev in events:
                    broadcast("message", ev)
                    _schedule_auto_reply(ev)
                seen[cid] = max_id

            if not bootstrapped:
                bootstrapped = True
                logger.info("SYNC bootstrapped %d chats", len(seen))
                last_ids = tuple(sorted(seen.keys()))
            tick += 1
            # 仅当会话集合变化时推快照（新会话实时进列表）；消息走 WS/message，不靠这里刷
            ids = tuple(sorted(seen.keys()))
            if ids != last_ids:
                last_ids = ids
                broadcast("chats", {"chats": summaries})
        except Exception as exc:  # noqa: BLE001
            logger.warning("sync_loop error: %s", exc)
        time.sleep(1)


# ---------- 媒体代理 ----------

def sniff_content_type(data: bytes, kind: str = "") -> str:
    """按文件头嗅探 MIME（CDN 常把音频/视频标成 application/octet-stream）。"""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"GIF8":
        return "image/gif"
    if len(data) > 12 and data[4:8] == b"ftyp":
        return "audio/mp4" if kind == "audio" else "video/mp4"
    if data[:3] == b"ID3":
        return "audio/mpeg"
    if kind == "audio":
        return "audio/mp4"
    if kind == "image":
        return "image/jpeg"
    return "application/octet-stream"


@app.route("/api/media")
def api_media():
    """代理小红书 CDN 媒体，返回正确 Content-Type，解决语音/视频无法播放。"""
    url = str(request.args.get("url") or "")
    kind = str(request.args.get("kind") or "")
    if not url or not url.startswith("http"):
        return jsonify({"error": "bad url"}), 400
    headers = {
        "User-Agent": DEFAULT_UA,
        "Referer": "https://www.xiaohongshu.com/",
        "Accept": "*/*",
    }
    try:
        r = requests.get(url, headers=headers, timeout=25)
        r.raise_for_status()
        data = r.content
        ctype = sniff_content_type(data, kind)
        resp = Response(data, mimetype=ctype)
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp
    except Exception as exc:  # noqa: BLE001
        logger.warning("media proxy failed kind=%s url=%s err=%s", kind, url, exc)
        return jsonify({"error": str(exc)}), 502


# ---------- HTTP API ----------

@app.route("/")
def index():
    resp = send_from_directory(os.path.join(BASE_DIR, "static"), "index.html")
    # 禁止缓存，确保前端每次刷新都拿到最新代码
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/api/me")
def api_me():
    return jsonify(STATE["me"])


def load_chats() -> List[Dict[str, Any]]:
    """拉会话列表并更新缓存，返回精简 chats。"""
    client = STATE["client"]
    data = im_mod.list_chats(client, limit=100)
    chats = [
        _chat_summary(ch)
        for ch in (data.get("chats") or [])
        if ch.get("chat_user_id")
    ]
    STATE["chats_cache"] = chats
    return chats


@app.route("/api/chats")
def api_chats():
    return jsonify({"chats": load_chats()})


@app.route("/api/messages")
def api_messages():
    client = STATE["client"]
    chat_user_id = str(request.args.get("chat_user_id") or "")
    limit = int(request.args.get("limit") or 50)
    if not chat_user_id:
        return jsonify({"error": "chat_user_id required"}), 400
    # 每次实时刷新会话缓存，保证 max_store_id 是最新的（否则最新消息会被漏拉）
    try:
        load_chats()
    except Exception as exc:  # noqa: BLE001
        logger.warning("load_chats failed: %s", exc)
    max_store_id = 0
    for ch in STATE["chats_cache"]:
        if ch["chat_user_id"] == chat_user_id:
            max_store_id = int(ch.get("max_store_id") or 0)
            break
    if max_store_id <= 0:
        return jsonify({"messages": [], "error": "unknown max_store_id"})
    try:
        raw_msgs = im_mod.fetch_recent_history(
            client,
            chat_user_id,
            max_store_id=max_store_id,
            limit=limit,
            page_size=30,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("fetch history failed")
        return jsonify({"error": str(exc)}), 500
    out = []
    for m in raw_msgs:
        out.append(normalize_history_message(m, chat_user_id))
    return jsonify({"messages": out})


@app.route("/api/send", methods=["POST"])
def api_send():
    client = STATE["client"]
    body = request.get_json(silent=True) or {}
    to = str(body.get("to") or "").strip()
    text = str(body.get("text") or "").strip()
    if not to or not text:
        return jsonify({"error": "to and text required"}), 400
    try:
        chat_user_id, peer_name = im_mod.resolve_chat_target(
            client, to, chat_limit=100
        )
        result = im_mod.send_text(client, chat_user_id, text, peer_name=peer_name)
        ok = bool(result)
        mid = str((result or {}).get("message_id") or "")
        # send_text_ws 返回的 message_id 是客户端 uuid，非服务端真实入库 id。
        # 发送成功后从历史里查真实 id 返回，前端乐观插入用真实 id 才能与服务端对齐去重。
        real_mid = mid
        if ok:
            try:
                load_chats()
                max_store_id = 0
                for ch in STATE["chats_cache"]:
                    if ch["chat_user_id"] == chat_user_id:
                        max_store_id = int(ch.get("max_store_id") or 0)
                        break
                if max_store_id > 0:
                    my_uid = str(STATE["me"].get("user_id") or "")
                    hist = im_mod.fetch_recent_history(
                        client, chat_user_id, max_store_id=max_store_id, limit=5, page_size=30
                    )
                    for m in reversed(hist or []):
                        if str(m.get("sender_id") or "") != my_uid:
                            continue
                        t, _, _ = parse_raw_content(m.get("content"))
                        if t and t.strip() == text.strip():
                            real_mid = str(m.get("id") or "")
                            break
            except Exception as exc:  # noqa: BLE001
                logger.warning("resolve real mid failed: %s", exc)
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as exc:  # noqa: BLE001
        logger.exception("send failed")
        return jsonify({"error": str(exc)}), 500
    return jsonify({
        "ok": ok,
        "chat_user_id": chat_user_id,
        "peer": peer_name,
        "message_id": real_mid,
        "time": now_str,
    })


@app.route("/api/stream")
def api_stream():
    q: queue.Queue = queue.Queue(maxsize=200)
    with SUBS_LOCK:
        SUBS.append(q)

    def gen():
        try:
            yield f"event: hello\ndata: {json.dumps(STATE['me'], ensure_ascii=False)}\n\n"
            while True:
                try:
                    item = q.get(timeout=15)
                    yield item
                except queue.Empty:
                    # 真正的 ping 事件（而非注释行）：供前端看门狗判断连接活性
                    yield f"event: ping\ndata: {int(time.time() * 1000)}\n\n"
        finally:
            with SUBS_LOCK:
                if q in SUBS:
                    SUBS.remove(q)

    return Response(gen(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


# ---------- 启动 ----------

def _bootstrap_client(
    *,
    cookie: str = "",
    account_name: str = "",
    nick: str = "",
) -> tuple[XhsClient, Dict[str, Any]]:
    if nick.strip():
        client, summary = im_mod.resolve_client_by_nick(nick.strip())
        return client, summary
    if cookie.strip():
        client = XhsClient(cookie=cookie, account_name=account_name)
    else:
        from boss_cli.xhs.credentials import load_xhs_cookie

        cred = load_xhs_cookie(account_name=account_name)
        client = XhsClient(cookie=cred.cookie, account_name=cred.name)
    summary = im_mod.account_summary(client)
    return client, summary


def serve_xhs_web(
    *,
    host: str = "127.0.0.1",
    port: int = 8767,
    cookie: str = "",
    account_name: str = "",
    nick: str = "",
    auto_reply: bool = True,
) -> None:
    """启动小红书私信网页版（阻塞直到进程退出）。"""
    auto_reply_mod.set_enabled(bool(auto_reply))
    client, summary = _bootstrap_client(
        cookie=cookie, account_name=account_name, nick=nick
    )
    STATE["client"] = client
    STATE["me"] = dict(summary or {})
    try:
        me = client.user_me()
        STATE["me"]["avatar"] = str(me.get("images") or me.get("imageb") or "")
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch my avatar failed: %s", exc)
    STATE["started"] = True
    threading.Thread(target=upstream_loop, daemon=True).start()
    threading.Thread(target=sync_loop, daemon=True).start()
    logger.info(
        "account=%s uid=%s auto_reply=%s",
        STATE["me"].get("nickname"),
        STATE["me"].get("user_id"),
        auto_reply_mod.is_enabled(),
    )
    logger.info("server: http://%s:%d", host, port)
    # Werkzeug 不适合 SSE 长连接；waitress 多线程承载流式与普通请求。
    from waitress import serve as waitress_serve

    waitress_serve(app, host=host, port=port, threads=16, channel_timeout=3600)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s"
    )
    parser = argparse.ArgumentParser(description="小红书私信网页版")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--account", default="")
    parser.add_argument("--nick", default="")
    parser.add_argument("--auto-reply", dest="auto_reply", action="store_true", default=True)
    parser.add_argument("--no-auto-reply", dest="auto_reply", action="store_false")
    args = parser.parse_args()
    serve_xhs_web(
        host=args.host,
        port=args.port,
        account_name=args.account,
        nick=args.nick,
        auto_reply=bool(args.auto_reply),
    )
