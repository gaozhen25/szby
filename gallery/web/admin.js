import { api } from "./lib/api.js?v=1";
import { escapeHtml, platformName, shortStoreError } from "./lib/text.js?v=1";
import { slidesOf } from "./lib/watch.js?v=2";

const login = document.getElementById("login");
const shell = document.getElementById("shell");
const loginForm = document.getElementById("login-form");
const loginError = document.getElementById("login-error");
const banner = document.getElementById("oss-banner");
const statsEl = document.getElementById("stats");
const grid = document.getElementById("grid");
const pageLabel = document.getElementById("page-label");
const prev = document.getElementById("prev");
const next = document.getElementById("next");
const detail = document.getElementById("detail");

const state = { offset: 0, limit: 12, total: 0, current: null, items: [], sourceId: "" };

function showLogin() {
  shell.classList.add("hidden");
  login.classList.remove("hidden");
}

function showApp() {
  login.classList.add("hidden");
  shell.classList.remove("hidden");
}

function showView(name) {
  document.querySelectorAll(".nav-btn").forEach((button) => {
    button.classList.toggle("on", button.dataset.view === name);
  });
  document.querySelectorAll(".view").forEach((view) => view.classList.add("hidden"));
  document.getElementById("view-" + name).classList.remove("hidden");
  const titles = { library: "素材库", ingest: "解析入库", api: "接口" };
  const crumb = document.getElementById("crumb-current");
  if (crumb) crumb.textContent = titles[name] || name;
}

function renderOss(oss) {
  if (!oss || !oss.configured) {
    const missing = ((oss && oss.missing) || []).join("、");
    banner.className = "banner";
    banner.textContent = "OSS 还没配好，文件不会上传。在项目 .env 里写上 " + (missing || "OSS 配置") + "，然后重新执行 bash run.sh。";
    return;
  }
  banner.className = "banner hidden";
  banner.textContent = "";
}

function uploadError(item) {
  return item.error || "";
}

function savedCount(item) {
  return item.saved ? 1 : 0;
}

function fillIndustrySelect(stats) {
  const select = document.getElementById("industry");
  const current = select.value;
  const industries = Array.isArray(stats && stats.industries) ? stats.industries : [];
  const options = ['<option value="">全部行业</option>'].concat(
    industries.map((item) => {
      const name = item.name || "";
      const count = typeof item.count === "number" ? ` ${item.count}` : "";
      return `<option value="${escapeHtml(name)}">${escapeHtml(name)}${escapeHtml(count)}</option>`;
    })
  );
  select.innerHTML = options.join("");
  if (current && industries.some((item) => item.name === current)) {
    select.value = current;
  } else {
    select.value = "";
  }
}

function renderStats(stats) {
  fillIndustrySelect(stats);
  const platform = document.getElementById("platform").value;
  const type = document.getElementById("type").value;
  const items = [
    ["", "", "全部", stats.total],
    ["douyin", "", "抖音", stats.douyin],
    ["xhs", "", "小红书", stats.xhs],
    ["", "image", "图片", stats.image],
    ["", "video", "视频", stats.video],
  ];
  statsEl.innerHTML = items.map(([itemPlatform, itemType, name, count]) => {
    const on = !state.sourceId && platform === itemPlatform && type === itemType;
    return `<button type="button" class="stat${on ? " on" : ""}" data-platform="${itemPlatform}" data-type="${itemType}">${escapeHtml(name)} ${count}</button>`;
  }).join("");
}

function coverOf(item) {
  const slide = slidesOf(item)[0];
  if (!slide) return "";
  if (item.type === "video") return slide.poster || "";
  return slide.src || "";
}

function typeName(value) {
  return value === "video" ? "视频" : "图片";
}

function whenOf(iso) {
  const date = new Date(iso || "");
  if (Number.isNaN(date.getTime())) return { day: "—", time: "" };
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  return { day: `${year}-${month}-${day}`, time: `${hour}:${minute}` };
}

