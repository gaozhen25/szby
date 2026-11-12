const state = {
  me: { uid: 0, name: "我", avatar: "" },
  conversations: [],
  total: 0,
  offset: 0,
  activeId: null,
  messages: [],
  nextCursor: null,
  hasMore: false,
  loadingOlder: false,
  threadCache: {},
  sendCred: { ready: false, missing: [] },
  sending: false,
  mqtt: "",
};

const threadInflight = new Map();

const el = {
  list: document.getElementById("conv-list"),
  loadMore: document.getElementById("load-more"),
  search: document.getElementById("search"),
  status: document.getElementById("mqtt-status"),
  empty: document.getElementById("chat-empty"),
  pane: document.getElementById("chat-pane"),
  peerAvatar: document.getElementById("peer-avatar"),
  peerName: document.getElementById("peer-name"),
  peerJob: document.getElementById("peer-job"),
  messages: document.getElementById("messages"),
  older: document.getElementById("load-older"),
  composer: document.getElementById("composer"),
  input: document.getElementById("input"),
  send: document.getElementById("send-btn"),
  back: document.getElementById("back-btn"),
  sendHint: document.getElementById("send-hint"),
};

function mediaUrl(url, extras = null) {
  if (!url && !(extras && extras.mid)) return "";
  if (url && String(url).startsWith("data:")) return url;
  const parts = [];
  if (url) parts.push(`u=${encodeURIComponent(url)}`);
  const meta = extras || {};
  if (meta.skey) parts.push(`skey=${encodeURIComponent(meta.skey)}`);
  if (meta.oid) parts.push(`oid=${encodeURIComponent(meta.oid)}`);
  if (meta.mid) parts.push(`mid=${encodeURIComponent(meta.mid)}`);
  return `/api/media?${parts.join("&")}`;
}

function imageMediaUrl(image) {
  if (!image) return "";
  const url = image.preview || image.origin || "";
  return mediaUrl(url, { skey: image.skey, oid: image.oid, mid: image.mid });
}

function audioMediaUrl(audio) {
  if (!audio || !audio.url) return "";
  return mediaUrl(audio.url, { mid: audio.mid });
}

function fileUrl(file, { download = false } = {}) {
  if (!file || !file.url) return "";
  const parts = [`u=${encodeURIComponent(file.url)}`];
  if (file.name) parts.push(`filename=${encodeURIComponent(file.name)}`);
  if (download) parts.push("dl=1");
  return `/api/media?${parts.join("&")}`;
}

function avatarUrl(url) {
  return mediaUrl(url);
}

function initial(name) {
  const text = String(name || "").trim();
  if (!text) return "?";
  if (/^用户\d{1,6}$/.test(text)) return "用";
  return text.slice(-1);
}

function renderAvatar(node, url, name) {
  node.innerHTML = "";
  if (url) {
    const img = document.createElement("img");
    img.alt = name || "";
    img.src = avatarUrl(url);
    img.addEventListener("error", () => {
      node.innerHTML = initial(name);
    });
    node.appendChild(img);
  } else {
    node.textContent = initial(name);
  }
}

function setStatus(kind, text) {
  el.status.textContent = text;
  el.status.className = "status " + (kind || "");
}

function filterMessagesForConv(friendId, messages) {
  return filterMsgsForConv(friendId, messages);
}

function dedupeConversationsByPeer(items) {
  const best = new Map();
  const rest = [];
  for (const item of items || []) {
    const peer = peerUidFromConv(item);
    if (!peer) {
      rest.push(item);
      continue;
    }
    const prev = best.get(peer);
    if (!prev) {
      best.set(peer, item);
      continue;
    }
    const prevReady = convReadyForList(prev) ? 1 : 0;
    const curReady = convReadyForList(item) ? 1 : 0;
    const prevTs = Number(prev.lastTs) || 0;
    const curTs = Number(item.lastTs) || 0;
    if (curReady > prevReady || (curReady === prevReady && curTs >= prevTs)) {
      best.set(peer, item);
    }
  }
  return [...best.values(), ...rest];
}

function visibleConversations() {
  const q = el.search.value.trim().toLowerCase();
  let items = dedupeConversationsByPeer(state.conversations.filter(convReadyForList));
  if (!q) return items;
  return items.filter((c) => `${c.name} ${c.job} ${c.lastMessage}`.toLowerCase().includes(q));
}

function convReadyForList(conv) {
  if (!conv || !isConversationId(conv.friendId)) return false;
  const uid = peerUidFromConv(conv);
  const name = String(conv.name || "").trim();
  const avatar = String(conv.avatar || "").trim();
  if (!uid || !avatar || !name) return false;
  if (looksLikePlaceholder(name, uid)) return false;
  if (isOwnDisplayName(name)) return false;
  return true;
}

function messageBelongsToConv(friendId, event) {
  const locked = peerUidFromConv({ friendId });
  const fromUid = uidStr(event.fromUid || (event.mine ? state.me.uid : event.uid));
  const myUid = uidStr(state.me.uid);
  if (!fromUid) return !locked;
  if (myUid && fromUid === myUid) return true;
  if (locked) return fromUid === locked;
  return true;
}

function renderList() {
  const items = visibleConversations();
  el.list.innerHTML = "";
  if (!items.length) {
    el.list.innerHTML = `<div class="empty">${state.conversations.length ? "没有匹配的会话" : "暂无会话"}</div>`;
  } else {
    for (const conv of items) {
      const row = document.createElement("div");
      row.className = "conv" + (String(conv.friendId) === String(state.activeId) ? " active" : "");
      row.dataset.id = conv.friendId;
      row.innerHTML = `
        <div class="avatar"></div>
        <div class="conv-body">
          <div class="conv-top">
            <div class="conv-name"></div>
            <div class="conv-time"></div>
          </div>
          <div class="conv-sub">
            <div class="conv-last"></div>
            ${conv.unread ? `<span class="unread">${conv.unread}</span>` : ""}
          </div>
        </div>`;
      row.querySelector(".conv-name").textContent = displayConvName(conv);
      row.querySelector(".conv-time").textContent = conv.lastTime || "";
      row.querySelector(".conv-last").textContent = conv.lastMessage || conv.job || "";
      renderAvatar(row.querySelector(".avatar"), conv.avatar, displayConvName(conv));
      row.addEventListener("click", () => openConversation(conv.friendId));
      el.list.appendChild(row);
    }
  }
  el.loadMore.hidden = !(state.offset < state.total);
}

function convPath(id) {
  return `/api/conversations/${encodeURIComponent(String(id))}/messages`;
}

async function notifyActive(friendId) {
  try {
    await fetch("/api/active", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversationId: friendId ? String(friendId) : "" }),
    });
  } catch (err) {
    console.debug(err);
  }
}

function cacheKey(id) {
  return String(id);
}

function getThreadCache(id) {
  return state.threadCache[cacheKey(id)] || null;
}

