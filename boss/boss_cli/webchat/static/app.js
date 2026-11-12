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
};

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
};

function mediaUrl(url) {
  if (!url) return "";
  return `/api/media?u=${encodeURIComponent(url)}`;
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
  return text ? text.slice(-1) : "?";
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

function visibleConversations() {
  const q = el.search.value.trim().toLowerCase();
  if (!q) return state.conversations;
  return state.conversations.filter((c) => {
    return `${c.name} ${c.job} ${c.lastMessage}`.toLowerCase().includes(q);
  });
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
      row.querySelector(".conv-name").textContent = conv.name || String(conv.friendId);
      row.querySelector(".conv-time").textContent = conv.lastTime || "";
      row.querySelector(".conv-last").textContent = conv.lastMessage || conv.job || "";
      renderAvatar(row.querySelector(".avatar"), conv.avatar, conv.name);
      row.addEventListener("click", () => openConversation(conv.friendId));
      el.list.appendChild(row);
    }
  }
  el.loadMore.hidden = !(state.offset < state.total);
}

function findConv(id) {
  return state.conversations.find((c) => String(c.friendId) === String(id) || String(c.uid) === String(id));
}

function isOwnDisplayName(name) {
  const mine = String(state.me.name || "").trim();
  return Boolean(mine && name && String(name).trim() === mine);
}

function looksLikePlaceholder(name) {
  const text = String(name || "").trim();
  if (!text) return true;
  return /^\d+$/.test(text);
}

function applyPeerIdentity(conv, partial, { trusted = false } = {}) {
  if (!conv || !partial) return;
  const incoming = String(partial.name || "").trim();
  const safe = incoming && !isOwnDisplayName(incoming) && !looksLikePlaceholder(incoming);
  if (safe && (trusted || looksLikePlaceholder(conv.name) || isOwnDisplayName(conv.name))) {
    conv.name = incoming;
  }
  if (partial.avatar) conv.avatar = partial.avatar;
  if (partial.job) conv.job = partial.job;
}

