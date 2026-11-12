"""账号报告分块 AI 调用契约。

每个分块独立生成、独立校验，避免要求模型一次返回完整报告。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .ai_evidence import build_ai_evidence
from .compliance_prompt import COMPLIANCE_RULES_GUIDANCE
from .hot_content_selection import select_balanced_hot_contents
from .target_audience_prompt import TARGET_AUDIENCE_GUIDANCE
from .models import (
    ComplianceRule,
    ContentStrategy,
    HotContent,
    ReportEvidence,
    SimilarAccount,
    TargetUserProfile,
    TopBlogger,
)
from .response_normalizer import normalize_account_report_response

_FENCED_JSON = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL | re.IGNORECASE)


class _SectionResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class SimilarAccountsResult(_SectionResult):
    similar_accounts: list[SimilarAccount] = Field(
        alias="similarAccounts", max_length=20
    )


class ComplianceRulesResult(_SectionResult):
    compliance_rules: list[ComplianceRule] = Field(
        alias="complianceRules", min_length=1, max_length=20
    )


class TargetUserProfileResult(_SectionResult):
    target_user_profile: TargetUserProfile = Field(alias="targetUserProfile")


class HotContentsResult(_SectionResult):
    hot_contents: list[HotContent] = Field(alias="hotContents", max_length=20)


class TopBloggersResult(_SectionResult):
    top_bloggers: list[TopBlogger] = Field(alias="topBloggers", max_length=10)


class ContentStrategyResult(_SectionResult):
    content_strategy: ContentStrategy = Field(alias="contentStrategy")


@dataclass(frozen=True)
class ReportSectionSpec:
    key: str
    result_model: type[_SectionResult]
    contract: Any
    instruction: str


REPORT_SECTION_SPECS = (
    ReportSectionSpec(
        "similarAccounts",
        SimilarAccountsResult,
        [
            {
                "platform": "平台",
                "creatorHash": "证据中的创作者哈希",
                "name": "账号名",
                "similarityReason": "相似原因",
                "metrics": {},
                "representativeContents": ["代表内容"],
            }
        ],
        "只能从 industryEvidence.similarAccounts 候选中选择，不得使用当前账号或编造账号。",
    ),
    ReportSectionSpec(
        "complianceRules",
        ComplianceRulesResult,
        [
            {
                "riskLevel": "high",
                "expression": "风险表达",
                "reason": "风险原因",
                "suggestion": "替代表达",
                "platforms": ["平台"],
            }
        ],
        COMPLIANCE_RULES_GUIDANCE,
    ),
    ReportSectionSpec(
        "targetUserProfile",
        TargetUserProfileResult,
        {
            "assumption": "信息不足时的一句话假设；无额外假设则为空字符串",
            "categories": [
                {
                    "categoryName": "类别名称",
                    "purchaseMotivation": "一句话购买动机",
                    "maleProfile": {"applicable": True, "description": "150–250 字完整画像"},
                    "femaleProfile": {"applicable": False, "description": "不适用原因"},
                }
            ],
            "priorityRanking": {
                "rankedCategories": [
                    {
                        "categoryName": "类别名称",
                        "contentAttraction": "high、medium 或 low",
                        "trustDifficulty": "high、medium 或 low",
                        "paymentLikelihood": "high、medium 或 low",
                        "repurchaseLikelihood": "high、medium 或 low",
                        "reason": "排序理由",
                    }
                ],
                "priorityCategory": "最值得优先服务的类别名称",
                "priorityReason": "优先服务原因",
            },
            "positioningReminder": {
                "commonMisjudgment": "最容易出现的一项用户判断误区",
                "hypothesisToValidate": "仍需验证的一项假设",
            },
        },
        TARGET_AUDIENCE_GUIDANCE,
    ),
    ReportSectionSpec(
        "hotContents",
        HotContentsResult,
        [
            {
                "platform": "平台",
                "contentId": "证据中的内容ID",
                "title": "标题",
                "selectionReason": "入选原因",
                "publicUrl": "公开链接或空字符串",
                "contentType": "image、video 或 unknown",
                "metrics": {},
            }
        ],
        (
            "只能从 industryEvidence.hotContents 候选中选择，不得用当前账号作品填充。"
            "候选不足 8 条时全部返回；候选达到 8 条时必须返回 8 条。"
            "尽量保持 4 条 video 和 4 条 image；某类不足时再由其他类型补齐。"
        ),
    ),
    ReportSectionSpec(
        "topBloggers",
        TopBloggersResult,
        [
            {
                "platform": "平台",
                "creatorHash": "证据中的创作者哈希",
                "name": "博主名",
                "contentTraits": ["内容特征"],
                "metrics": {},
            }
        ],
        "只能从 industryEvidence.topBloggers 候选中选择，不得使用当前账号或编造博主。",
    ),
    ReportSectionSpec(
        "contentStrategy",
        ContentStrategyResult,
        {
            "contentPillars": ["内容支柱"],
            "tone": ["语气要求"],
            "opportunities": ["内容机会"],
            "avoidDirections": ["规避方向"],
        },
        (
            "结合账号定位、知识库、目标用户和公开行业证据给出可执行策略，数组字段不得返回字符串。"
            "contentPillars、tone、opportunities、avoidDirections 应尽量各返回至少 1 项；"
            "公开证据不足时，优先依据账号行业、产品或服务、账号定位与内容目标归纳，"
            "只有输入中连这些基础信息也无法支持判断时才返回空数组。"
        ),
    ),
)

REGENERATABLE_REPORT_SECTION_KEYS = frozenset(
    {
        "similarAccounts",
        "complianceRules",
        "targetUserProfile",
        "hotContents",
    }
)


def get_report_section_spec(section_key: str) -> ReportSectionSpec:
    """返回允许用户单独重新生成的报告板块契约。"""

    if section_key not in REGENERATABLE_REPORT_SECTION_KEYS:
        raise ValueError(f"不支持单独生成账号报告板块：{section_key}")
    return next(spec for spec in REPORT_SECTION_SPECS if spec.key == section_key)


def build_report_section_prompt(
    spec: ReportSectionSpec,
    account_context: dict[str, Any],
    evidence: ReportEvidence,
    source_meta: dict[str, Any],
) -> str:
    ai_evidence = build_ai_evidence(evidence)
    if spec.key == "hotContents":
        selected = select_balanced_hot_contents(evidence.industry.hot_contents)
        selected_keys = {(item.platform, item.content_id) for item in selected}
        ai_evidence["industryEvidence"]["hotContents"] = [
            item
            for item in ai_evidence["industryEvidence"]["hotContents"]
            if (item["platform"], item["content_id"]) in selected_keys
        ]
    payload = {
        "accountContext": account_context,
        "evidence": ai_evidence,
        "sourceMeta": source_meta,
    }
    contract = {spec.key: spec.contract}
    return f"""你是中文社交媒体账号策略与合规分析师。本次只生成账号报告的 {spec.key} 分块。