function setThreadCache(id, data) {
  if (!id || !data) return;
  const prev = getThreadCache(id) || {};
  const incomingSource = data.source || "";
  const source =
    incomingSource === "history" || prev.source === "history"
      ? "history"
      : (incomingSource || prev.source || "");
  state.threadCache[cacheKey(id)] = {
    messages: sortMessages(data.messages || []),
    hasMore: data.hasMore != null ? Boolean(data.hasMore) : Boolean(prev.hasMore),
    nextCursor: data.nextCursor !== undefined ? data.nextCursor : (prev.nextCursor ?? null),
    peer: data.peer || prev.peer || null,
    source,
    fetchedAt: data.fetchedAt != null ? data.fetchedAt : Date.now(),
  };
}

function messageRichness(m) {
  if (!m) return -1;
  let score = 0;
  if (m.pending) score -= 20;
  if (m.image && (m.image.preview || m.image.origin || m.image.mid || m.image.skey)) score += 8;
  if (m.audio && m.audio.url) score += 8;
  if (m.file && m.file.url) score += 4;
  if (m.resume) score += 2;
  if (m.kind && m.kind !== "text") score += 1;
  if (m.kind === "video" || m.kind === "card") score += 3;
  const t = String(m.text || "").trim();
  if (m.kind === "text" && (t === "分享" || t === "[分享]" || t === "[分享视频]" || t === "[分享图文]")) {
    score -= 6;
  }
  if (m.text) score += 1;
  return score;
}

function upgradeMessage(prev, next) {
  if (!prev) return next;
  if (!next) return prev;
  // Never merge two different messages (e.g. two [图片] with distinct mids).
  if (prev.mid && next.mid && String(prev.mid) !== String(next.mid)) return next;
  const base = messageRichness(next) >= messageRichness(prev) ? { ...prev, ...next } : { ...next, ...prev };
  // Prefer non-empty media fields from either side — only for the same message.
  if ((!base.image || !(base.image.preview || base.image.origin || base.image.mid)) && prev.image) {
    base.image = prev.image;
  }
  if ((!base.audio || !base.audio.url) && prev.audio) base.audio = prev.audio;
  if ((!base.file || !base.file.url) && prev.file) base.file = prev.file;
  if (next.image && prev.image) {
    base.image = { ...prev.image, ...next.image };
  }
  if (next.audio && prev.audio) base.audio = { ...prev.audio, ...next.audio };
  if (base.pending && !next.pending) base.pending = false;
  return base;
}

function isGenericMediaPlaceholder(text) {
  const t = String(text || "").trim();
  return (
    t === "[图片]"
    || t === "[表情]"
    || t === "[语音]"
    || t === "[视频]"
    || t === "[消息]"
    || t === "分享"
    || t === "[分享]"
    || t === "[分享视频]"
    || t === "[分享图文]"
  );
}

function mergeThreadMessages(existing, incoming) {
  // True union by mid; never drop confirmed locals when incoming is empty/partial.
  const byMid = new Map();
  const noMid = [];
  for (const m of existing || []) {
    if (!m) continue;
    const id = m.mid == null || m.mid === "" ? "" : String(m.mid);
    if (!id) {
      noMid.push(m);
      continue;
    }
    byMid.set(id, m);
  }
  for (const m of incoming || []) {
    if (!m) continue;
    const id = m.mid == null || m.mid === "" ? "" : String(m.mid);
    if (!id) {
      noMid.push(m);
      continue;
    }
    byMid.set(id, upgradeMessage(byMid.get(id), m));
  }
  return sortMessages([...byMid.values(), ...noMid]);
}

function filterMsgsForConv(friendId, list) {
  return (list || []).filter((m) => {
    if (!m) return false;
    return messageBelongsToConv(friendId, {
      fromUid: m.fromUid,
      uid: m.fromUid,
      mine: m.mine,
    });
  });
}

function applyThreadPayload(friendId, data, { toView = true, merge = false } = {}) {
  const conv = findConv(friendId) || { friendId, name: String(friendId) };
  if (data.peer) {
    const locked = peerUidFromConv({ friendId });
    const peerUid = String(data.peer.uid || "").trim();
    // 拒绝把别的会话 peer 写进本会话（防串名/串头像）。
    if (!peerUid || !locked || peerUid === locked || peerUid === String(state.me.uid || "")) {
      applyPeerIdentity(conv, { ...data.peer, uid: locked || peerUid }, { trusted: true });
      if (locked) conv.uid = locked;
      if (String(state.activeId) === cacheKey(friendId)) {
        syncActiveHeader(conv);
      }
    }
  }
  const key = cacheKey(friendId);
  const prev = getThreadCache(friendId);
  // 只合并「本会话」缓存，绝不用 state.messages（切换会话后可能仍是上一个聊天）。
  const local = filterMsgsForConv(friendId, prev?.messages || []);
  let messages = filterMsgsForConv(friendId, sortMessages(data.messages || []));
  const incomingEmpty = !messages.length;
  const source = data.source || "";
  if (source === "history" && !incomingEmpty) {
    // 历史是权威来源：丢掉已串入的旧缓存，只保留未发送成功的 pending。
    const pending = local.filter((m) => m && m.pending);
    messages = mergeThreadMessages(messages, pending);
  } else if (incomingEmpty && local.length) {
    messages = local;
  } else if (local.length) {
    messages = mergeThreadMessages(local, messages);
  }
  const nextSource = source === "history" || prev?.source === "history" ? "history" : (source || prev?.source || "");
  // hasMore：本地已有更多时不要被短包打成 false；history 包可更新游标。
  let hasMore = data.hasMore;
  if (hasMore == null) hasMore = prev?.hasMore;
  if (local.length > (data.messages || []).length && hasMore === false && nextSource !== "history") {
    hasMore = prev?.hasMore ?? true;
  }
  setThreadCache(friendId, {
    ...data,
    messages,
    hasMore,
    nextCursor: data.nextCursor !== undefined ? data.nextCursor : prev?.nextCursor,
    source: nextSource,
    peer: data.peer || prev?.peer || null,
    fetchedAt: Date.now(),
  });
  if (toView && String(state.activeId) === key) {
    const nearBottom =
      el.messages.scrollHeight - el.messages.scrollTop - el.messages.clientHeight < 120;
    state.messages = messages;
    if (!incomingEmpty || data.hasMore != null) {
      state.hasMore = Boolean(hasMore);
      state.nextCursor = data.nextCursor !== undefined ? data.nextCursor : (state.nextCursor ?? null);
    }
    renderMessages({ stickToBottom: nearBottom || merge || source === "history" });
  }
  renderList();
}

async function fetchThread(friendId, { silent = false, merge = false } = {}) {
  const key = cacheKey(friendId);
  if (threadInflight.has(key)) return threadInflight.get(key);
  const task = (async () => {
    const resp = await fetch(`${convPath(friendId)}?count=40`);
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error?.message || "加载失败");
    applyThreadPayload(friendId, data.data, {
      toView: String(state.activeId) === key,
      merge: silent || merge,
    });
    return data.data;
  })().finally(() => {
    threadInflight.delete(key);
  });
  threadInflight.set(key, task);
  if (!silent && String(state.activeId) === key && !getThreadCache(friendId)?.messages?.length) {
    el.messages.innerHTML = `<div class="empty">正在加载聊天…</div>`;
  }
  return task;
}

function findConvByFriendId(friendId) {
  const id = String(friendId || "").trim();
  if (!id) return null;
  return state.conversations.find((c) => String(c.friendId) === id) || null;
}

