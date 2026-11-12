import { api } from "./lib/api.js?v=1";
import { escapeHtml, platformName } from "./lib/text.js?v=1";
import { slidesOf } from "./lib/watch.js?v=2";

const form = document.getElementById("form");
const input = document.getElementById("text");
const go = document.getElementById("go");
const clearBtn = document.getElementById("clear");
const statusEl = document.getElementById("status");
const result = document.getElementById("result");
const lightbox = document.getElementById("lightbox");
const lightboxImg = document.getElementById("lightbox-img");

const state = { item: null, index: 0 };

function renderStage(slides) {
  const slide = slides[state.index];
  if (!slide) return '<div class="stage-empty">没有可播放的文件</div>';
  if (slide.type === "video") {
    const poster = slide.poster ? ` poster="${escapeHtml(slide.poster)}"` : "";
    return `<video controls playsinline${poster} src="${escapeHtml(slide.src)}"></video>`;
  }
  return `<button type="button" class="stage-still" data-open="1"><img alt="${escapeHtml(slide.label || "图片")}" src="${escapeHtml(slide.src)}" /></button>`;
}

function commentBlock(item) {
  const comments = item.comments || [];
  if (comments.length) {
    const rows = comments.map((comment) => `<p><span class="who">${escapeHtml(comment.author || "匿名")}</span> ${escapeHtml(comment.text || "")}</p>`).join("");
    return `<h2>评论</h2><div class="comments">${rows}</div>`;
  }
  if (item.comment_count) {
    return `<h2>评论</h2><p class="muted">公开页没有评论正文，评论数 ${escapeHtml(item.comment_count)}。</p>`;
  }
  return "";
}

function render(item) {
  state.item = item;
  state.index = 0;
  paint();
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  result.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
}

function paint() {
  const item = state.item;
  if (!item) return;
  const slides = slidesOf(item);
  const slide = slides[state.index] || null;
  const who = [platformName(item.platform), item.author || ""].filter(Boolean).join("，");
  const tags = (item.tags || []).map((tag) => `<span class="chip">#${escapeHtml(tag)}</span>`).join("");
  const film = slides.length > 1
    ? `<div class="film">${slides.map((entry, index) => `
        <button type="button" class="thumb${index === state.index ? " on" : ""}" data-index="${index}">
          ${entry.type === "video" && !entry.poster ? `<span>视频</span>` : `<img alt="" src="${escapeHtml(entry.poster || entry.src)}" />`}
        </button>`).join("")}</div>`
    : "";
  const nav = slides.length > 1
    ? `<button type="button" class="stage-nav prev" data-step="-1" aria-label="上一张">‹</button>
       <button type="button" class="stage-nav next" data-step="1" aria-label="下一张">›</button>`
    : "";
  const download = slide && slide.download
    ? `<a class="dl" href="${escapeHtml(slide.download)}" download="${escapeHtml(slide.name)}">下载${escapeHtml(slide.label)}</a>`
    : "";
  result.classList.remove("hidden");
  result.innerHTML = `
    <div class="watch">
      <div class="stage-col">
        <div class="stage">
          ${nav}
          ${renderStage(slides)}
          <p class="stage-count">${slides.length ? state.index + 1 + " / " + slides.length : ""}</p>
        </div>
        ${film}
      </div>
      <aside class="meta">
        <p class="who">${escapeHtml(who)}</p>
        <p class="caption" id="caption">${escapeHtml(item.content || item.title || "（无文案）")}</p>
        <div class="row-actions">
          <button type="button" id="copy" class="ghost">复制文案</button>
          ${download}
        </div>
        <h2>原始标签</h2>
        <div class="chips">${tags || '<span class="muted">无标签</span>'}</div>
        ${commentBlock(item)}
        <p class="muted via">${escapeHtml(item.via || "")}</p>
      </aside>
    </div>`;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text) {
    statusEl.textContent = "请先粘贴分享链接";
    statusEl.className = "status err";
    return;
  }
  go.disabled = true;
  statusEl.className = "status";
  statusEl.textContent = "解析中…";
  try {
    const body = await api("/api/parse", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    const count = (body.item.medias || []).length;
    statusEl.textContent = "可以观看，" + count + " 个文件";
    render(body.item);
  } catch (err) {
    statusEl.textContent = err.message;
    statusEl.className = "status err";
  } finally {
    go.disabled = false;
  }
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

result.addEventListener("click", async (event) => {
  const step = event.target.closest("[data-step]");
  const thumb = event.target.closest("[data-index]");
  const open = event.target.closest("[data-open]");
  const copy = event.target.closest("#copy");
  const slides = state.item ? slidesOf(state.item) : [];
  if (step && slides.length) {
    state.index = (state.index + Number(step.dataset.step) + slides.length) % slides.length;
    paint();
    return;
  }
  if (thumb) {
    state.index = Number(thumb.dataset.index);
    paint();
    return;
  }
  if (open) {
    const slide = slides[state.index];
    if (!slide || slide.type !== "image") return;
    lightboxImg.src = slide.src;
    lightbox.showModal();
    return;
  }
  if (copy) {
    const text = document.getElementById("caption").textContent;
    try {
      await navigator.clipboard.writeText(text);
      copy.textContent = "已复制";
    } catch {
      copy.textContent = "复制失败";
    }
  }
});

function syncClear() {
  clearBtn.classList.toggle("is-off", !input.value);
}

input.addEventListener("input", syncClear);
clearBtn.addEventListener("click", () => {
  input.value = "";
  syncClear();
  input.focus();
});

document.getElementById("lightbox-close").addEventListener("click", () => lightbox.close());
lightbox.addEventListener("click", (event) => {
  if (event.target === lightbox) lightbox.close();
});

document.addEventListener("keydown", (event) => {
  if (!state.item || event.target.closest("textarea, input")) return;
  if (lightbox.open) return;
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  const slides = slidesOf(state.item);
  if (slides.length < 2) return;
  state.index = (state.index + (event.key === "ArrowRight" ? 1 : -1) + slides.length) % slides.length;
  paint();
});
