"""爆款参考内容的类型均衡选择。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar


_ContentItem = TypeVar("_ContentItem")


def select_balanced_hot_contents(
    candidates: Sequence[_ContentItem],
    *,
    limit: int = 8,
    target_per_type: int = 4,
) -> list[_ContentItem]:
    """保留原排名，优先选满视频和图文目标，缺口由其他候选补齐。"""

    if limit <= 0:
        return []

    selected_ids: set[int] = set()
    selected: list[_ContentItem] = []
    for content_type in ("video", "image"):
        matches = [
            item
            for item in candidates
            if getattr(item, "content_type", "unknown") == content_type
        ][:target_per_type]
        selected.extend(matches)
        selected_ids.update(id(item) for item in matches)

    if len(selected) < limit:
        for item in candidates:
            if id(item) in selected_ids:
                continue
            selected.append(item)
            selected_ids.add(id(item))
            if len(selected) >= limit:
                break

    original_rank = {id(item): index for index, item in enumerate(candidates)}
    return sorted(selected[:limit], key=lambda item: original_rank[id(item)])