function isConversationId(value) {
  return /^0:\d+:\d+:\d+/.test(String(value || "").trim());
}

function findConv(id) {
  const key = String(id || "").trim();
  if (!key) return null;
  // BOSS-stable: friendId (会话 id) 是主键；避免用 peer uid 误匹配其它会话。
  const byFid = findConvByFriendId(key);
  if (byFid) return byFid;
  if (isConversationId(key)) return null;
  const matches = state.conversations.filter((c) => String(c.uid || "") === key);
  if (matches.length === 1) return matches[0];
  // 多个会话共享同一 uid 时不猜测，避免串写 lastMessage。
  return null;
}

function isOwnDisplayName(name) {
  const mine = String(state.me.name || "").trim();
  const text = String(name || "").trim();
  if (!mine || !text) return false;
  if (text === mine) return true;
  const myUid = String(state.me.uid || "").trim();
  if (myUid && text === myUid) return true;
  return false;
}

function isMyAvatar(url) {
  const mine = String(state.me.avatar || "").trim();
  const target = String(url || "").trim();
  if (!mine || !target) return false;
  if (mine === target) return true;
  try {
    const a = new URL(mine, location.origin);
    const b = new URL(target, location.origin);
    return a.pathname === b.pathname;
  } catch (_) {
    return false;
  }
}

function isSelfPeer(partial) {
  if (!partial) return false;
  const myUid = String(state.me.uid || "").trim();
  const uid = String(partial.uid || "").trim();
  if (myUid && uid && uid === myUid) return true;
  if (isOwnDisplayName(partial.name)) return true;
  if (partial.avatar && isMyAvatar(partial.avatar)) return true;
  return false;
}

function looksLikeConversationId(text) {
  return /^0:\d+:\d+:\d+/.test(String(text || "").trim());
}

function displayConvName(conv) {
  if (!conv) return "未知";
  const name = String(conv.name || "").trim();
  const uid = String(conv.uid || "").trim();
  const job = String(conv.job || "").trim();
  if (name && !looksLikePlaceholder(name, uid)) return name;
  if (job && !looksLikePlaceholder(job, uid)) return job;
  if (name && name !== uid && !/^用户\d+$/.test(name) && !looksLikeConversationId(name)) return name;
  if (uid) return uid.length >= 4 ? `用户${uid.slice(-4)}` : uid;
  if (name) return name;
  return "新会话";
}

function looksLikePlaceholder(name, uid = "") {
  const text = String(name || "").trim();
  const peerUid = String(uid || "").trim();
  if (!text) return true;
  if (text === "加载中…" || text === "加载中..." || text === "新会话" || text === "未知") return true;
  if (/^用户\d{1,6}$/.test(text)) return true;
  if (looksLikeConversationId(text)) return true;
  if (peerUid && text === peerUid) return true;
  if (/^\d+\(\d+\)$/.test(text)) return true;
  // Short digit nicknames (e.g. 9277) are real; long digit strings matching uid are not.
  if (/^\d+$/.test(text)) {
    if (peerUid && text === peerUid) return true;
    if (peerUid && text.length >= 10 && text.length === peerUid.length) return true;
    if (!peerUid && text.length >= 12) return true;
    return false;
  }
  return false;
}

function peerPatch(partial) {
  if (!partial || partial.mine || isSelfPeer(partial)) {
    return {
      ...partial,
      name: undefined,
      avatar: undefined,
    };
  }
  const patch = { ...partial };
  if (patch.avatar && isMyAvatar(patch.avatar)) {
    patch.avatar = undefined;
  }
  if (patch.name && isOwnDisplayName(patch.name)) {
    patch.name = undefined;
  }
  return patch;
}

function applyPeerIdentity(conv, partial, { trusted = false } = {}) {
  if (!conv || !partial) return;
  if (partial.mine || isSelfPeer(partial)) {
    if (partial.lastMessage) conv.lastMessage = partial.lastMessage;
    if (partial.lastTime || partial.time) conv.lastTime = partial.lastTime || partial.time;
    return;
  }
  const incoming = String(partial.name || "").trim();
  const job = String(partial.job || "").trim();
  const uid = String(partial.uid || conv.uid || "").trim();
  if (uid && String(state.me.uid || "") && uid === String(state.me.uid)) return;
  const safe = incoming && !isOwnDisplayName(incoming) && !looksLikePlaceholder(incoming, uid);
  if (safe && (trusted || looksLikePlaceholder(conv.name, conv.uid) || isOwnDisplayName(conv.name) || looksLikeConversationId(conv.name))) {
    conv.name = incoming;
  } else if (
    job
    && !looksLikePlaceholder(job, uid)
    && (looksLikePlaceholder(conv.name, conv.uid) || !conv.name || conv.name === "加载中…" || conv.name === "新会话" || isOwnDisplayName(conv.name))
  ) {
    conv.name = job;
  }
  if (partial.avatar && !isMyAvatar(partial.avatar)) conv.avatar = partial.avatar;
  if (partial.job) conv.job = partial.job;
  if (partial.uid && partial.uid !== String(state.me.uid || "")) conv.uid = partial.uid;
  // Scrub if somehow polluted
  if (isOwnDisplayName(conv.name)) conv.name = displayConvName({ ...conv, name: "" });
  if (conv.avatar && isMyAvatar(conv.avatar)) conv.avatar = "";
}

