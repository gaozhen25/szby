"""账号报告分块 AI 调用契约。

每个分块独立生成、独立校验，避免要求模型一次返回完整报告。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..domain.models import (
    ComplianceRule,
    HotContent,
    ReportEvidence,
    SimilarAccount,
    TargetUserProfile,
)
from ..evidence.ai_projection import build_ai_evidence
from ..evidence.hot_contents import select_balanced_hot_contents
from .normalizer import normalize_account_report_response
from .prompts.compliance import COMPLIANCE_RULES_GUIDANCE
from .prompts.target_audience import TARGET_AUDIENCE_GUIDANCE

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
        (
            "只能从 industryEvidence.similarAccounts 候选中选择，不得使用当前账号或编造账号。"
            "全行业一律要求高度垂直：相似账号须与账号/对标属于同一细分产品、服务或内容品类。"
            "蹭边一律排除：同大类不同细分、相邻赛道、泛干货/泛获客/泛营销号。"
            "不要只因为同属大行业、目标客户相似、获客目标相似、内容风格相似或粉丝量高就入选。"
            "例如 GEO/AI 搜索优化不要选大学生求职、简历模板、普通职场、泛创业类博主；"
            "游戏陪玩不要选游戏攻略；留学申请不要选高考志愿填报。"
            "每条必须同时输出 similarityReason 与 1–3 条 representativeContents。"
            "similarityReason 写法必须接近："
            "「同属XX赛道，内容核心是YY，与「账号定位」高度一致」；"
            "要点出赛道、内容核心、与 accountContext 定位的一致性；"
            "禁止空话「风格相似」「可参考运营节奏」；条与条不得套同一句模板；"
            "严禁出现「关键词」「检索词」「搜索词」。"
            "representativeContents 必须优先原样使用候选 representative_contents 里的作品标题"
            "（可含话题标签），禁止编造，尽量保留完整标题信息。"
        ),
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
                    "specificProfile": "150–250 字完整画像",
                    "purchaseMotivation": "一句话购买动机",
                }
            ],
            "priorityRanking": {
                "rankedCategories": [
                    {
                        "categoryName": "类别名称",
                        "priority": 1,
                        "contentAttraction": "高、较高、中等、较低或低",
                        "trustDifficulty": "高、较高、中等、较低或低",
                        "paymentLikelihood": "高、较高、中等、较低或低",
                        "repurchaseLikelihood": "高、较高、中等、较低或低",
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
                "coverUrl": "封面链接或空字符串",
                "contentType": "image、video 或 unknown",
                "tags": [],
                "metrics": {},
            }
        ],
        (
            "只能从 industryEvidence.hotContents 候选中选择，不得用当前账号作品填充。"
            "推荐爆款必须与账号行业、产品或服务强关联；内部可看 title/summary，"
            "但 selectionReason 严禁出现「关键词」「检索词」「搜索词」或复述检索词。"
            "不要只因为目标客户相似、痛点相似、获客目标相似或内容结构相似就选择。"
            "例如 GEO/AI 搜索优化行业，不要选择大学生求职通用模板、简历模板、普通职场经验、泛创业、泛获客、泛营销类笔记。"
            "咨询/服务/机构类账号：只选与产品服务动作强相关的内容（咨询、方案、避坑、怎么选、测评、申请规划等）；"
            "禁止选纯生活日常、无关 vlog、逛街旅拍、宿舍探店等与交付服务无关的内容。"
            "每条 selectionReason 必须接近："
            "「标题与摘要明确围绕XX，与「账号定位」高度一致」"
            "或「标题指向XX，与账号定位强相关且热度积累高」；"
            "要结合该条真实标题/摘要主题和 accountContext 定位来写，条与条必须有区分；"
            "禁止千篇一律套话（如整句复用「点赞较高适合参考选题切口」）。"
            "抖音与小红书双平台时各约占一半（各自按点赞从高到低）；单平台则按点赞凑满 8 条；候选足 8 必须返回 8。"
            "tags 固定返回空数组。"
            "换一批避开上一批 contentId；也避开选题中心已绑定原文。"
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
    *,
    exclude_hot_keys: set[tuple[str, str]] | frozenset[tuple[str, str]] | None = None,
) -> str:
    ai_evidence = build_ai_evidence(evidence)
    prompt_source_meta = dict(source_meta or {})
    # 候选池仅供系统换批，不暴露给模型，避免又选回上一批高赞内容
    prompt_source_meta.pop("hotContentsCandidatePool", None)
    if spec.key == "hotContents":
        account = dict(account_context.get("account") or {})
        platforms = [
            str(item).strip()
            for item in (account.get("platforms") or [account.get("platform")])
            if str(item or "").strip()
        ]
        selected = select_balanced_hot_contents(
            evidence.industry.hot_contents,
            platforms=platforms,
            exclude_keys=exclude_hot_keys,
            account_context=account_context,
        )
        selected_keys = {(item.platform, item.content_id) for item in selected}
        ai_evidence["industryEvidence"]["hotContents"] = [
            item
            for item in ai_evidence["industryEvidence"]["hotContents"]
            if (item["platform"], item["content_id"]) in selected_keys
        ]
    payload = {
        "accountContext": account_context,
        "evidence": ai_evidence,
        "sourceMeta": prompt_source_meta,
    }
    contract = {spec.key: spec.contract}
    return f"""你是中文社交媒体账号策略与合规分析师。本次只生成账号报告的 {spec.key} 分块。