function tagsOf(source) {
  const tags = source.tags || [];
  if (!tags.length) return '<span class="muted">—</span>';
  return tags.map((tag) => `<span class="chip">${escapeHtml(tag)}</span>`).join("");
}

function metricText(source) {
  const parts = [
    ["赞", source.like_count],
    ["藏", source.collect_count],
    ["分享", source.share_count],
    ["评论", source.comment_count],
  ].filter(([, count]) => count !== null && count !== undefined && count !== "");
  const skip = new Set([
    "like_count", "collect_count", "share_count", "comment_count",
    "liked_count", "likedCount", "collected_count", "collectedCount",
    "shareCount", "commentCount", "zanCount", "点赞", "收藏", "分享", "评论",
    "liked", "collectedAt", "index", "platform", "title", "author", "comments", "shareLink",
  ]);
  const reported = source.reported && typeof source.reported === "object" ? source.reported : {};
  if (reported.liked === true) parts.push(["已点赞", ""]);
  if (typeof reported.collectedAt === "number" && reported.collectedAt > 1e11) {
    const when = new Date(reported.collectedAt);
    if (!Number.isNaN(when.getTime())) parts.push(["采集", when.toLocaleString("zh-CN", { hour12: false })]);
  }
  Object.entries(reported).forEach(([key, value]) => {
    if (skip.has(key) || value === null || value === undefined || value === "" || typeof value === "object") return;
    parts.push([key, value]);
  });
  return parts.map(([name, count]) => (count === "" ? name : `${name} ${count}`)).join(" · ");
}