function upsertConv(partial) {
  let friendId = String(partial.friendId || "").trim();
  const lockedUid = isConversationId(friendId) ? peerUidFromConv({ friendId }) : "";
  const peerUid = String(partial.uid || lockedUid || "").trim();
  const patch = peerPatch(partial);
  if (lockedUid) patch.uid = lockedUid;

  // 严禁用裸 uid 当会话主键，否则会和真正的 0:1:… 会话串写预览/身份。
  if (friendId && !isConversationId(friendId)) {
    const hit = state.conversations.find((c) => (
      isConversationId(c.friendId)
      && (String(c.uid || "") === friendId || (peerUid && String(c.uid || "") === peerUid))
    ));
    if (hit) friendId = String(hit.friendId);
    else return;
  }
  if (!friendId || !isConversationId(friendId)) return;

  let existing = findConvByFriendId(friendId);
  // 若列表里还有同 peer 的裸 uid 脏行，清掉以免点开会串。
  if (peerUid) {
    state.conversations = state.conversations.filter((c) => {
      if (isConversationId(c.friendId)) return true;
      return String(c.friendId || "") !== peerUid && String(c.uid || "") !== peerUid;
    });
  }
  const canTouchPreview = Boolean(partial.lastMessage);
  if (existing) {
    if (lockedUid) existing.uid = lockedUid;
    // 事件里的 uid 必须属于该会话，否则忽略身份补丁（防串名/串头像）。
    const expectedUid = lockedUid || peerUidFromConv(existing);
    const incomingUid = String(patch.uid || peerUid || "").trim();
    if (
      incomingUid
      && expectedUid
      && incomingUid !== expectedUid
      && incomingUid !== String(state.me.uid || "")
      && !partial.trusted
    ) {
      if (canTouchPreview) {
        existing.lastMessage = partial.lastMessage;
        existing.lastTime = partial.lastTime || partial.time || existing.lastTime;
        existing.lastTs = partial.lastTs || Date.now();
        state.conversations = [existing, ...state.conversations.filter((c) => c !== existing)];
      }
      return;
    }
    if (partial.trusted && incomingUid && incomingUid !== String(state.me.uid || "")) {
      existing.uid = incomingUid;
    }
    applyPeerIdentity(existing, patch, { trusted: Boolean(partial.trusted) });
    if (canTouchPreview) existing.lastMessage = partial.lastMessage;
    if (partial.lastTime || partial.time) existing.lastTime = partial.lastTime || partial.time;
    if (partial.lastTs) existing.lastTs = partial.lastTs;
    else if (canTouchPreview) existing.lastTs = Date.now();
    if (patch.uid && patch.uid !== String(state.me.uid || "")) existing.uid = patch.uid;
    existing.friendId = friendId;
    if (typeof partial.unread === "number") existing.unread = partial.unread;
    if (canTouchPreview) {
      state.conversations = [existing, ...state.conversations.filter((c) => c !== existing)];
    }
  } else {
    const row = {
      friendId,
      uid: lockedUid || (patch.uid || peerUid || "").trim(),
      name: displayConvName({ name: patch.name, uid: patch.uid || peerUid, job: patch.job }),
      job: patch.job || "",
      avatar: patch.avatar && !isMyAvatar(patch.avatar) ? patch.avatar : "",
      lastMessage: canTouchPreview ? (partial.lastMessage || partial.text || "") : "",
      lastTime: partial.lastTime || partial.time || "",
      lastTs: partial.lastTs || (canTouchPreview ? Date.now() : 0),
      unread: partial.mine ? 0 : 1,
    };
    applyPeerIdentity(row, patch, { trusted: Boolean(partial.trusted) });
    state.conversations.unshift(row);
  }
}

function sortMessages(list) {
  return list.slice().sort((a, b) => {
    const ts = (Number(a.ts) || 0) - (Number(b.ts) || 0);
    if (ts) return ts;
    return (Number(a.mid) || 0) - (Number(b.mid) || 0);
  });
}

function mergeMessages(existing, incoming) {
  const seen = new Set(existing.map((m) => (m.mid == null ? "" : String(m.mid))).filter(Boolean));
  const extra = incoming.filter((m) => m.mid == null || !seen.has(String(m.mid)));
  return sortMessages(existing.concat(extra));
}

function textEl(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = text || "";
  return node;
}

function renderImageBubble(bubble, msg, { emoji = false } = {}) {
  if (!msg.image) return false;
  const hasSrc = Boolean(
    msg.image.preview
    || msg.image.origin
    || msg.image.mid
    || (msg.image.skey && msg.image.oid)
  );
  if (!hasSrc) return false;
  bubble.classList.add("bubble-media");
  if (emoji) bubble.classList.add("bubble-emoji");
  const src = imageMediaUrl(msg.image);
  if (!src) return false;
  const link = document.createElement("a");
  link.href = src;
  link.target = "_blank";
  link.rel = "noopener";
  const img = document.createElement("img");
  img.className = emoji ? "chat-emoji" : "chat-image";
  img.alt = msg.text || (emoji ? "表情" : "图片");
  img.loading = "eager";
  img.decoding = "async";
  img.src = src;
  let retried = false;
  img.addEventListener("error", () => {
    if (!retried && msg.image && (msg.image.skey || msg.image.mid || msg.image.oid)) {
      retried = true;
      const again = mediaUrl("", {
        skey: msg.image.skey,
        oid: msg.image.oid,
        mid: msg.image.mid,
      });
      if (again) {
        img.src = `${again}${again.includes("?") ? "&" : "?"}r=${Date.now()}`;
        return;
      }
    }
    img.replaceWith(textEl("div", "", msg.text || (emoji ? "[表情]" : "[图片]")));
  });
  link.appendChild(img);
  bubble.appendChild(link);
  if (!emoji && msg.text && msg.text !== "[图片]" && msg.text !== "[表情]") {
    bubble.appendChild(textEl("div", "media-caption", msg.text));
  }
  return true;
}

