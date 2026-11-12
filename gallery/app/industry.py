"""Classify a work into an industry from its title and tags via Volcengine Ark."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

ARK_URL = os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3/responses").strip()
ARK_MODEL = os.getenv("ARK_MODEL", "deepseek-v4-1-flash-economy-261017").strip()

_PROMPT = """根据下面作品的标题和标签，判断它最可能属于哪个行业。
只回复一个简短的中文行业名，不要解释，不要标点，不要换行。
优先从这些里选：美妆、护肤、服饰、健身、运动、美食、餐饮、母婴、教育、数码、家电、家居、旅游、汽车、财经、医疗、游戏、娱乐、宠物、农业、其他。
如果都不合适，自己起一个不超过 6 个字的行业名。

标题：{title}
标签：{tags}
文案：{content}
"""


def classify_industry(title: str, tags: list[str] | None = None, content: str = "") -> str:
    """Return a short industry label, or empty when Ark is not configured / fails."""
    key = os.getenv("ARK_API_KEY", "").strip()
    if not key:
        return ""
    title = (title or "").strip()
    content = (content or "").strip()
    tag_text = "、".join(t.strip() for t in (tags or []) if isinstance(t, str) and t.strip())
    if not title and not tag_text and not content:
        return ""
    prompt = _PROMPT.format(
        title=title[:200] or "（无）",
        tags=tag_text[:200] or "（无）",
        content=content[:400] or "（无）",
    )
    try:
        with httpx.Client(timeout=45.0, trust_env=False) as client:
            resp = client.post(
                ARK_URL,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": ARK_MODEL,
                    "thinking": {"type": "disabled"},
                    "input": [
                        {
                            "role": "user",
                            "content": [{"type": "input_text", "text": prompt}],
                        }
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError, ValueError):
        return ""
    return _clean_label(_text_of(data))


def _text_of(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    for key in ("output_text", "text"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    output = data.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, str) and content.strip():
                parts.append(content.strip())
                continue
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    text = block.get("text") or block.get("output_text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
        if parts:
            return "\n".join(parts)
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"].strip()
    return ""


def _clean_label(raw: str) -> str:
    text = (raw or "").strip().splitlines()[0].strip() if raw else ""
    text = re.sub(r"^[\s\"'“”‘’「」【\[]+|[\s\"'“”‘’「」】\].:：;；,，。!！?？]+$", "", text)
    text = re.sub(r"\s+", "", text)
    if not text or text in {"未知", "无", "其他行业"}:
        return ""
    if text == "其他":
        return "其他"
    return text[:20]