function plainTitle(source) {
  const raw = source.content || source.title || "";
  const text = raw.replace(/#/g, " ").replace(/[ \t]{2,}/g, " ").replace(/ *\n */g, "\n").trim();
  return text || "（无文案）";
}

function workStatus(assets) {
  const images = assets.filter((item) => item.type !== "video").length;
  const videos = assets.filter((item) => item.type === "video").length;
  const bits = [];
  if (images) bits.push(`${images} 张图片`);
  if (videos) bits.push(`${videos} 个视频`);
  const failed = assets.some((item) => uploadError(item));
  const saved = assets.length > 0 && assets.every((item) => item.saved);
  const pill = failed
    ? `<span class="pill bad">仅预览</span>`
    : (saved ? `<span class="pill ok">已入库</span>` : `<span class="pill">未保存</span>`);
  return `<span class="badge-row"><span class="pill">${escapeHtml(bits.join("，") || "没有素材")}</span>${pill}</span>`;
}

function coverButton(item) {
  const cover = coverOf(item);
  const visual = cover
    ? `<img alt="" width="88" height="118" src="${escapeHtml(cover)}" />`
    : `<span class="cover-fallback">${escapeHtml(typeName(item.type))}</span>`;
  return `<button type="button" class="cover" data-id="${escapeHtml(item.id)}" aria-label="${escapeHtml(typeName(item.type))}">${visual}</button>`;
}

function renderGrid(data) {
  state.total = data.total;
  state.items = data.items || [];
  const from = data.total ? state.offset + 1 : 0;
  const to = Math.min(state.offset + data.items.length, data.total);
  const assetNote = typeof data.asset_total === "number" ? `，${data.asset_total} 条素材` : "";
  pageLabel.textContent = data.total
    ? `${state.sourceId ? "同一来源 · " : ""}${from}-${to} / ${data.total} 个作品${assetNote}`
    : "0";
  document.getElementById("clear-source").classList.toggle("hidden", !state.sourceId);
  prev.disabled = state.offset <= 0;
  next.disabled = state.offset + state.limit >= data.total;
  if (!data.items.length) {
    grid.innerHTML = '<tr><td class="empty" colspan="8">库是空的。<button type="button" class="ghost" data-go="ingest">去入库</button></td></tr>';
    return;
  }
  grid.innerHTML = data.items.map((item) => {
    const source = item.source || {};
    const assets = item.assets || [];
    const when = whenOf(item.updated_at || (assets[0] && assets[0].updated_at));
    const author = source.author || "未知作者";
    const industry = (source.industry || "").trim();
    const href = source.canonical_url || source.source_url || "";
    const link = href
      ? `<a class="linkish" href="${escapeHtml(href)}" target="_blank" rel="noreferrer">打开</a>`
      : `<span class="muted">—</span>`;
    const first = assets[0];
    return `<tr class="work"${first ? ` data-id="${escapeHtml(first.id)}" tabindex="0"` : ""}>
      <td><span class="when"><span>${when.day}</span><span class="time">${when.time}</span></span></td>
      <td><span class="who"><span><strong>${escapeHtml(author)}</strong><span class="plat">${escapeHtml(platformName(source.platform))}</span></span></span></td>
      <td><span class="copy">${escapeHtml(plainTitle(source))}</span>${metricText(source) ? `<span class="metrics">${escapeHtml(metricText(source))}</span>` : ""}</td>
      <td>${industry ? `<span class="chip">${escapeHtml(industry)}</span>` : '<span class="muted">—</span>'}</td>
      <td><div class="covers">${assets.map(coverButton).join("") || '<span class="muted">没有素材</span>'}</div></td>
      <td><span class="taglist">${tagsOf(source)}</span></td>
      <td>${workStatus(assets)}</td>
      <td>${link}</td>
    </tr>`;
  }).join("");
}

async function loadLibrary() {
  grid.innerHTML = '<tr><td class="empty" colspan="8">加载中…</td></tr>';
  const params = new URLSearchParams({
    current: String(Math.floor(state.offset / state.limit) + 1),
    size: String(state.limit),
    q: document.getElementById("q").value.trim(),
    industry: document.getElementById("industry").value.trim(),
    platform: document.getElementById("platform").value,
    type: document.getElementById("type").value,
    source_id: state.sourceId,
    group: "source",
  });
  const [list, stats] = await Promise.all([
    api("/api/v1/library?" + params.toString()),
    api("/api/v1/library/stats"),
  ]);
  renderStats(stats.stats);
  renderGrid(list);
}

function openWork(work, focusId) {
  const source = work.source || {};
  const assets = work.assets || [];
  const focus = assets.find((item) => item.id === focusId) || assets[0] || null;
  state.current = focus;
  const when = whenOf(work.updated_at || (focus && focus.updated_at));
  document.getElementById("detail-when").textContent = when.time ? `${when.day} ${when.time}` : when.day;
  document.getElementById("detail-who").textContent = [source.author || "未知作者", platformName(source.platform)].filter(Boolean).join("，");
  document.getElementById("detail-title").textContent = plainTitle(source);
  const works = document.getElementById("detail-works");
  works.innerHTML = assets.map(coverButton).join("") || '<span class="muted">没有素材</span>';
  const focused = focus ? works.querySelector(`[data-id="${focus.id}"]`) : null;
  if (focused) focused.classList.add("on");
  document.getElementById("detail-tags").innerHTML = (source.tags || []).map((tag) => `<span class="chip">${escapeHtml(tag)}</span>`).join("") || '<span class="muted">没有标签</span>';
  document.getElementById("detail-industry-view").textContent = (source.industry || "").trim() || "未识别";
  document.getElementById("detail-state").innerHTML = workStatus(assets);
  const failed = assets.map(uploadError).find(Boolean) || "";
  const store = document.getElementById("detail-store");
  if (failed) {
    store.textContent = shortStoreError(failed) + "。画面来自原链接，还没有进 OSS。";
    store.className = "store-note bad";
  } else if (assets.length && assets.every((item) => item.saved)) {
    store.textContent = "文件在素材库里，地址长期有效。";
    store.className = "store-note ok";
  } else {
    store.textContent = "";
    store.className = "store-note";
  }
  const href = source.canonical_url || source.source_url || "";
  document.getElementById("detail-link").innerHTML = href
    ? `<a class="linkish" href="${escapeHtml(href)}" target="_blank" rel="noreferrer">打开</a>`
    : '<span class="muted">—</span>';
  const comments = source.comments || [];
  const commentBox = document.getElementById("detail-comments");
  if (comments.length) {
    commentBox.innerHTML = comments.map((comment) => {
      const bits = [];
      if (comment.zanCount) bits.push(`赞 ${comment.zanCount}`);
      if (comment.ip) bits.push(comment.ip);
      if (comment.isAuthor) bits.push("作者");
      const meta = bits.length ? ` <span class="muted">${escapeHtml(bits.join(" · "))}</span>` : "";
      const name = comment.author || comment.nickname || "匿名";
      const text = comment.text || comment.content || "";
      return `<p><span class="who">${escapeHtml(name)}</span> ${escapeHtml(text)}${meta}</p>`;
    }).join("");
  } else if (source.comment_count) {
    commentBox.innerHTML = `<p class="muted">公开页没有评论正文，评论数 ${escapeHtml(source.comment_count)}。</p>`;
  } else {
    commentBox.innerHTML = '<p class="muted">公开页没有带回评论。</p>';
  }
  state.savedCategory = focus ? (focus.category || "") : "";
  state.savedNote = focus ? (focus.note || "") : "";
  state.savedIndustry = source.industry || "";
  document.getElementById("detail-category").value = state.savedCategory;
  document.getElementById("detail-note").value = state.savedNote;
  document.getElementById("detail-industry").value = state.savedIndustry;
  syncDetailSave();
  document.getElementById("detail-status").textContent = "";
  document.getElementById("detail-files").innerHTML = assets.map((item) => (
    item.href
      ? `<li><a href="${escapeHtml(item.href)}" target="_blank" rel="noreferrer">${escapeHtml(item.name || "文件")}</a><span class="muted">已入库</span></li>`
      : `<li><span>${escapeHtml(item.name || "文件")}</span><span class="warn">${escapeHtml(shortStoreError(item.error))}</span></li>`
  )).join("") || '<li class="muted">没有文件</li>';
  if (!detail.open) detail.showModal();
  if (focused) focused.scrollIntoView({ block: "nearest" });
}

document.querySelectorAll(".nav-btn").forEach((button) => {
  button.addEventListener("click", () => showView(button.dataset.view));
});

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.textContent = "";
  try {
    const body = await api("/api/admin/login", {
      method: "POST",
      body: JSON.stringify({
        username: document.getElementById("username").value.trim(),
        password: document.getElementById("password").value,
      }),
    });
    renderOss(body.oss);
    showApp();
    fillApi();
    await loadLibrary();
  } catch (err) {
    loginError.textContent = err.message;
  }
});