function renderBubbleContent(bubble, msg) {
  const kind = msg.kind || "text";
  // kind=image but missing image object: still try mid-only proxy.
  if ((kind === "image" || kind === "emoji") && !msg.image && msg.mid) {
    msg = { ...msg, image: { mid: String(msg.mid) } };
  }
  if ((kind === "image" || kind === "emoji") && renderImageBubble(bubble, msg, { emoji: kind === "emoji" })) {
    return;
  }
  if (kind === "video" || kind === "card") {
    bubble.classList.add("bubble-media");
    const card = document.createElement("a");
    card.className = "share-card";
    const href = (msg.file && msg.file.url) || (msg.image && msg.image.origin) || "";
    if (href) {
      card.href = href.startsWith("http") ? href : mediaUrl(href);
      card.target = "_blank";
      card.rel = "noopener";
    } else {
      card.href = "#";
      card.addEventListener("click", (e) => e.preventDefault());
      card.classList.add("share-card-pending");
    }
    if (msg.image && (msg.image.preview || msg.image.origin)) {
      const img = document.createElement("img");
      img.className = "chat-image";
      img.alt = msg.text || "分享";
      img.src = imageMediaUrl(msg.image);
      img.addEventListener("error", () => {
        img.remove();
      });
      card.appendChild(img);
    }
    const title = textEl("div", "share-title", msg.text || msg.file?.name || "[分享]");
    card.appendChild(title);
    bubble.appendChild(card);
    return;
  }
  if (kind === "voice") {
    const wrap = document.createElement("div");
    wrap.className = "voice-card";
    const label = textEl("span", "voice-label", msg.text || "[语音]");
    const audioSrc = msg.audio && (msg.audio.url || msg.audio.mid)
      ? (msg.audio.url ? audioMediaUrl(msg.audio) : mediaUrl("", { mid: msg.audio.mid }))
      : "";
    if (audioSrc) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "voice-play";
      btn.textContent = "▶";
      const audio = document.createElement("audio");
      audio.preload = "none";
      audio.src = audioSrc;
      btn.addEventListener("click", () => {
        if (audio.paused) {
          audio.play().catch(() => {});
          btn.textContent = "❚❚";
        } else {
          audio.pause();
          btn.textContent = "▶";
        }
      });
      audio.addEventListener("ended", () => {
        btn.textContent = "▶";
      });
      wrap.appendChild(btn);
      wrap.appendChild(audio);
    }
    wrap.appendChild(label);
    bubble.appendChild(wrap);
    return;
  }
  if ((kind === "pdf" || kind === "file") && msg.file && msg.file.url) {
    bubble.classList.add("bubble-media");
    const isPdf = kind === "pdf" || (msg.file.name || "").toLowerCase().endsWith(".pdf") || (msg.file.mime || "").includes("pdf");
    const card = document.createElement("div");
    card.className = "file-card";
    card.appendChild(textEl("div", "file-icon", isPdf ? "PDF" : "DOC"));
    const meta = document.createElement("div");
    meta.className = "file-meta";
    meta.appendChild(textEl("div", "file-name", msg.file.name || (isPdf ? "文件.pdf" : "附件")));
    meta.appendChild(textEl("div", "file-sub", msg.text || (isPdf ? "PDF 文件" : "点击下载后打开")));
    card.appendChild(meta);
    const actions = document.createElement("div");
    actions.className = "file-actions";
    const open = document.createElement("a");
    open.className = "file-link";
    open.href = fileUrl(msg.file, { download: !isPdf });
    open.target = "_blank";
    open.rel = "noopener";
    open.textContent = isPdf ? "打开" : "下载";
    actions.appendChild(open);
    if (isPdf) {
      const save = document.createElement("a");
      save.className = "file-link";
      save.href = fileUrl(msg.file, { download: true });
      save.textContent = "下载";
      actions.appendChild(save);
    }
    card.appendChild(actions);
    bubble.appendChild(card);
    return;
  }
  if ((kind === "resume" || msg.resume) && msg.resume) {
    bubble.classList.add("bubble-media");
    const card = document.createElement("div");
    card.className = "resume-card";
    const head = document.createElement("div");
    head.className = "resume-head";
    const av = document.createElement("div");
    av.className = "resume-avatar";
    renderAvatar(av, msg.resume.avatar, msg.resume.name);
    const meta = document.createElement("div");
    meta.appendChild(textEl("div", "resume-name", msg.resume.name || "候选人"));
    const sub = [msg.resume.age, msg.resume.workYear, msg.resume.education, msg.resume.city].filter(Boolean).join(" · ");
    if (sub) meta.appendChild(textEl("div", "resume-sub", sub));
    head.appendChild(av);
    head.appendChild(meta);
    card.appendChild(head);
    if (msg.resume.position) card.appendChild(textEl("div", "resume-line", msg.resume.position));
    if (msg.resume.expect) card.appendChild(textEl("div", "resume-line", msg.resume.expect));
    if (msg.resume.school) card.appendChild(textEl("div", "resume-line muted", msg.resume.school));
    if (msg.resume.salary || msg.resume.status) {
      card.appendChild(textEl("div", "resume-line", [msg.resume.salary, msg.resume.status].filter(Boolean).join(" · ")));
    }
    if (msg.resume.footer) card.appendChild(textEl("div", "resume-foot", msg.resume.footer));
    const pdfUrl = msg.resume.pdfUrl || (msg.file && msg.file.url);
    if (pdfUrl) {
      const actions = document.createElement("div");
      actions.className = "file-actions";
      const file = msg.file || { url: pdfUrl, name: "简历.pdf" };
      const open = document.createElement("a");
      open.className = "file-link";
      open.href = fileUrl(file, { download: false });
      open.target = "_blank";
      open.rel = "noopener";
      open.textContent = "打开 PDF";
      const save = document.createElement("a");
      save.className = "file-link";
      save.href = fileUrl(file, { download: true });
      save.textContent = "下载";
      actions.appendChild(open);
      actions.appendChild(save);
      card.appendChild(actions);
    } else {
      card.appendChild(textEl("div", "resume-tag", msg.resume.title || "在线简历"));
    }
    bubble.appendChild(card);
    return;
  }
  bubble.textContent = msg.text || "";
}

function uidStr(value) {
  const text = String(value ?? "").trim();
  return text && text !== "0" ? text : "";
}

function peerUidFromConv(conv) {
  const uid = uidStr(conv.uid);
  if (uid && !uid.includes(":")) return uid;
  const fid = uidStr(conv.friendId);
  if (fid.includes(":")) {
    const parts = fid.split(":");
    if (parts.length >= 4) {
      const myUid = uidStr(state.me.uid);
      const left = uidStr(parts[2]);
      const right = uidStr(parts[3]);
      if (myUid && left === myUid) return right;
      if (myUid && right === myUid) return left;
      return right || left;
    }
  }
  return uid || "";
}

function isMine(msg) {
  if (msg.mine === true) return true;
  if (msg.mine === false) return false;
  const fromUid = uidStr(msg.fromUid);
  const myUid = uidStr(state.me.uid);
  const peerUid = peerUidFromConv(findConv(state.activeId) || {});
  if (myUid && fromUid === myUid) return true;
  if (peerUid && fromUid === peerUid) return false;
  return false;
}

function scrollMessagesToBottom() {
  el.messages.scrollTop = el.messages.scrollHeight;
  requestAnimationFrame(() => {
    el.messages.scrollTop = el.messages.scrollHeight;
  });
}

function renderMessages({ stickToBottom = true } = {}) {
  const prevHeight = el.messages.scrollHeight;
  el.messages.innerHTML = "";
  let lastStamp = "";
  for (const msg of state.messages) {
    if (msg.time && msg.time !== lastStamp) {
      const stamp = document.createElement("div");
      stamp.className = "msg-time";
      stamp.textContent = msg.time;
      el.messages.appendChild(stamp);
      lastStamp = msg.time;
    }
    const conv = findConv(state.activeId) || {};
    const mine = isMine(msg);
    const row = document.createElement("div");
    row.className = "row" + (mine ? " mine" : "");
    const av = document.createElement("div");
    av.className = "bubble-avatar";
    const peerName = displayConvName(conv) || msg.name || "";
    const peerAvatar = conv.avatar || msg.avatar || "";
    if (mine) {
      renderAvatar(av, state.me.avatar || msg.avatar, state.me.name);
    } else {
      renderAvatar(av, peerAvatar, peerName);
    }
    const stack = document.createElement("div");
    stack.className = "bubble-stack";
    if (!mine && peerName) {
      stack.appendChild(textEl("div", "bubble-name", peerName));
    }
    const bubble = document.createElement("div");
    bubble.className = "bubble" + (msg.pending ? " pending" : "");
    renderBubbleContent(bubble, msg);
    stack.appendChild(bubble);
    row.appendChild(av);
    row.appendChild(stack);
    el.messages.appendChild(row);
  }
  el.older.hidden = !state.hasMore;
  if (stickToBottom) {
    // Caller decided to stick; always go to bottom (open chat / live append).
    // Images may grow height after load — nudge again on each media load once.
    scrollMessagesToBottom();
    el.messages.querySelectorAll("img").forEach((img) => {
      if (img.complete) return;
      img.addEventListener("load", scrollMessagesToBottom, { once: true });
    });
  } else {
    el.messages.scrollTop = el.messages.scrollHeight - prevHeight;
  }
}

async function loadMe() {
  const resp = await fetch("/api/me");
  const data = await resp.json();
  if (!data.ok) throw new Error(data.error?.message || "无法获取当前用户");
  state.me = data.data.me || state.me;
  state.sendCred = data.data.sendCred || state.sendCred;
  state.mqtt = data.data.mqtt || state.mqtt;
  refreshStatusBar();
}

function refreshStatusBar() {
  const cred = state.sendCred || {};
  if (!cred.ready) {
    const miss = (cred.missing || []).join(",") || "ticket";
    setStatus("bad", `缺发信凭据 ${miss}`);
    if (el.sendHint) {
      el.sendHint.hidden = false;
      el.sendHint.textContent = "发信凭据未就绪：请运行 boss douyin grab-ticket --qr";
    }
    return;
  }
  if (el.sendHint) el.sendHint.hidden = true;
  setMqtt(state.mqtt);
}

