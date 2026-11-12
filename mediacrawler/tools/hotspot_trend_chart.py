# -*- coding: utf-8 -*-
"""热点榜按日搜索量折线图（自包含 HTML，无需外网 CDN）。"""

from __future__ import annotations

import base64
import json
import pathlib
from typing import Any, Dict, List, Optional


def png_file_to_data_uri(png_path: str) -> Optional[str]:
    path = pathlib.Path(png_path)
    if not path.is_file():
        return None
    raw = path.read_bytes()
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def format_trend_date(raw: Any) -> str:
    """``20260630`` / ``2026-07-14 11:00:00`` → 可读横轴。"""
    s = str(raw or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[4:6]}-{s[6:8]}"
    if " " in s:
        # 小时窗口：保留月日+小时
        date_part, time_part = s.split(" ", 1)
        parts = date_part.split("-")
        if len(parts) == 3:
            hh = time_part[:2] if time_part else ""
            return f"{parts[1]}-{parts[2]} {hh}h" if hh else f"{parts[1]}-{parts[2]}"
    if len(s) >= 10 and s[4] == "-":
        return s[5:10]
    return s


def item_trend_series(item: Dict[str, Any]) -> Dict[str, List]:
    dates: List[str] = []
    values: List[float] = []
    for point in item.get("trends") or []:
        if not isinstance(point, dict):
            continue
        dates.append(format_trend_date(point.get("date")))
        try:
            values.append(float(point.get("value") or 0))
        except (TypeError, ValueError):
            values.append(0.0)
    return {"dates": dates, "values": values}


def enrich_items_with_series(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """给每条热点附上 chart 友好的 dates/values（原地写 trend_series）。"""
    for item in items:
        item["trend_series"] = item_trend_series(item)
    return items


def build_trend_chart_html(
    items: List[Dict[str, Any]],
    meta: Optional[Dict[str, Any]] = None,
    top_overlay: int = 10,
) -> str:
    """生成自包含折线图 HTML（TopN 对比 + 各词明细）。"""
    meta = meta or {}
    series_payload = []
    for item in items:
        series = item.get("trend_series") or item_trend_series(item)
        wordcloud_uri = item.get("wordcloud_data_uri") or ""
        if not wordcloud_uri and item.get("wordcloud_path"):
            wordcloud_uri = png_file_to_data_uri(str(item["wordcloud_path"])) or ""
        series_payload.append(
            {
                "rank": item.get("rank"),
                "key_word": item.get("key_word") or "",
                "search_score": item.get("search_score"),
                "dates": series.get("dates") or [],
                "values": series.get("values") or [],
                "wordcloud_data_uri": wordcloud_uri,
                "comment_count": item.get("comment_count"),
            }
        )

    board_name = meta.get("board_name") or "搜索热点总榜"
    title = f"{board_name} · 搜索量趋势"
    data_json = json.dumps(series_payload, ensure_ascii=False)
    meta_json = json.dumps(
        {
            "board_name": board_name,
            "date_window": meta.get("date_window"),
            "fetched_count": meta.get("fetched_count", len(items)),
            "total_count": meta.get("total_count"),
            "top_overlay": top_overlay,
        },
        ensure_ascii=False,
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<style>
  :root {{
    --bg: #0f1419;
    --panel: #1a2332;
    --text: #e7ecf3;
    --muted: #8b9bb4;
    --accent: #3d9cff;
    --grid: #2a3548;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    background: radial-gradient(1200px 600px at 10% -10%, #1c2a44 0%, var(--bg) 55%);
    color: var(--text);
    padding: 28px 20px 60px;
  }}
  h1 {{ font-size: 1.45rem; font-weight: 650; margin: 0 0 22px; }}
  .panel {{
    background: var(--panel);
    border: 1px solid #243044;
    border-radius: 14px;
    padding: 16px 16px 8px;
    margin-bottom: 18px;
  }}
  .panel h2 {{
    font-size: 1rem;
    margin: 0 0 10px;
    font-weight: 600;
  }}
  canvas.main {{ width: 100%; height: 400px; display: block; cursor: crosshair; }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 14px;
  }}
  .card canvas {{ width: 100%; height: 170px; display: block; cursor: crosshair; }}
  .card .meta {{
    display: flex;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 6px;
    font-size: 0.85rem;
  }}
  .card .meta .kw {{ font-weight: 600; }}
  .card .meta .sc {{ color: var(--muted); }}
  .card .wc {{
    margin-top: 10px;
    border-radius: 10px;
    overflow: hidden;
    background: #0c1118;
    border: 1px solid #243044;
  }}
  .card .wc img {{
    display: block;
    width: 100%;
    height: auto;
    vertical-align: middle;
  }}
  .card .wc-empty {{
    margin-top: 10px;
    color: var(--muted);
    font-size: 0.8rem;
    text-align: center;
    padding: 18px 8px;
    border: 1px dashed #2a3548;
    border-radius: 10px;
  }}
  #tip {{
    position: fixed;
    z-index: 99;
    pointer-events: none;
    display: none;
    background: rgba(15, 20, 25, 0.92);
    border: 1px solid #3d9cff;
    color: #e7ecf3;
    padding: 8px 10px;
    border-radius: 8px;
    font-size: 12px;
    line-height: 1.45;
    box-shadow: 0 8px 24px rgba(0,0,0,.35);
    white-space: nowrap;
  }}