document.getElementById("logout").addEventListener("click", async () => {
  await api("/api/admin/logout", { method: "POST" });
  showLogin();
});

document.getElementById("filters").addEventListener("submit", (event) => event.preventDefault());
let timer = 0;
function reloadLibrarySoon() {
  clearTimeout(timer);
  timer = setTimeout(() => {
    state.offset = 0;
    loadLibrary().catch((err) => { grid.innerHTML = `<tr><td class="empty" colspan="8">${escapeHtml(err.message)}</td></tr>`; });
  }, 250);
}
document.getElementById("q").addEventListener("input", reloadLibrarySoon);
for (const id of ["industry", "platform", "type"]) {
  document.getElementById(id).addEventListener("change", () => {
    state.offset = 0;
    loadLibrary().catch((err) => { grid.innerHTML = `<tr><td class="empty" colspan="8">${escapeHtml(err.message)}</td></tr>`; });
  });
}
statsEl.addEventListener("click", (event) => {
  const button = event.target.closest("[data-platform]");
  if (!button) return;
  document.getElementById("platform").value = button.dataset.platform;
  document.getElementById("type").value = button.dataset.type || "";
  state.sourceId = "";
  state.offset = 0;
  loadLibrary().catch((err) => { grid.innerHTML = `<tr><td class="empty" colspan="8">${escapeHtml(err.message)}</td></tr>`; });
});
prev.addEventListener("click", () => {
  state.offset = Math.max(0, state.offset - state.limit);
  loadLibrary().catch((err) => { grid.innerHTML = `<tr><td class="empty" colspan="8">${escapeHtml(err.message)}</td></tr>`; });
});
next.addEventListener("click", () => {
  state.offset += state.limit;
  loadLibrary().catch((err) => { grid.innerHTML = `<tr><td class="empty" colspan="8">${escapeHtml(err.message)}</td></tr>`; });
});
document.getElementById("clear-source").addEventListener("click", () => {
  state.sourceId = "";
  state.offset = 0;
  loadLibrary().catch((err) => { grid.innerHTML = `<tr><td class="empty" colspan="8">${escapeHtml(err.message)}</td></tr>`; });
});