function setMqtt(status) {
  state.mqtt = status || state.mqtt;
  if (state.sendCred && state.sendCred.ready === false) {
    refreshStatusBar();
    return;
  }
  if (status === "online" || status === "polling") setStatus("online", "实时在线 · 发信就绪");
  else if (status === "reconnecting") setStatus("bad", "重连中");
  else if (status === "stopped") setStatus("bad", "已断开");
  else setStatus("", "连接中");
}

async function loadConversations({ reset = false } = {}) {
  const offset = reset ? 0 : state.offset;
  const scope = "all";
  const limit = 100;
  const resp = await fetch(`/api/conversations?offset=${offset}&limit=${limit}&scope=${scope}`);
  const data = await resp.json();
  if (!data.ok) {
    el.list.innerHTML = `<div class="empty">${data.error?.message || "加载失败"}</div>`;
    return;
  }
  const page = (data.data.conversations || []).filter((c) => isConversationId(c.friendId));
  state.total = data.data.total || page.length;
  if (reset) {
    state.threadCache = {};
    const prev = new Map(state.conversations.map((c) => [String(c.friendId), c]));
    const merged = page.map((item) => {
      const old = prev.get(String(item.friendId));
      if (!old) return item;
      const keepName = looksLikePlaceholder(item.name, item.uid) && !looksLikePlaceholder(old.name, old.uid);
      return {
        ...item,
        name: keepName ? old.name : item.name,
        avatar: item.avatar || old.avatar || "",
        job: item.job || old.job || "",
        lastMessage: item.lastMessage || old.lastMessage || "",
        lastTime: item.lastTime || old.lastTime || "",
        lastTs: item.lastTs || old.lastTs || 0,
      };
    });
    const seen = new Set(merged.map((c) => String(c.friendId)));
    for (const old of prev.values()) {
      if (seen.has(String(old.friendId))) continue;
      const isActive = state.activeId && String(old.friendId) === String(state.activeId);
      const isLive = Number(old.lastTs || 0) > 0 || Boolean(old.lastMessage);
      if ((isActive || isLive) && convReadyForList(old)) {
        merged.push(old);
        seen.add(String(old.friendId));
      }
    }
    merged.sort((a, b) => (Number(b.lastTs) || 0) - (Number(a.lastTs) || 0));
    state.conversations = dedupeConversationsByPeer(merged);
  } else {
    const seen = new Set(state.conversations.map((c) => String(c.friendId)));
    for (const item of page) {
      if (!seen.has(String(item.friendId))) state.conversations.push(item);
    }
  }
  state.offset = data.data.nextOffset == null ? state.total : data.data.nextOffset;
  renderList();
}

async function openConversation(friendId) {
  const prevId = state.activeId;
  state.activeId = friendId;
  const conv = findConv(friendId) || { friendId, name: String(friendId) };
  if (conv.unread) conv.unread = 0;
  document.querySelector(".app").classList.add("chat-open");
  el.empty.hidden = true;
  el.pane.hidden = false;
  el.peerName.textContent = displayConvName(conv);
  el.peerJob.textContent = [conv.job, conv.salary].filter(Boolean).join(" · ");
  renderAvatar(el.peerAvatar, conv.avatar, displayConvName(conv));
  renderList();

  const cached = getThreadCache(friendId);
  const cachedMsgs = filterMsgsForConv(friendId, cached?.messages || []);

  // 切换会话时立刻清空上一个聊天的消息，避免 merge 串写。
  if (String(prevId || "") !== String(friendId)) {
    state.messages = [];
    state.hasMore = false;
    state.nextCursor = null;
  }

  // Always paint THIS conversation's cache first (never the previous chat).
  if (cachedMsgs.length) {
    if (cached.peer) {
      const locked = peerUidFromConv(conv);
      const peerUid = String(cached.peer.uid || "").trim();
      if (!peerUid || !locked || peerUid === locked) {
        applyPeerIdentity(conv, { ...cached.peer, uid: locked || peerUid }, { trusted: true });
      }
      el.peerName.textContent = displayConvName(conv);
      el.peerJob.textContent = [conv.job, conv.salary].filter(Boolean).join(" · ");
      renderAvatar(el.peerAvatar, conv.avatar, displayConvName(conv));
    }
    state.messages = cachedMsgs.map((m) => ({ ...m }));
    state.hasMore = cached.hasMore;
    state.nextCursor = cached.nextCursor;
    renderMessages({ stickToBottom: true });
    el.input.focus();
    void notifyActive(friendId);
    // Background refresh; merge only against this friend's threadCache.
    void fetchThread(friendId, { silent: true, merge: true });
    return;
  }

  renderMessages({ stickToBottom: true });
  try {
    await fetchThread(friendId, { silent: false, merge: true });
  } catch (err) {
    if (!getThreadCache(friendId)?.messages?.length) {
      el.messages.innerHTML = `<div class="empty">${err.message || "加载失败"}</div>`;
    }
  } finally {
    void notifyActive(friendId);
    el.input.focus();
  }
}

async function loadOlder() {
  if (!state.activeId || !state.hasMore || state.loadingOlder) return;
  state.loadingOlder = true;
  el.older.textContent = "加载中…";
  try {
    const cursor = state.nextCursor || 0;
    const resp = await fetch(`${convPath(state.activeId)}?count=40&maxMsgId=${cursor}`);
    const data = await resp.json();
    if (data.ok) {
      const older = data.data.messages || [];
      state.messages = mergeMessages(state.messages, older);
      state.hasMore = Boolean(data.data.hasMore);
      state.nextCursor = data.data.nextCursor;
      setThreadCache(state.activeId, {
        messages: state.messages,
        hasMore: state.hasMore,
        nextCursor: state.nextCursor,
        peer: getThreadCache(state.activeId)?.peer || data.data.peer,
      });
      renderMessages({ stickToBottom: false });
    }
  } finally {
    state.loadingOlder = false;
    el.older.textContent = "查看更早消息";
  }
}

function livePayload(event) {
  return {
    mid: event.mid,
    text: event.text,
    time: event.time,
    ts: event.ts || Date.now(),
    mine: event.mine,
    fromUid: event.fromUid,
    name: event.mine ? "" : event.name,
    avatar: event.avatar,
    kind: event.kind || "text",
    image: event.image,
    resume: event.resume,
    file: event.file,
    audio: event.audio,
  };
}

function syncActiveHeader(conv) {
  if (!conv) return;
  if (String(state.activeId) !== String(conv.friendId) && String(state.activeId) !== String(conv.uid)) return;
  el.peerName.textContent = displayConvName(conv);
  el.peerJob.textContent = [conv.job, conv.salary].filter(Boolean).join(" · ");
  renderAvatar(el.peerAvatar, conv.avatar, displayConvName(conv));
}

function applyIncomingConv(event) {
  const friendId = String(event.friendId || "").trim();
  if (!isConversationId(friendId)) return;
  upsertConv({
    friendId,
    uid: event.uid,
    name: event.name,
    avatar: event.avatar,
    job: event.job,
    lastMessage: event.lastMessage,
    lastTime: event.lastTime,
    unread: typeof event.unread === "number" ? event.unread : 1,
    trusted: true,
  });
  if (event.total != null) state.total = event.total;
  renderList();
}

