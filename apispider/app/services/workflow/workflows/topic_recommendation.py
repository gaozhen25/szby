"""Topic recommendation workflow."""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.ai_service import AI_SERVICE_FORBIDDEN_SENTINEL

from .base import BaseWorkflow, WorkflowRegister

TOPIC_RECOMMENDATION_COUNT = 8
MIN_VALID_TOPIC_COUNT = 4
TOPIC_CONTENT_TYPES = ("image", "video")


def build_topic_recommendation_system_prompt() -> str:
    return (
        "你是社交媒体账号运营选题策划助手。"
        "只输出 JSON，不输出 markdown。"
        "选题必须贴合账号定位、转化目标、账号平台和知识库。"
        "避免和现有选题标题简单重复。"
        "每条选题必须有推荐理由和适合平台。图文选题必须绑定输入中的一条爆款参考笔记。"
    )


def build_topic_recommendation_user_prompt(context: dict[str, Any], count: int = TOPIC_RECOMMENDATION_COUNT) -> str:
    account = context.get("account") or {}
    account_platforms = [str(item).strip() for item in account.get("platforms") or [] if str(item).strip()]
    if not account_platforms and str(account.get("platform") or "").strip():
        account_platforms = [str(account.get("platform") or "").strip()]
    if not account_platforms:
        account_platforms = ["小红书"]
    account_report = context.get("accountReport")
    if account_report:
        report_lines = [
            "已生成账号报告证据:",
            "目标用户画像:",
            json.dumps(account_report.get("targetUserProfile") or {}, ensure_ascii=False),
            "爆款内容证据:",
            json.dumps(account_report.get("hotContents") or [], ensure_ascii=False),
            "相似账号与内容策略:",
            json.dumps(
                {
                    "similarAccounts": account_report.get("similarAccounts") or [],
                    "contentStrategy": account_report.get("contentStrategy") or {},
                },
                ensure_ascii=False,
            ),
            "合规限制:",
            json.dumps(account_report.get("complianceRules") or [], ensure_ascii=False),
            "报告来源摘要:",
            json.dumps(account_report.get("sourceMeta") or {}, ensure_ascii=False),
        ]
    else:
        report_lines = ["已生成账号报告证据:", "无已生成账号报告。"]
    lines = [
        "请基于以下账号信息生成新一批推荐选题。",
        "",
        "账号档案:",
        f"- 账号名称: {account.get('name') or ''}",
        f"- 账号类型: {account.get('type') or ''}",
        f"- 账号描述: {account.get('description') or ''}",
        f"- 运营目的: {account.get('purpose') or ''}",
        f"- 行业: {account.get('industry') or ''}",
        f"- 产品/服务: {account.get('productService') or ''}",
        f"- 目标城市: {account.get('targetCity') or ''}",
        f"- 目标人群: {account.get('targetAudience') or ''}",
        f"- 转化目标: {account.get('conversionGoal') or ''}",
        f"- 已选平台: {'、'.join(account.get('platforms') or [])}",
        "",
        "知识库:",
        str(context.get("knowledgeContext") or "无"),
        "",
        "已有选题标题，请避免简单重复:",
        "、".join(context.get("existingTopicTitles") or []) or "无",
        "",
        *report_lines,
        "",
        "输出要求:",
        "- 如有账号报告，必须基于报告证据提炼选题方向，服务目标用户和转化目标。",
        "- 可借鉴爆款和相似账号的内容特征，但不得直接复制竞品标题。",
        "- 图文选题必须填写 referenceContentId，且只能使用爆款内容证据中的 contentId。",
        "- 图文选题要说明如何结合目标用户画像借鉴该参考笔记；视频选题的 referenceContentId 可为空。",
        "- 必须遵守合规限制，避免报告标记的风险表达和方向。",
        "- 只允许输出一个 JSON 对象，不要输出解释、markdown、代码块或前后缀文本。",
        "- JSON 第一字符必须是 {，最后字符必须是 }。",
        f"- topics 数组必须包含 {count} 条选题。",
        f"- 内容形式必须各占一半: {count // 2} 条图文 contentType=image，{count // 2} 条视频 contentType=video。",
        "- platforms 只能从账号已选平台中选择。",
        "JSON 示例:",
        json.dumps(
            {
                "topics": [
                    {
                        "title": "30 字以内中文标题",
                        "reason": "60 字以内推荐理由",
                        "platforms": account_platforms[:1],
                        "category": "内容分类",
                        "contentType": "image 或 video",
                        "referenceContentId": "图文必填：爆款内容证据中的 contentId",
                    }
                ]
            },
            ensure_ascii=False,
        ),
    ]
    return "\n".join(lines)