</style>
</head>
<body>
  <h1>{title}</h1>
  <div class="panel">
    <h2>Top <span id="topn"></span> 词 · 按日搜索量对比</h2>
    <canvas id="overlay" class="main"></canvas>
  </div>
  <div class="panel">
    <h2>全部词条趋势</h2>
    <div class="grid" id="cards"></div>
  </div>
  <div id="tip"></div>
<script>
const ITEMS = {data_json};
const META = {meta_json};

const COLORS = [
  "#3d9cff","#52d6a7","#f5a524","#ff6b6b","#b388ff",
  "#4ecdc4","#ffe66d","#ff8fab","#7bdff2","#c3f584"
];
const tipEl = document.getElementById("tip");

function niceMax(v) {{
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  return Math.ceil(v / p) * p;
}}

function shortNum(n) {{
  const abs = Math.abs(n);
  if (abs >= 1e8) return (n / 1e8).toFixed(1) + "亿";
  if (abs >= 1e4) return (n / 1e4).toFixed(1) + "万";
  return String(Math.round(n));
}}

function bindLineChart(canvas, datasets, options = {{}}) {{
  const showXLabels = options.showXLabels !== false;
  let activeKey = null;
  let hits = [];

  function paint() {{
    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth || 600;
    const cssH = canvas.clientHeight || 220;
    canvas.width = Math.floor(cssW * dpr);
    canvas.height = Math.floor(cssH * dpr);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const pad = {{
      t: options.legend ? 28 : 14,
      r: 18,
      b: showXLabels ? 28 : 14,
      l: 54,
    }};
    const w = cssW - pad.l - pad.r;
    const h = cssH - pad.t - pad.b;

    const dates = Array.from(new Set(
      datasets.flatMap(ds => ds.dates || [])
    )).sort();

    let maxV = 0;
    datasets.forEach(ds => (ds.values || []).forEach(v => {{ if (v > maxV) maxV = v; }}));
    maxV = niceMax(maxV);
    const minV = 0;

    ctx.clearRect(0, 0, cssW, cssH);
    ctx.fillStyle = "#1a2332";
    ctx.fillRect(0, 0, cssW, cssH);

    ctx.strokeStyle = "#2a3548";
    ctx.fillStyle = "#8b9bb4";
    ctx.font = "11px sans-serif";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    const yTicks = 4;
    for (let i = 0; i <= yTicks; i++) {{
      const y = pad.t + (h * i) / yTicks;
      const val = maxV - (maxV - minV) * (i / yTicks);
      ctx.beginPath();
      ctx.moveTo(pad.l, y);
      ctx.lineTo(pad.l + w, y);
      ctx.stroke();
      ctx.fillText(shortNum(val), pad.l - 8, y);
    }}

    const n = Math.max(dates.length, 1);
    if (showXLabels) {{
      // Top10：全部日期同一水平线上平行排布
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillStyle = "#8b9bb4";
      ctx.font = n > 12 ? "10px sans-serif" : "11px sans-serif";
      const y = pad.t + h + 10;
      dates.forEach((d, i) => {{
        const x = pad.l + (n === 1 ? w / 2 : (w * i) / (n - 1));
        ctx.fillText(d, x, y);
      }});
    }}

    hits = [];
    datasets.forEach((ds, di) => {{
      const color = COLORS[di % COLORS.length];
      const map = new Map();
      (ds.dates || []).forEach((d, i) => map.set(d, ds.values[i]));
      const pts = dates.map((d, i) => {{
        const v = map.has(d) ? map.get(d) : null;
        const x = pad.l + (dates.length === 1 ? w / 2 : (w * i) / (dates.length - 1));
        if (v === null || v === undefined) return null;
        const y = pad.t + h - ((v - minV) / (maxV - minV || 1)) * h;
        return {{ x, y, v, date: d, key_word: ds.key_word, rank: ds.rank, color }};
      }});

      ctx.strokeStyle = color;
      ctx.lineWidth = options.thick ? 2.4 : 2;
      ctx.beginPath();
      let started = false;
      pts.forEach(p => {{
        if (!p) {{ started = false; return; }}
        if (!started) {{ ctx.moveTo(p.x, p.y); started = true; }}
        else ctx.lineTo(p.x, p.y);
      }});
      ctx.stroke();

      pts.forEach(p => {{
        if (!p) return;
        const key = `${{di}}|${{p.date}}`;
        hits.push({{ ...p, key, di }});
        const active = activeKey === key;
        ctx.beginPath();
        ctx.fillStyle = color;
        ctx.arc(p.x, p.y, active ? 5 : 2.8, 0, Math.PI * 2);
        ctx.fill();
        if (active) {{
          ctx.strokeStyle = "#fff";
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }}
      }});
    }});

    if (options.legend) {{
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      let lx = pad.l;
      let ly = 4;
      datasets.forEach((ds, di) => {{
        const color = COLORS[di % COLORS.length];
        const label = `#${{ds.rank}} ${{ds.key_word}}`;
        ctx.fillStyle = color;
        ctx.fillRect(lx, ly + 3, 10, 10);
        ctx.fillStyle = "#e7ecf3";
        ctx.fillText(label, lx + 14, ly);
        lx += ctx.measureText(label).width + 28;
        if (lx > cssW - 120) {{ lx = pad.l; ly += 16; }}
      }});
    }}
  }}

  function nearestHit(mx, my) {{
    let best = null;
    let bestDist = 14;
    hits.forEach(p => {{
      const d = Math.hypot(p.x - mx, p.y - my);
      if (d < bestDist) {{ bestDist = d; best = p; }}
    }});
    return best;
  }}

  function showTip(hit, clientX, clientY) {{
    const kw = hit.key_word ? `<div style="color:#8b9bb4">#${{hit.rank}} ${{hit.key_word}}</div>` : "";
    tipEl.innerHTML = `${{kw}}<div>日期 ${{hit.date}}</div><div>热度 ${{shortNum(hit.v)}}</div>`;
    tipEl.style.display = "block";
    const tw = tipEl.offsetWidth || 120;
    const th = tipEl.offsetHeight || 48;
    let left = clientX + 14;
    let top = clientY + 14;
    if (left + tw > window.innerWidth - 8) left = clientX - tw - 12;
    if (top + th > window.innerHeight - 8) top = clientY - th - 12;
    tipEl.style.left = left + "px";
    tipEl.style.top = top + "px";
  }}

  function hideTip() {{
    tipEl.style.display = "none";
  }}

  canvas.onmousemove = (e) => {{
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const hit = nearestHit(mx, my);
    const nextKey = hit ? hit.key : null;
    if (nextKey !== activeKey) {{
      activeKey = nextKey;
      paint();
    }}
    if (hit) showTip(hit, e.clientX, e.clientY);
    else hideTip();
  }};
  canvas.onmouseleave = () => {{
    activeKey = null;
    hideTip();
    paint();
  }};

  paint();
  return paint;
}}