function applyIncomingPeer(event) {
  const friendId = String(event.friendId || "").trim();
  if (!isConversationId(friendId)) return;
  let conv = findConvByFriendId(friendId);
  if (!conv) {
    upsertConv({
      friendId,
      uid: event.uid,
      name: event.name,
      avatar: event.avatar,
      job: event.job,
      trusted: true,
    });
    conv = findConvByFriendId(friendId);
  } else {
    const expectedUid = peerUidFromConv(conv);
    const incomingUid = String(event.uid || "").trim();
    const trusted = Boolean(event.trusted);
    if (
      incomingUid
      && expectedUid
      && incomingUid !== expectedUid
      && incomingUid !== String(state.me.uid || "")
      && !trusted
    ) {
      renderList();
      return;
    }
    if (trusted && incomingUid && incomingUid !== String(state.me.uid || "")) {
      conv.uid = incomingUid;
    }
    applyPeerIdentity(conv, event, { trusted: true });
  }
  syncActiveHeader(conv);
  if (conv && String(state.activeId) === friendId) {
    renderMessages({ stickToBottom: false });
  }
  renderList();
}

function applyIncomingThread(event) {
  const friendId = String(event.friendId || "").trim();
  if (!isConversationId(friendId)) return;
  if (event.lastMessage) {
    upsertConv({
      friendId,
      uid: event.peer?.uid || event.uid,
      name: event.peer?.name || event.name,
      avatar: event.peer?.avatar || event.avatar,
      job: event.peer?.job || event.job,
      lastMessage: event.lastMessage,
      lastTs: Date.now(),
      trusted: true,
    });
  }
  applyThreadPayload(friendId, {
    messages: event.messages || [],
    hasMore: event.hasMore,
    nextCursor: event.nextCursor,
    source: "history",
    peer: event.peer || {
      uid: event.uid,
      friendId,
      name: event.name,
      avatar: event.avatar,
      job: event.job,
    },
  }, {
    toView: String(state.activeId) === cacheKey(friendId),
    merge: true,
  });
}

function cacheLiveIntoThread(friendId, event) {
  const key = String(friendId || event.friendId || "").trim();
  if (!key || !isConversationId(key)) return;
  if (!messageBelongsToConv(key, event)) return;
  const payload = livePayload(event);
  const prev = getThreadCache(key);
  const local = prev?.messages || [];
  const merged = mergeThreadMessages(local, [payload]);
  setThreadCache(key, {
    messages: merged,
    hasMore: prev?.hasMore ?? false,
    nextCursor: prev?.nextCursor ?? null,
    peer: prev?.peer || {
      uid: event.uid,
      friendId: key,
      name: event.name,
      avatar: event.avatar,
      job: event.job,
    },
    source: prev?.source === "history" ? "history" : "live",
    fetchedAt: prev?.fetchedAt || Date.now(),
  });
  return merged;
}

function appendLive(event) {
  // BOSS-stable: 会话主键必须是 friendId（conversation id），uid 只表示对方。
  const friendId = String(event.friendId || "").trim();
  const peerUid = String(event.uid || "").trim();
  if (!isConversationId(friendId)) {
    // 没有合法会话 id 时绝不改列表预览，避免串写全部会话。
    return;
  }
  if (!messageBelongsToConv(friendId, event)) return;
  if (event.mine && event.avatar && !state.me.avatar) {
    state.me = { ...state.me, avatar: event.avatar };
  }
  const incomingName = event.mine ? undefined : event.name;
  const existing = findConvByFriendId(friendId);
  upsertConv({
    friendId,
    uid: event.mine ? undefined : peerUid,
    name: incomingName,
    job: event.mine ? undefined : event.job,
    avatar: event.mine ? undefined : event.avatar,
    lastMessage: event.text,
    lastTime: event.time,
    lastTs: event.ts || Date.now(),
    mine: event.mine,
    unread: event.mine ? 0 : 1,
    trusted: Boolean(incomingName && !looksLikePlaceholder(incomingName, peerUid)),
  });
  if (!event.mine && existing && looksLikePlaceholder((findConvByFriendId(friendId) || {}).name, peerUid) && !looksLikePlaceholder(existing.name, existing.uid)) {
    const row = findConvByFriendId(friendId);
    if (row) row.name = existing.name;
  }
  const isActive = Boolean(state.activeId && String(state.activeId) === friendId);
  if (isActive) {
    const nearBottom =
      el.messages.scrollHeight - el.messages.scrollTop - el.messages.clientHeight < 140;
    const incoming = livePayload(event);
    const kind = String(incoming.kind || event.kind || "text");
    const isMedia = kind === "image" || kind === "emoji" || kind === "voice" || kind === "video";
    const pendingIdx = state.messages.findIndex((m) => (
      m.pending && Boolean(m.mine) === Boolean(event.mine) && m.text === event.text
    ));
    if (pendingIdx >= 0) {
      state.messages[pendingIdx] = upgradeMessage(state.messages[pendingIdx], { ...incoming, pending: false });
    } else {
      // Media placeholders all share text like [图片]/[表情] — only match by mid.
      const dupIdx = state.messages.findIndex((m) => {
        if (event.mid && m.mid && String(m.mid) === String(event.mid)) return true;
        if (isMedia || isGenericMediaPlaceholder(event.text) || isGenericMediaPlaceholder(m.text)) {
          return false;
        }
        if (Boolean(m.mine) === Boolean(event.mine) && m.text === event.text) {
          const dt = Math.abs((Number(m.ts) || 0) - (Number(event.ts) || Date.now()));
          return dt < 120000;
        }
        return false;
      });
      if (dupIdx >= 0) {
        state.messages[dupIdx] = upgradeMessage(state.messages[dupIdx], incoming);
      } else {
        state.messages = mergeThreadMessages(state.messages, [incoming]);
      }
    }
    setThreadCache(friendId, {
      messages: state.messages.slice(),
      hasMore: state.hasMore,
      nextCursor: state.nextCursor,
      peer: getThreadCache(friendId)?.peer || findConv(friendId),
      source: getThreadCache(friendId)?.source || "live",
      fetchedAt: Date.now(),
    });
    renderMessages({ stickToBottom: nearBottom });
    const conv = findConvByFriendId(friendId);
    if (conv) {
      conv.unread = 0;
      syncActiveHeader(conv);
    }
  } else {
    cacheLiveIntoThread(friendId, event);
  }
  renderList();
}