def normalize_recommended_topics(
    raw_topics: Any,
    allowed_platforms: list[str],
    canonical_platform: str,
    hot_contents: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    allowed = [str(item).strip() for item in allowed_platforms if str(item).strip()]
    canonical = str(canonical_platform or "").strip()
    fallback_platform = canonical if canonical and canonical in allowed else (allowed[0] if allowed else "小红书")
    fallbacks: list[str] = []
    normalized: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    reference_notes = [
        {
            "contentId": str(item.get("contentId") or "").strip(),
            "platform": str(item.get("platform") or "").strip(),
            "title": str(item.get("title") or "").strip(),
            "selectionReason": str(item.get("selectionReason") or "").strip(),
            "publicUrl": str(item.get("publicUrl") or "").strip(),
            "contentType": str(item.get("contentType") or "unknown").strip(),
            "metrics": dict(item.get("metrics") or {}),
        }
        for item in (hot_contents or [])
        if isinstance(item, dict)
        and str(item.get("contentId") or "").strip()
        and str(item.get("publicUrl") or "").strip()
        and str(item.get("contentType") or "").strip() == "image"
    ]
    reference_by_id = {item["contentId"]: item for item in reference_notes}
    for item in raw_topics or []:
        if not isinstance(item, dict):
            fallbacks.append("skipped non-object topic")
            continue
        title = str(item.get("title") or "").strip()
        if not title or title in seen_titles:
            fallbacks.append("skipped empty or duplicate title")
            continue
        seen_titles.add(title)
        raw_platforms = item.get("platforms") if isinstance(item.get("platforms"), list) else []
        platforms = [str(platform).strip() for platform in raw_platforms if str(platform).strip() in allowed]
        if not platforms:
            platforms = [fallback_platform]
            fallbacks.append(f"{title}: platform fallback")
        reason = str(item.get("reason") or "").strip()
        if not reason:
            reason = "贴合账号定位、目标人群和当前内容转化目标。"
            fallbacks.append(f"{title}: reason fallback")
        category = str(item.get("category") or "").strip() or "内容种草"
        content_type = str(item.get("contentType") or item.get("type") or "").strip() or "image"
        if content_type not in {"image", "video"}:
            content_type = "image"
            fallbacks.append(f"{title}: contentType fallback")
        reference_note: dict[str, Any] = {}
        if content_type == "image":
            requested_reference_id = str(item.get("referenceContentId") or "").strip()
            reference_note = reference_by_id.get(requested_reference_id) or (
                reference_notes[len(normalized) % len(reference_notes)] if reference_notes else {}
            )
            if not reference_note:
                fallbacks.append(f"{title}: missing hot-content reference")
            elif requested_reference_id != reference_note["contentId"]:
                fallbacks.append(f"{title}: referenceNote fallback")
        normalized.append(
            {
                "title": title,
                "source": "AI推荐",
                "category": category,
                "contentType": content_type,
                "reason": reason,
                "platforms": platforms,
                "referenceNote": reference_note,
            }
        )
    return normalized, fallbacks


def parse_topic_recommendation_payload(raw: Any) -> dict[str, Any] | list[Any] | None:
    if isinstance(raw, (dict, list)):
        return raw

    text = str(raw or "").strip()
    if not text:
        return None

    fence = re.match(r"^```(?:json)?\s*\n(.*?)\n```\s*$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start_candidates = [idx for idx in (text.find("{"), text.find("[")) if idx >= 0]
        start = min(start_candidates) if start_candidates else -1
        end = max(text.rfind("}"), text.rfind("]"))
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None

    return parsed if isinstance(parsed, (dict, list)) else None


def balance_topic_content_types(
    topics: list[dict[str, Any]],
    count: int = TOPIC_RECOMMENDATION_COUNT,
) -> tuple[list[dict[str, Any]], list[str]]:
    target_count = min(max(count, 0), len(topics))
    if target_count <= 0:
        return [], []

    video_target = target_count // 2
    targets = {"image": target_count - video_target, "video": video_target}
    indexed_topics = list(enumerate(topics))
    selected: list[tuple[int, dict[str, Any]]] = []
    used_indexes: set[int] = set()
    fallbacks: list[str] = []
    fallback_reference_note = next(
        (dict(topic.get("referenceNote") or {}) for topic in topics if topic.get("referenceNote")),
        {},
    )

    for content_type in TOPIC_CONTENT_TYPES:
        selected_count = 0
        for index, topic in indexed_topics:
            if index in used_indexes or topic.get("contentType") != content_type:
                continue
            selected.append((index, topic))
            used_indexes.add(index)
            selected_count += 1
            if selected_count >= targets[content_type]:
                break

    for content_type in TOPIC_CONTENT_TYPES:
        selected_count = sum(1 for _, topic in selected if topic.get("contentType") == content_type)
        while selected_count < targets[content_type]:
            replacement = next(((index, topic) for index, topic in indexed_topics if index not in used_indexes), None)
            if replacement is None:
                break
            index, topic = replacement
            balanced_topic = {**topic, "contentType": content_type}
            if content_type == "image" and not balanced_topic.get("referenceNote"):
                if fallback_reference_note:
                    balanced_topic["referenceNote"] = fallback_reference_note
            selected.append((index, balanced_topic))
            used_indexes.add(index)
            selected_count += 1
            fallbacks.append(f"{balanced_topic.get('title') or 'untitled'}: contentType balanced")

    if len(selected) < target_count:
        for index, topic in indexed_topics:
            if index in used_indexes:
                continue
            selected.append((index, topic))
            used_indexes.add(index)
            if len(selected) >= target_count:
                break

    selected.sort(key=lambda item: item[0])
    return [topic for _, topic in selected[:target_count]], fallbacks


@WorkflowRegister.register
class TopicRecommendationWorkflow(BaseWorkflow):
    type = "topic_recommendation"

    async def execute(self) -> dict[str, Any]:
        record: Any = self.store.get_workflow(self.workflow_id)
        if record is None:
            raise ValueError(f"workflow {self.workflow_id} not found")

        self.store.update_progress(self.workflow_id, progress=10, current_stage="context_loading")
        context = self.store.topic_recommendation_context(record.account_id)
        if not context:
            raise ValueError("topic recommendation context is unavailable")

        prompt = build_topic_recommendation_user_prompt(context)
        step_id = self.store.create_step(
            workflow_id=self.workflow_id,
            user_id=record.user_id,
            account_id=record.account_id,
            step_type="topic_recommendation",
            input_payload={"prompt": prompt},
            group_key="topic_recommendation",
        )

        self.store.update_progress(self.workflow_id, progress=40, current_stage="ai_recommendation")
        try:
            self.store.mark_step_running(step_id)
            raw = await self.ai_service.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=build_topic_recommendation_system_prompt(),
                temperature=0.7,
            )
        except Exception as exc:
            self.store.mark_step_failed(step_id, str(exc) or exc.__class__.__name__)
            raise

        if raw == AI_SERVICE_FORBIDDEN_SENTINEL:
            self.store.mark_step_failed(step_id, "AI service token is not configured")
            raise ValueError("AI service token is not configured")
        parsed = parse_topic_recommendation_payload(raw)
        if not parsed:
            self.store.mark_step_failed(step_id, "topic recommendation returned invalid JSON")
            raise ValueError("topic recommendation returned invalid JSON")
        raw_topics = parsed.get("topics") if isinstance(parsed, dict) else parsed

        self.store.update_progress(self.workflow_id, progress=75, current_stage="normalization")
        topics, fallbacks = normalize_recommended_topics(
            raw_topics,
            list((context.get("account") or {}).get("platforms") or []),
            str((context.get("account") or {}).get("platform") or ""),
            list((context.get("accountReport") or {}).get("hotContents") or []),
        )
        if len(topics) < MIN_VALID_TOPIC_COUNT:
            self.store.mark_step_failed(step_id, f"at least {MIN_VALID_TOPIC_COUNT} valid topics are required")
            raise ValueError(f"at least {MIN_VALID_TOPIC_COUNT} valid topics are required")
        topics, balance_fallbacks = balance_topic_content_types(topics, TOPIC_RECOMMENDATION_COUNT)
        fallbacks.extend(balance_fallbacks)

        result = {
            "knowledgeBaseUsed": bool(context.get("knowledgeBaseUsed")),
            "accountContext": context.get("account") or {},
            "knowledgeContext": context.get("knowledgeContext") or "",
            "accountReport": context.get("accountReport"),
            "topics": topics,
            "fallbacks": fallbacks,
        }
        self.store.update_progress(self.workflow_id, progress=90, current_stage="topic_replacement")
        try:
            self.store.replace_account_topics(
                workflow_id=self.workflow_id,
                user_id=record.user_id,
                account_id=record.account_id,
                topics=topics,
            )
        except Exception as exc:
            self.store.mark_step_failed(step_id, str(exc) or exc.__class__.__name__)
            raise
        self.store.mark_step_completed(step_id, {"raw": raw, "topics": topics, "fallbacks": fallbacks})
        self.store.update_progress(self.workflow_id, progress=100, current_stage="completed", result_payload=result)
        return result