function render() {{
  const topN = META.top_overlay || 10;
  document.getElementById("topn").textContent = String(Math.min(topN, ITEMS.length));

  const overlayItems = ITEMS.slice(0, topN).filter(it => (it.values || []).length);
  bindLineChart(document.getElementById("overlay"), overlayItems, {{
    legend: true, thick: true, showXLabels: true,
  }});

  const cards = document.getElementById("cards");
  ITEMS.forEach((it, idx) => {{
    const card = document.createElement("div");
    card.className = "panel card";
    const wcHtml = it.wordcloud_data_uri
      ? `<div class="wc"><img alt="词云 #${{it.rank}} ${{it.key_word}}" src="${{it.wordcloud_data_uri}}"/></div>`
      : `<div class="wc-empty">暂无评论词云</div>`;
    card.innerHTML = `
      <div class="meta">
        <span class="kw">#${{it.rank}} ${{it.key_word}}</span>
        <span class="sc">热度 ${{shortNum(it.search_score || 0)}}</span>
      </div>
      <canvas id="c${{idx}}"></canvas>
      ${{wcHtml}}`;
    cards.appendChild(card);
    bindLineChart(document.getElementById(`c${{idx}}`), [it], {{
      legend: false, showXLabels: false,
    }});
  }});
}}

window.addEventListener("resize", () => {{
  hideTip();
  document.getElementById("cards").innerHTML = "";
  render();
}});
function hideTip() {{ tipEl.style.display = "none"; }}
render();
</script>
</body>
</html>
"""


async def write_hotspot_trend_chart(
    json_path: str,
    items: List[Dict[str, Any]],
    meta: Optional[Dict[str, Any]] = None,
) -> str:
    """与热点榜 JSON 同目录写入 ``*_趋势.html``，返回路径。"""
    import aiofiles

    html_path = json_path[:-5] + "_趋势.html" if json_path.endswith(".json") else json_path + "_趋势.html"
    html = build_trend_chart_html(items, meta=meta)
    async with aiofiles.open(html_path, "w", encoding="utf-8") as f:
        await f.write(html)
    return html_path