async function sendMessage(text) {
  if (state.sending) {
    if (el.sendHint) {
      el.sendHint.hidden = false;
      el.sendHint.textContent = "上一条还在发送…";
    }
    return;
  }
  if (!state.activeId) {
    alert("请先选择一个会话");
    return;
  }
  if (!text.trim()) return;
  // Only block when we positively know creds are missing (not while still loading).
  if (state.sendCred && state.sendCred.ready === false && Array.isArray(state.sendCred.missing)) {
    alert("发信凭据未就绪，请先运行: boss douyin grab-ticket --qr");
    return;
  }
  const trimmed = text.trim();
  const activeId = state.activeId;
  const conv = findConv(activeId) || {};
  const tempId = `tmp-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const pending = {
    mid: tempId,
    text: trimmed,
    time: new Date().toTimeString().slice(0, 5),
    ts: Date.now(),
    mine: true,
    fromUid: state.me.uid,
    kind: "text",
    pending: true,
  };
  state.sending = true;
  state.messages = mergeMessages(state.messages, [pending]);
  upsertConv({
    friendId: activeId,
    uid: conv.uid,
    lastMessage: trimmed,
    lastTime: pending.time,
    mine: true,
  });
  setThreadCache(activeId, {
    messages: state.messages,
    hasMore: state.hasMore,
    nextCursor: state.nextCursor,
    peer: getThreadCache(activeId)?.peer || conv,
    fetchedAt: getThreadCache(activeId)?.fetchedAt || Date.now(),
  });
  renderMessages({ stickToBottom: true });
  renderList();
  el.input.value = "";
  resizeInput();
  el.send.disabled = true;
  if (el.sendHint) {
    el.sendHint.hidden = false;
    el.sendHint.textContent = "发送中…";
  }
  const postOnce = async () => {
    const resp = await fetch(convPath(activeId), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: trimmed }),
    });
    let data = null;
    try {
      data = await resp.json();
    } catch (parseErr) {
      throw new Error(`发送失败(HTTP ${resp.status})，响应不是 JSON`);
    }
    return { resp, data };
  };
  try {
    let { resp, data } = await postOnce();
    if (!data.ok) {
      await new Promise((r) => setTimeout(r, 500));
      ({ resp, data } = await postOnce());
    }
    if (!data.ok) {
      state.messages = state.messages.filter((m) => m.mid !== tempId);
      setThreadCache(state.activeId || activeId, {
        messages: state.messages,
        hasMore: state.hasMore,
        nextCursor: state.nextCursor,
        peer: getThreadCache(state.activeId || activeId)?.peer || conv,
      });
      renderMessages({ stickToBottom: true });
      el.input.value = trimmed;
      resizeInput();
      const msg = data.error?.message || `发送失败(HTTP ${resp.status})`;
      if (el.sendHint) {
        el.sendHint.hidden = false;
        el.sendHint.textContent = msg;
      }
      alert(msg);
      try { await loadMe(); } catch (_) { /* ignore */ }
      return;
    }
    const ev = data.data || {};
    const newId = ev.friendId || activeId;
    if (newId && String(newId) !== String(state.activeId)) {
      const oldPeer = peerUidFromConv({ friendId: activeId });
      const newPeer = peerUidFromConv({ friendId: newId });
      // Only migrate cache when remapped cid is the same DM peer — never copy across people.
      if (oldPeer && newPeer && oldPeer === newPeer) {
        const oldCache = getThreadCache(activeId);
        if (oldCache) setThreadCache(newId, oldCache);
      }
      state.activeId = newId;
      upsertConv({
        friendId: newId,
        uid: conv.uid,
        name: conv.name,
        avatar: conv.avatar,
        lastMessage: trimmed,
        lastTime: pending.time,
        mine: true,
        trusted: true,
      });
      void notifyActive(newId);
    }
    const targetId = state.activeId || newId || activeId;
    const idx = state.messages.findIndex((m) => m.mid === tempId);
    if (idx >= 0) {
      const already = state.messages.find((m, i) => i !== idx && m.mine && m.text === trimmed && !m.pending);
      if (already) {
        state.messages = state.messages.filter((m) => m.mid !== tempId);
      } else {
        state.messages[idx] = { ...state.messages[idx], ...livePayload(ev), pending: false, mid: ev.mid || tempId };
      }
    } else {
      // Pending was wiped by a refresh — still append the confirmed send.
      state.messages = mergeMessages(state.messages, [{ ...livePayload(ev), pending: false }]);
    }
    setThreadCache(targetId, {
      messages: state.messages,
      hasMore: state.hasMore,
      nextCursor: state.nextCursor,
      peer: getThreadCache(targetId)?.peer || findConv(targetId),
      fetchedAt: Date.now(),
    });
    renderMessages({ stickToBottom: true });
    renderList();
    if (el.sendHint) el.sendHint.hidden = true;
  } catch (err) {
    state.messages = state.messages.filter((m) => m.mid !== tempId);
    renderMessages({ stickToBottom: true });
    el.input.value = trimmed;
    resizeInput();
    const msg = err.message || "发送失败";
    if (el.sendHint) {
      el.sendHint.hidden = false;
      el.sendHint.textContent = msg;
    }
    alert(msg);
  } finally {
    state.sending = false;
    el.send.disabled = false;
    el.input.focus();
  }
}

function connectEvents() {
  const source = new EventSource("/api/events");
  source.onmessage = (ev) => {
    try {
      const event = JSON.parse(ev.data);
      if (event.type === "status") {
        if (event.me) {
          state.me = { ...state.me, ...event.me };
          if (!state.me.avatar && event.me.avatar) state.me.avatar = event.me.avatar;
        }
        if (event.sendCred) state.sendCred = event.sendCred;
        setMqtt(event.mqtt);
        refreshStatusBar();
      } else if (event.type === "conv") {
        applyIncomingConv(event);
      } else if (event.type === "peer") {
        applyIncomingPeer(event);
      } else if (event.type === "thread") {
        applyIncomingThread(event);
      } else if (event.type === "message") {
        appendLive(event);
      }
    } catch (err) {
      console.debug(err);
    }
  };
  source.onerror = () => setStatus("bad", "实时连接中断");
}

function resizeInput() {
  el.input.style.height = "auto";
  el.input.style.height = Math.min(el.input.scrollHeight, 120) + "px";
}

el.search.addEventListener("input", renderList);
el.loadMore.addEventListener("click", () => loadConversations({ reset: false }));
el.older.addEventListener("click", loadOlder);
el.back.addEventListener("click", () => {
  document.querySelector(".app").classList.remove("chat-open");
  state.activeId = null;
  void notifyActive(null);
  renderList();
});
el.composer.addEventListener("submit", (ev) => {
  ev.preventDefault();
  sendMessage(el.input.value);
});
el.input.addEventListener("input", resizeInput);
// Enter 发送；Shift+Enter 换行。输入法组字中不发送。
el.input.addEventListener("keydown", (ev) => {
  if (ev.key !== "Enter" || ev.shiftKey) return;
  if (ev.isComposing) return;
  ev.preventDefault();
  ev.stopPropagation();
  sendMessage(el.input.value);
});
el.input.addEventListener("keyup", (ev) => {
  // 部分中文输入法组字结束后只在 keyup 给出 Enter
  if (ev.key !== "Enter" || ev.shiftKey || ev.isComposing) return;
  if (state.sending) return;
  if (!el.input.value.trim()) return;
  // keydown 已处理过则 sending/清空会拦住；此处兜底未发出的情况
  ev.preventDefault();
  sendMessage(el.input.value);
});

(async function boot() {
  try {
    await loadMe();
  } catch (err) {
    el.list.innerHTML = `<div class="empty">${err.message}</div>`;
  }
  connectEvents();
  await loadConversations({ reset: true });
})();