function upsertConv(partial) {
  const id = partial.friendId || partial.uid;
  const existing = findConv(id);
  if (existing) {
    applyPeerIdentity(existing, partial, { trusted: false });
    if (partial.lastMessage) existing.lastMessage = partial.lastMessage;
    if (partial.lastTime || partial.time) existing.lastTime = partial.lastTime || partial.time;
    if (partial.uid) existing.uid = partial.uid;
    if (partial.friendId) existing.friendId = partial.friendId;
    if (typeof partial.unread === "number") existing.unread = partial.unread;
    if (partial.lastMessage) {
      state.conversations = [existing, ...state.conversations.filter((c) => c !== existing)];
    }
  } else if (id) {
    const row = {
      friendId: id,
      uid: partial.uid || id,
      name: String(id),
      job: "",
      avatar: "",
      lastMessage: partial.lastMessage || partial.text || "",
      lastTime: partial.lastTime || partial.time || "",
      unread: partial.mine ? 0 : 1,
    };
    applyPeerIdentity(row, partial, { trusted: false });
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

function renderBubbleContent(bubble, msg) {
  const kind = msg.kind || "text";
  if (kind === "image" && msg.image && (msg.image.preview || msg.image.origin)) {
    bubble.classList.add("bubble-media");
    const link = document.createElement("a");
    link.href = mediaUrl(msg.image.origin || msg.image.preview);
    link.target = "_blank";
    link.rel = "noopener";
    const img = document.createElement("img");
    img.className = "chat-image";
    img.alt = msg.text || "图片";
    img.src = mediaUrl(msg.image.preview || msg.image.origin);
    img.addEventListener("error", () => {
      img.replaceWith(textEl("div", "", msg.text || "[图片]"));
    });
    link.appendChild(img);
    bubble.appendChild(link);
    if (msg.text && msg.text !== "[图片]") {
      bubble.appendChild(textEl("div", "media-caption", msg.text));
    }
    return;
  }
  if (kind === "voice") {
    const wrap = document.createElement("div");
    wrap.className = "voice-card";
    const label = textEl("span", "voice-label", msg.text || "[语音]");
    if (msg.audio && msg.audio.url) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "voice-play";
      btn.textContent = "▶";
      const audio = document.createElement("audio");
      audio.preload = "none";
      audio.src = mediaUrl(msg.audio.url);
      btn.addEventListener("click", () => {
        if (audio.paused) {
          audio.play();
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

function isMine(msg) {
  const fromUid = Number(msg.fromUid || 0);
  const myUid = Number(state.me.uid || 0);
  const conv = findConv(state.activeId) || {};
  const peerUid = Number(conv.uid || conv.friendId || 0);
  if (myUid && fromUid === myUid) return true;
  if (peerUid && fromUid === peerUid) return false;
  if (msg.mine === true) return true;
  if (peerUid && fromUid && fromUid !== peerUid) return true;
  return false;
}

function renderMessages({ stickToBottom = true } = {}) {
  const nearBottom =
    el.messages.scrollHeight - el.messages.scrollTop - el.messages.clientHeight < 80;
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
    const peerName = conv.name || msg.name || "";
    const peerAvatar = conv.avatar || msg.avatar || "";
    if (mine) {
      renderAvatar(av, state.me.avatar, state.me.name);
    } else {
      renderAvatar(av, peerAvatar, peerName);
    }
    const stack = document.createElement("div");
    stack.className = "bubble-stack";
    if (!mine && peerName && !looksLikePlaceholder(peerName)) {
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
  if (stickToBottom && (nearBottom || state.messages.length < 12)) {
    el.messages.scrollTop = el.messages.scrollHeight;
  } else if (!stickToBottom) {
    el.messages.scrollTop = el.messages.scrollHeight - prevHeight;
  }
}

async function loadMe() {
  const resp = await fetch("/api/me");
  const data = await resp.json();
  if (!data.ok) throw new Error(data.error?.message || "无法获取当前用户");
  state.me = data.data.me || state.me;
  setMqtt(data.data.mqtt);
}

function setMqtt(status) {
  if (status === "online") setStatus("online", "在线");
  else if (status === "reconnecting") setStatus("bad", "重连中");
  else if (status === "stopped") setStatus("bad", "已断开");
  else setStatus("", "连接中");
}

async function loadConversations({ reset = false } = {}) {
  const offset = reset ? 0 : state.offset;
  const resp = await fetch(`/api/conversations?offset=${offset}&limit=60`);
  const data = await resp.json();
  if (!data.ok) {
    el.list.innerHTML = `<div class="empty">${data.error?.message || "加载失败"}</div>`;
    return;
  }
  const page = data.data.conversations || [];
  state.total = data.data.total || page.length;
  if (reset) state.conversations = page;
  else {
    const seen = new Set(state.conversations.map((c) => String(c.friendId)));
    for (const item of page) {
      if (!seen.has(String(item.friendId))) state.conversations.push(item);
    }
  }
  state.offset = data.data.nextOffset == null ? state.total : data.data.nextOffset;
  renderList();
}

async function openConversation(friendId) {
  state.activeId = friendId;
  const conv = findConv(friendId) || { friendId, name: String(friendId) };
  if (conv.unread) conv.unread = 0;
  document.querySelector(".app").classList.add("chat-open");
  el.empty.hidden = true;
  el.pane.hidden = false;
  el.peerName.textContent = conv.name || "";
  el.peerJob.textContent = [conv.job, conv.salary].filter(Boolean).join(" · ");
  renderAvatar(el.peerAvatar, conv.avatar, conv.name);
  renderList();
  el.messages.innerHTML = `<div class="empty">正在加载聊天…</div>`;
  const resp = await fetch(`/api/conversations/${friendId}/messages?count=40`);
  const data = await resp.json();
  if (!data.ok) {
    el.messages.innerHTML = `<div class="empty">${data.error?.message || "加载失败"}</div>`;
    return;
  }
  state.messages = sortMessages(data.data.messages || []);
  state.hasMore = Boolean(data.data.hasMore);
  state.nextCursor = data.data.nextCursor;
  if (data.data.peer) {
    applyPeerIdentity(conv, data.data.peer, { trusted: true });
    el.peerName.textContent = conv.name || "";
    el.peerJob.textContent = [conv.job || data.data.peer.job, conv.salary].filter(Boolean).join(" · ");
    renderAvatar(el.peerAvatar, conv.avatar, conv.name);
    renderList();
  }
  renderMessages({ stickToBottom: true });
  el.input.focus();
}

async function loadOlder() {
  if (!state.activeId || !state.hasMore || state.loadingOlder) return;
  state.loadingOlder = true;
  el.older.textContent = "加载中…";
  try {
    const cursor = state.nextCursor || 0;
    const resp = await fetch(`/api/conversations/${state.activeId}/messages?count=40&maxMsgId=${cursor}`);
    const data = await resp.json();
    if (data.ok) {
      const older = data.data.messages || [];
      state.messages = mergeMessages(state.messages, older);
      state.hasMore = Boolean(data.data.hasMore);
      state.nextCursor = data.data.nextCursor;
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
  el.peerName.textContent = conv.name || "";
  el.peerJob.textContent = [conv.job, conv.salary].filter(Boolean).join(" · ");
  renderAvatar(el.peerAvatar, conv.avatar, conv.name);
}

function applyIncomingPeer(event) {
  let conv = findConv(event.friendId) || findConv(event.uid);
  if (!conv) {
    upsertConv({
      friendId: event.friendId || event.uid,
      uid: event.uid,
      name: event.name,
      avatar: event.avatar,
      job: event.job,
      mine: false,
    });
    conv = findConv(event.friendId) || findConv(event.uid);
  } else {
    applyPeerIdentity(conv, event, { trusted: true });
  }
  syncActiveHeader(conv);
  if (conv && (String(state.activeId) === String(conv.friendId) || String(state.activeId) === String(conv.uid))) {
    renderMessages({ stickToBottom: false });
  }
  renderList();
}

function appendLive(event) {
  const uid = event.friendId || event.uid;
  upsertConv({
    friendId: uid,
    uid: event.uid,
    name: event.name,
    avatar: event.avatar,
    lastMessage: event.text,
    lastTime: event.time,
    mine: event.mine,
    unread: event.mine ? 0 : 1,
  });
  if (String(state.activeId) === String(uid) || String(state.activeId) === String(event.uid)) {
    const pendingIdx = state.messages.findIndex((m) => (
      m.pending && Boolean(m.mine) === Boolean(event.mine) && m.text === event.text
    ));
    if (pendingIdx >= 0) {
      state.messages[pendingIdx] = { ...state.messages[pendingIdx], ...livePayload(event), pending: false };
      renderMessages({ stickToBottom: true });
    } else {
      const dup = state.messages.some((m) => {
        if (event.mid && m.mid && String(m.mid) === String(event.mid)) return true;
        if (Boolean(m.mine) === Boolean(event.mine) && m.text === event.text) {
          const dt = Math.abs((Number(m.ts) || 0) - (Number(event.ts) || Date.now()));
          return dt < 120000;
        }
        return false;
      });
      if (!dup) {
        state.messages = mergeMessages(state.messages, [livePayload(event)]);
        renderMessages({ stickToBottom: true });
      }
    }
    const conv = findConv(uid) || findConv(state.activeId);
    if (conv) {
      conv.unread = 0;
      syncActiveHeader(conv);
    }
  }
  renderList();
}

async function sendMessage(text) {
  if (!state.activeId || !text.trim()) return;
  const trimmed = text.trim();
  const conv = findConv(state.activeId) || {};
  const tempId = `tmp-${Date.now()}`;
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
  state.messages = mergeMessages(state.messages, [pending]);
  upsertConv({
    friendId: state.activeId,
    uid: conv.uid,
    lastMessage: trimmed,
    lastTime: pending.time,
    mine: true,
  });
  renderMessages({ stickToBottom: true });
  renderList();
  el.input.value = "";
  resizeInput();
  el.send.disabled = true;
  try {
    const resp = await fetch(`/api/conversations/${state.activeId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: trimmed }),
    });
    const data = await resp.json();
    if (!data.ok) {
      state.messages = state.messages.filter((m) => m.mid !== tempId);
      renderMessages({ stickToBottom: true });
      el.input.value = trimmed;
      resizeInput();
      alert(data.error?.message || "发送失败");
      return;
    }
    const ev = data.data || {};
    const idx = state.messages.findIndex((m) => m.mid === tempId);
    if (idx >= 0) {
      const already = state.messages.find((m, i) => i !== idx && m.mine && m.text === trimmed && !m.pending);
      if (already) {
        state.messages = state.messages.filter((m) => m.mid !== tempId);
      } else {
        state.messages[idx] = { ...state.messages[idx], ...livePayload(ev), pending: false, mid: ev.mid || tempId };
      }
      renderMessages({ stickToBottom: true });
    }
  } catch (err) {
    state.messages = state.messages.filter((m) => m.mid !== tempId);
    renderMessages({ stickToBottom: true });
    el.input.value = trimmed;
    resizeInput();
    alert(err.message || "发送失败");
  } finally {
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
        if (event.me) state.me = event.me;
        setMqtt(event.mqtt);
      } else if (event.type === "peer") {
        applyIncomingPeer(event);
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
  renderList();
});
el.composer.addEventListener("submit", (ev) => {
  ev.preventDefault();
  sendMessage(el.input.value);
});
el.input.addEventListener("input", resizeInput);
el.input.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey) {
    ev.preventDefault();
    sendMessage(el.input.value);
  }
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
