#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同进程直传 dict 演示 — 不读 JSON。在项目根目录执行: uv run python scripts/direct_dict_demo.py [关键词]"""

from __future__ import annotations

import json
import sys

from sdk import keyword_ex


def main() -> None:
    keyword = sys.argv[1] if len(sys.argv) > 1 else "猫咪"
    max_notes = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    print(f"[demo] keyword_ex('xhs', {keyword!r}, max_notes_count={max_notes})")
    result = keyword_ex("xhs", keyword, max_notes_count=max_notes)

    if result["code"] != 0:
        raise SystemExit(f"crawl failed: {result.get('message')}")

    data = result["data"]
    summary = data["summary"]
    print(f"[demo] note_count={summary.get('note_count')}  source_file={summary.get('source_file')}")

    for i, note in enumerate(data["notes"][:3], 1):
        title = (note.get("title") or "")[:50]
        print(f"  [{i}] {title}  👍 {note.get('liked_count')}")

    print("\n[demo] full dict (truncated):")
    print(json.dumps(result, ensure_ascii=False, indent=2)[:800], "...")


if __name__ == "__main__":
    main()
