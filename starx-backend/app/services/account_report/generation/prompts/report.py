"""账号报告关键词规划、完整报告提示词和严格 JSON 解析。"""

from __future__ import annotations

import json
import re
from typing import Any

from ...domain.models import AccountReportPayload, ReportEvidence
from ...evidence.ai_projection import build_ai_evidence
from ..normalizer import normalize_account_report_response
from .compliance import COMPLIANCE_RULES_GUIDANCE
from .target_audience import TARGET_AUDIENCE_GUIDANCE

_FENCED_JSON = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL | re.IGNORECASE)
_REPORT_OUTPUT_CONTRACT = {
    "similarAccounts": [
        {
            "platform": "平台",
            "creatorHash": "证据中的创作者哈希",
            "name": "账号名",
            "similarityReason": "相似原因",
            "metrics": {},
            "representativeContents": ["代表内容"],
        }
    ],
    "complianceRules": [
        {
            "riskLevel": "high",
            "expression": "原表达",
            "reason": "风险原因",
            "suggestion": "替代表达",
            "platforms": ["平台"],
        }
    ],
    "targetUserProfile": {
        "assumption": "信息不足时的一句话假设；无额外假设则为空字符串",
        "categories": [
            {
                "categoryName": "类别名称",
                "specificProfile": "150–250 字完整画像",
                "purchaseMotivation": "一句话购买动机",
            }
        ],
        "priorityRanking": {
            "rankedCategories": [{
                "categoryName": "类别名称",
                "priority": 1,
                "contentAttraction": "高",
                "trustDifficulty": "中等",
                "paymentLikelihood": "较高",
                "repurchaseLikelihood": "较高",
                "reason": "排序理由",
            }],
            "priorityCategory": "最值得优先服务的类别名称",
            "priorityReason": "优先服务原因",
        },
        "positioningReminder": {
            "commonMisjudgment": "用户判断误区",
            "hypothesisToValidate": "待验证假设",
        },
    },
    "hotContents": [
        {
            "platform": "平台",
            "contentId": "证据中的内容ID",
            "title": "标题",
            "selectionReason": "入选原因",
            "publicUrl": "公开链接或空字符串",
            "coverUrl": "封面链接或空字符串",
            "contentType": "image、video 或 unknown",
            "metrics": {},
        }
    ],
    "sourceMeta": {
        "platforms": ["平台"],
        "keywords": ["关键词1", "关键词2", "关键词3"],
        "sampleCount": 0,
        "failedPlatforms": [],
        "unsupportedPlatforms": [],
    },
}


def build_keyword_planning_prompt(
    account_context: dict[str, Any],
    *,
    benchmark_seed: dict[str, Any] | None = None,
) -> str:
    keyword_context = dict(account_context)
    keyword_account = dict(keyword_context.get("account") or {})
    keyword_account.pop("name", None)
    keyword_context["account"] = keyword_account
    seed = dict(benchmark_seed or {}) or dict(keyword_context.get("benchmarkSeed") or {})
    if seed:
        keyword_context["benchmarkSeed"] = seed
    context_json = json.dumps(keyword_context, ensure_ascii=False, default=str)
    seed_hint = ""
    if seed:
        seed_hint = (
            "若提供了 benchmarkSeed（对标账号公开资料），检索词应贴近其对标赛道与内容方向，"
            "但仍不得使用对标昵称、品牌名作为检索词。"
        )
    return f"""你是中文社交媒体行业研究员。请根据账号档案和知识库，规划所有平台共用的 3–5 个检索短词。
每个词不超过 12 个字符，彼此不重复，必须具体、可解释且与账号行业强相关。
每个词单独用于平台搜索时，都应优先召回该行业的参考内容；不要生成只表达目标人群、目标地域、营销结果或泛业务诉求的宽泛词。
只依据行业、产品或服务、目标地域、目标人群和内容定位生成行业专属检索词。
不得参考、改写、拆分或组合账号名称、品牌名、IP 名称来生成检索词；不要生成账号专属词或疑似账号昵称的词。
{seed_hint}
示例：若行业为 GEO、AI 搜索优化或相关服务，可优先考虑“GEO优化”“AI搜索优化”“ChatGPT SEO”“AI流量”“AI获客”等行业检索词；不要生成“地理”相关的关键词，也不要生成“企业获客”“精准获客”“营销增长”等相关性较弱、容易召回非 GEO 内容的泛获客词。
只返回 JSON：{{"keywords":["词1","词2","词3"]}}，不要返回 markdown 或说明。
账号上下文：{context_json}"""


def build_account_report_prompt(
    account_context: dict[str, Any],
    evidence: ReportEvidence,
    source_meta: dict[str, Any],
) -> str:
    payload = {
        "accountContext": account_context,
        "evidence": build_ai_evidence(evidence),
        "sourceMeta": source_meta,
    }
    return f"""你是中文社交媒体账号策略与合规分析师。必须仅依据下方账号资料和精选公开证据生成一次性完整报告。
不得补造账号、互动指标或链接；样本不足时应明确说明。
complianceRules 专项要求：
{COMPLIANCE_RULES_GUIDANCE}
targetUserProfile 专项要求：
{TARGET_AUDIENCE_GUIDANCE}
currentAccountEvidence 只用于分析当前账号现状、已有内容特征、受众反馈和改进机会。
industryEvidence 用于生成行业热门内容、相似账号和对标结论；不得用当前账号作品填充行业热门内容或相似账号。
评论证据仅用于聚合趋势、需求与顾虑推断；不得逐字引用或复述单条评论，不得输出评论者身份、联系方式，也不得在报告结构或 sourceMeta 中新增评论字段。
只返回合法 JSON，不要返回 markdown。JSON 必须完整包含以下五个顶层块：
similarAccounts（最多20项）、complianceRules（1–20项）、targetUserProfile、hotContents（最多20项）、sourceMeta。
targetUserProfile 必须包含 assumption、categories、priorityRanking、positioningReminder。
以下是固定 JSON 结构示例，键名和数组类型不得改变，示例值必须替换为基于证据的内容：
{json.dumps(_REPORT_OUTPUT_CONTRACT, ensure_ascii=False, separators=(",", ":"))}
riskLevel 只能使用 high、medium、low。
输入：{json.dumps(payload, ensure_ascii=False, default=str)}"""


def parse_account_report(raw: str) -> AccountReportPayload:
    """仅允许裸 JSON 或完整 markdown JSON fence，不从自然语言中猜取 JSON。"""

    text = str(raw or "").strip()
    match = _FENCED_JSON.fullmatch(text)
    if match:
        text = match.group(1).strip()
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("账号报告不是合法的完整 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("账号报告顶层必须是 JSON 对象")
    return AccountReportPayload.model_validate(normalize_account_report_response(value))