必须仅依据输入中的账号资料和精选公开证据；不得补造账号、内容、互动指标或链接。
优先使用 accountContext 中的账号行业、定位、产品或服务、知识库和内容目标进行合理归纳；similarAccounts 和 hotContents 必须先判断细分赛道高度垂直，再考虑热度、粉丝量和泛相似度；蹭边相关不算相似。不要因为公开样本不足就直接返回空数组；只有当前分块确实没有足够依据时才返回空数组。
评论证据只能用于聚合趋势，不得逐字引用或输出评论者身份、联系方式。
专项要求：{spec.instruction}
只返回合法 JSON，不要返回 markdown 或说明。顶层必须且只能包含 {spec.key}，固定结构如下：
{json.dumps(contract, ensure_ascii=False, separators=(",", ":"))}
输入：{json.dumps(payload, ensure_ascii=False, default=str)}"""


def build_target_user_profile_prompt(
    spec: ReportSectionSpec,
    account_context: dict[str, Any],
) -> str:
    """仅使用账号档案与知识库生成目标用户画像。

    该分块不依赖公开作品、行业搜索结果或评论证据，避免将内容样本
    的偶然偏差误当成账号的核心客群定义。
    """

    if spec.key != "targetUserProfile":
        raise ValueError("纯上下文提示词仅支持目标用户画像")
    contract = {spec.key: spec.contract}
    payload = {"accountContext": account_context}
    return f"""你是中文社交媒体账号定位与用户策略顾问。本次只生成账号报告的 targetUserProfile 分块。
只能使用 accountContext 中的账号档案与已启用知识库信息；不要假设已查询过作品、行业样本或评论。
信息不足时，可依据账号所属行业与产品服务做谨慎假设，并明确写入 assumption。
专项要求：{spec.instruction}
只返回合法 JSON，不要返回 markdown 或说明。顶层必须且只能包含 targetUserProfile，固定结构如下：
{json.dumps(contract, ensure_ascii=False, separators=(",", ":"))}
输入：{json.dumps(payload, ensure_ascii=False, default=str)}"""


def build_report_section_retry_prompt(prompt: str, spec: ReportSectionSpec) -> str:
    """在保留原始证据与契约的前提下，要求模型重新生成失败分块。"""

    target_profile_correction = ""
    if spec.key == "targetUserProfile":
        target_profile_correction = """
目标用户画像不得再使用旧版 summary、coreNeeds、contentPreferences、purchaseConcerns、conversionTriggers 字段。
targetUserProfile 必须且只能使用 assumption、categories、priorityRanking、positioningReminder；
categories 必须包含 3–5 类按购买场景、需求状态或决策逻辑划分的用户；
每个 category 必须只输出 categoryName、specificProfile、purchaseMotivation。"""
    return f"""{prompt}

上一次 {spec.key} 响应无法通过标准 JSON 解析或结构校验。
请从头重新生成该分块，不要复述或修补上一次响应。
再次确认：第一个字符必须是 {{，最后一个字符必须是 }}；
所有属性名和字符串都使用英文双引号，字符串内的双引号必须转义；
不要输出 markdown、注释、尾随逗号或 JSON 对象之外的任何文字。{target_profile_correction}"""


def _close_truncated_json(text: str) -> str:
    """补全模型截断时缺失的引号与括号，尽量挽救近完整 JSON。"""

    in_string = False
    escape = False
    stack: list[str] = []
    for char in text:
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            stack.append("}")
        elif char == "[":
            stack.append("]")
        elif char in "}]" and stack and stack[-1] == char:
            stack.pop()

    repaired = text
    if in_string:
        repaired += '"'
    repaired = re.sub(r",\s*$", "", repaired)
    if stack:
        repaired += "".join(reversed(stack))
    return repaired


def _loads_report_section_json(raw: str) -> Any:
    """解析分块 JSON：支持 fence、前后杂质，以及少闭合括号的截断输出。"""

    text = str(raw or "").lstrip("\ufeff").strip()
    if not text:
        raise ValueError("empty json")
    match = _FENCED_JSON.fullmatch(text)
    if match:
        text = match.group(1).strip()

    brace_at = text.find("{")
    roots = [text]
    if brace_at > 0:
        roots.append(text[brace_at:])
    elif brace_at == 0:
        roots = [text]

    candidates: list[str] = []
    for root in roots:
        if root not in candidates:
            candidates.append(root)
        closed = _close_truncated_json(root)
        if closed not in candidates:
            candidates.append(closed)

    last_error: Exception | None = None
    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, TypeError) as exc:
            last_error = exc
        # 只从第一个 { 解码，且后续只能是空白，避免误取内层对象
        start = candidate.find("{")
        if start < 0:
            continue
        try:
            value, end = decoder.raw_decode(candidate[start:])
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if str(candidate[start + end :]).strip():
            continue
        return value

    if last_error is not None:
        raise last_error
    raise ValueError("empty json")


def parse_report_section(raw: str, spec: ReportSectionSpec) -> Any:
    try:
        value = _loads_report_section_json(raw)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(f"账号报告分块 {spec.key} 不是合法的完整 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"账号报告分块 {spec.key} 顶层必须是 JSON 对象")
    normalized = normalize_account_report_response(value)
    result = spec.result_model.model_validate(normalized)
    field_name = next(iter(spec.result_model.model_fields))
    return getattr(result, field_name)