async function openRow(row) {
  const id = row.dataset.id;
  const cached = state.items.find((work) => (work.assets || []).some((item) => item.id === id));
  if (cached) {
    openWork(cached, id);
    return;
  }
  const body = await api("/api/v1/library/" + id);
  const sourceId = body.item.source && body.item.source.id;
  if (!sourceId) {
    openWork({ source: body.item.source, assets: [body.item] }, id);
    return;
  }
  const listed = await api("/api/v1/library?group=source&source_id=" + encodeURIComponent(sourceId) + "&limit=1");
  const work = (listed.items && listed.items[0]) || { source: body.item.source, assets: [body.item] };
  openWork(work, id);
}

grid.addEventListener("click", (event) => {
  if (event.target.closest("[data-go]")) {
    showView("ingest");
    return;
  }
  if (event.target.closest("a")) return;
  const row = event.target.closest("[data-id]");
  if (!row) return;
  openRow(row);
});
grid.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  if (event.target.closest("a, button")) return;
  const row = event.target.closest("[data-id]");
  if (!row) return;
  event.preventDefault();
  openRow(row);
});

function syncDetailSave() {
  const category = document.getElementById("detail-category").value.trim();
  const note = document.getElementById("detail-note").value.trim();
  const industry = document.getElementById("detail-industry").value.trim();
  const changed = category !== (state.savedCategory || "")
    || note !== (state.savedNote || "").trim()
    || industry !== (state.savedIndustry || "").trim();
  document.getElementById("detail-save").disabled = !changed;
}

document.getElementById("detail-category").addEventListener("input", syncDetailSave);
document.getElementById("detail-note").addEventListener("input", syncDetailSave);
document.getElementById("detail-industry").addEventListener("input", syncDetailSave);

document.getElementById("detail-close").addEventListener("click", () => detail.close());

document.getElementById("detail-save").addEventListener("click", async () => {
  if (!state.current || document.getElementById("detail-save").disabled) return;
  const status = document.getElementById("detail-status");
  const category = document.getElementById("detail-category").value.trim();
  const note = document.getElementById("detail-note").value;
  const industry = document.getElementById("detail-industry").value.trim();
  status.textContent = "保存中…";
  try {
    const body = await api("/api/v1/library/" + state.current.id, {
      method: "PATCH",
      body: JSON.stringify({ note, category, industry }),
    });
    state.current = body.item;
    state.savedCategory = category;
    state.savedNote = note.trim();
    state.savedIndustry = industry;
    document.getElementById("detail-industry-view").textContent = industry || "未识别";
    syncDetailSave();
    status.textContent = "已保存";
    await loadLibrary();
  } catch (err) {
    status.textContent = err.message;
  }
});

document.getElementById("detail-delete").addEventListener("click", async () => {
  if (!state.current) return;
  if (!confirm("从素材库删除这条，并删除 OSS 上的文件？")) return;
  await api("/api/v1/library/" + state.current.id, { method: "DELETE" });
  detail.close();
  state.current = null;
  await loadLibrary();
});