必须仅依据输入中的账号资料和精选公开证据；不得补造账号、内容、互动指标或链接。
优先使用 accountContext 中的账号行业、定位、产品或服务、知识库和内容目标进行合理归纳，不要因为公开样本不足就直接返回空数组；只有当前分块确实没有足够依据时才返回空数组。
评论证据只能用于聚合趋势，不得逐字引用或输出评论者身份、联系方式。
专项要求：{spec.instruction}
只返回合法 JSON，不要返回 markdown 或说明。顶层必须且只能包含 {spec.key}，固定结构如下：
{json.dumps(contract, ensure_ascii=False, separators=(",", ":"))}
输入：{json.dumps(payload, ensure_ascii=False, default=str)}"""


def build_report_section_retry_prompt(prompt: str, spec: ReportSectionSpec) -> str:
    """在保留原始证据与契约的前提下，要求模型重新生成失败分块。"""

    target_profile_correction = ""
    if spec.key == "targetUserProfile":
        target_profile_correction = """
目标用户画像不得再使用旧版 summary、coreNeeds、contentPreferences、purchaseConcerns、conversionTriggers 字段。
targetUserProfile 必须且只能使用 assumption、categories、priorityRanking、positioningReminder；
categories 必须包含 3–5 类按生活处境、使用场景、核心动机和付费原因划分的用户。"""
    return f"""{prompt}

上一次 {spec.key} 响应无法通过标准 JSON 解析或结构校验。
请从头重新生成该分块，不要复述或修补上一次响应。
再次确认：第一个字符必须是 {{，最后一个字符必须是 }}；
所有属性名和字符串都使用英文双引号，字符串内的双引号必须转义；
不要输出 markdown、注释、尾随逗号或 JSON 对象之外的任何文字。{target_profile_correction}"""


def parse_report_section(raw: str, spec: ReportSectionSpec) -> Any:
    text = str(raw or "").strip()
    match = _FENCED_JSON.fullmatch(text)
    if match:
        text = match.group(1).strip()
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"账号报告分块 {spec.key} 不是合法的完整 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"账号报告分块 {spec.key} 顶层必须是 JSON 对象")
    normalized = normalize_account_report_response(value)
    result = spec.result_model.model_validate(normalized)
    field_name = next(iter(spec.result_model.model_fields))
    return getattr(result, field_name)