document.getElementById("ingest-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = document.getElementById("ingest-status");
  const box = document.getElementById("ingest-results");
  const button = document.getElementById("ingest-go");
  const chunks = document.getElementById("ingest-text").value.split(/\n\s*\n/).map((item) => item.trim()).filter(Boolean);
  if (!chunks.length) {
    status.textContent = "先粘贴分享文案";
    return;
  }
  if (chunks.length > 20) {
    status.textContent = "一次最多 20 条";
    return;
  }
  button.disabled = true;
  status.textContent = "解析并上传中…";
  box.innerHTML = "";
  try {
    const body = await api("/api/v1/parse", {
      method: "POST",
      body: JSON.stringify({ texts: chunks, download: true }),
    });
    status.textContent = `成功 ${body.saved} 条链接，失败 ${body.failed} 条`;
    box.innerHTML = body.results.map((item) => {
      if (!item.ok) {
        return `<article class="result-line bad">${escapeHtml(item.error.message)}</article>`;
      }
      const assets = item.assets || [];
      const failed = assets.find((asset) => asset.error);
      const note = failed ? shortStoreError(failed.error) : `拆成 ${assets.length} 条素材`;
      const source = item.source || {};
      return `<article class="result-line">
        <div>
          <strong>${escapeHtml(platformName(source.platform))}</strong>
          <p>${escapeHtml((source.content || "").slice(0, 72))}</p>
          <p class="${failed ? "warn" : "muted"}">${escapeHtml(note)}</p>
        </div>
        <button type="button" data-source="${escapeHtml(source.id)}">查看这批</button>
      </article>`;
    }).join("");
    state.offset = 0;
    await loadLibrary();
  } catch (err) {
    status.textContent = err.message;
  } finally {
    button.disabled = false;
  }
});

document.getElementById("ingest-results").addEventListener("click", (event) => {
  const button = event.target.closest("[data-source]");
  if (!button) return;
  state.sourceId = button.dataset.source;
  state.offset = 0;
  showView("library");
  loadLibrary().catch((err) => { grid.innerHTML = `<tr><td class="empty" colspan="8">${escapeHtml(err.message)}</td></tr>`; });
});

function fillApi() {
  const origin = location.origin;
  document.getElementById("api-parse").textContent =
    `POST ${origin}/api/v1/parse\nAuthorization: Bearer <API Key>\nContent-Type: application/json\n\n{\n  "platform": "douyin",\n  "author": "作者",\n  "zanCount": 1649000,\n  "commentCount": 12000,\n  "comments": [{"nickname": "评论人", "content": "评论", "zanCount": 1, "isZan": false, "isAuthor": false, "ip": "福建"}],\n  "liked": false,\n  "shareLink": "分享文案或链接",\n  "collectedAt": 1793328490129\n}\n\n也可以直接传这个对象组成的数组。`;
  document.getElementById("api-library").textContent =
    `GET ${origin}/api/v1/library?group=source&current=1&size=100&industry=美妆\nAuthorization: Bearer <API Key>\n\nitems[].source 是作品：文案、所属行业、点赞、评论、对方上报的字段。\nitems[].assets[] 是这条作品里的每张图、每个视频。\nassets[].href 有值时，用同一个请求头再 GET ${origin}{href}，拿到的就是文件。\n\ntotal 是作品数。超过 100 条时 current 加 1 再请求，直到取完。按行业筛选用 industry=美妆，搜索框也会匹配行业。`;
}

document.querySelectorAll("[data-copy]").forEach((button) => {
  button.addEventListener("click", async () => {
    const text = document.getElementById(button.dataset.copy).textContent;
    try {
      await navigator.clipboard.writeText(text);
      button.textContent = "已复制";
    } catch {
      button.textContent = "复制失败";
    }
    setTimeout(() => { button.textContent = "复制"; }, 1200);
  });
});

async function boot() {
  try {
    const me = await api("/api/admin/me");
    renderOss(me.oss);
    showApp();
    fillApi();
    await loadLibrary();
  } catch (err) {
    if (err.status === 401) showLogin();
    else loginError.textContent = err.message;
  }
}

boot();
