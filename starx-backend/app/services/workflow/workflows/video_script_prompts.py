"""Prompt builders distilled from the approved short-video manuals."""

from __future__ import annotations

import json
from typing import Any

from .video_script_contract import (
    ALLOWED_CONTENT_GOALS,
    ALLOWED_TONE_STYLES,
    ALLOWED_VIDEO_FORMATS,
    MIN_SHOT_COUNTS,
    VIDEO_SCRIPT_MANUAL_VERSION,
    VIDEO_SCRIPT_SCHEMA_VERSION,
)


# Source file: docs/短视频手册/IP定位与内容支点落地手册.docx
# Sections: 四「内容支点画布」、六「影像资源」、九「理想用户」、十五「AI应该怎么用」。
IP_POSITIONING_RULES = """《IP定位与内容支点落地手册》规则：
1. 每条视频只有一个唯一核心目的，不同时追求多个结果。
2. 面向一个具体种子用户，写清其真实处境、语言习惯和当下阻力。
3. 只使用账号资料和知识库中已经给出的真实资源、能力与产品信息。"""


# Source file: docs/短视频手册/短视频选题结构与标签化创作落地手册.docx
# Sections: 二「选题」、三「清单式原子结构」、四「标签化思维」、十「AI 使用边界」。
TOPIC_STRUCTURE_RULES = """《短视频选题结构与标签化创作落地手册》规则：
1. 选题必须形成“需求—解决方案”的单线闭环，先指出需求，再给出可执行解决方案。
2. 正文采用清单式原子结构，每一项只承载一个信息点，并能被单独理解。
3. 前 3-5 秒给出与用户需求直接相关的钩子，避免空泛铺垫。"""


# Source file: docs/短视频手册/短视频内容分类与客户新账号落地手册.docx
# Sections: 总原则、一「内容分类」、八「新账号落地 SOP」、十「AI 协作」。
CONTENT_GOAL_RULES = """《短视频内容分类与客户新账号落地手册》规则：
1. 根据账号阶段选择曝光、获客、转化或人设中的一个内容目的。
2. 结尾设置与唯一核心目的对应的行动入口；入口必须具体、自然且可执行。
3. 内容形式服务于目标和素材条件，不能为了形式虚构案例或证明。"""


_NO_FABRICATION_RULES = """真实性红线：
- 不得编造个人经历、客户案例、用户评价、测试数据、资质、价格、效果保证或产品事实。
- 未出现在账号资料、知识库或选题信息中的事实一律不要补全；信息不足时使用不依赖该事实的表达。
- 不得把推测写成事实，也不得生成绝对化承诺。"""


def build_video_script_system_prompt() -> str:
    return (
        "你是严格遵循业务手册的短视频脚本策划助手。"
        "只使用用户提供的账号、知识库、选题和偏好信息。"
        "只输出一个 JSON 对象，不输出 markdown、代码块、解释或前后缀文本。"
        "不得编造任何经历、案例、评价、数据、资质、价格、保证或产品事实。"
    )


def build_video_script_user_prompt(context: dict[str, Any], preferences: dict[str, Any]) -> str:
    account = context.get("account") or {}
    knowledge = context.get("knowledgeContext") or ""
    topic = context.get("topic") or {}
    duration_seconds = int(preferences.get("durationSeconds") or 30)
    minimum_shots = MIN_SHOT_COUNTS[duration_seconds]
    boundaries = [0, 5] + [
        round(5 + (duration_seconds - 5) * index / (minimum_shots - 1))
        for index in range(1, minimum_shots)
    ]
    final_script_shape = []
    for index in range(minimum_shots):
        start_seconds = boundaries[index]
        end_seconds = boundaries[index + 1]
        time_range = (
            f"{start_seconds // 60:02d}:{start_seconds % 60:02d}-"
            f"{end_seconds // 60:02d}:{end_seconds % 60:02d}"
        )
        final_script_shape.append(
            {
                "shotNumber": index + 1,
                "timeRange": time_range,
                "text": "本镜逐字口播",
                "narration": "本镜逐字口播",
                "soundNarration": "本镜旁白、对白、环境声、音效与音乐变化",
                "purpose": "本镜在完整脚本中的唯一作用",
                "visual": "本镜画面主体、动作、环境与关键道具",
                "shotSizeCamera": "本镜景别与机位",
                "shootingTechnique": "本镜拍摄技巧、运镜或剪辑方式",
                "subtitle": "本镜屏幕字幕",
                "bgmSound": "本镜 BGM、音效或声音变化",
            }
        )
    output_shape: dict[str, Any] = {
        "title": "脚本标题",
        "contentGoal": "exposure | acquisition | conversion | persona，不得输出 auto",
        "contentGoalReason": "选择该唯一核心目的的理由",
        "targetAudience": "具体种子用户",
        "coreNeed": "该用户的一个核心需求",
        "coreSolution": "针对需求的一个核心解决方案",
        "draftScript": ["初稿段落 1", "初稿段落 2"],
        "finalScript": final_script_shape,
        "publishCopy": "发布文案",
        "hashtags": ["#标签1", "#标签2"],
        "bgmSuggestion": "背景音乐建议",
        "hookSuggestion": "前 3-5 秒可直接使用的钩子文案，必须具体、有信息量",
        "rhythmNote": "节奏建议，可为空字符串",
        "callToAction": "与内容目的对应的行动入口",
    }
    input_payload = {
        "account": account,
        "knowledgeContext": knowledge,
        "topic": topic,
        "preferences": preferences,
    }
    constraints = {
        "schemaVersion": VIDEO_SCRIPT_SCHEMA_VERSION,
        "manualVersion": VIDEO_SCRIPT_MANUAL_VERSION,
        "contentGoalValues": sorted(ALLOWED_CONTENT_GOALS - {"auto"}),
        "videoFormatValues": sorted(ALLOWED_VIDEO_FORMATS),
        "toneStyleValues": sorted(ALLOWED_TONE_STYLES),
    }
    return "\n\n".join(
        [
            "请依据输入资料和以下三份手册规则生成短视频脚本。",
            IP_POSITIONING_RULES,
            TOPIC_STRUCTURE_RULES,
            CONTENT_GOAL_RULES,
            _NO_FABRICATION_RULES,
            "输入资料：\n" + json.dumps(input_payload, ensure_ascii=False, indent=2),
            "契约约束：\n" + json.dumps(constraints, ensure_ascii=False, indent=2),
            (
                "输出要求：\n"
                "- 只输出下面形状的 JSON 对象；不要输出 schemaVersion、manualVersion 或 appliedPrinciples，后端会统一添加。\n"
                "- finalScript 的 timeRange 使用 MM:SS-MM:SS，第一段从 00:00 开始，各段首尾连续且完整覆盖 preferences.durationSeconds。\n"
                f"- {duration_seconds} 秒视频至少拆分为 {minimum_shots} 个镜头；除结尾行动引导外，单镜建议 3-8 秒，禁止用一个长镜头承载多个观点或跨越大部分视频时长。\n"
                "- 每个镜头只表达一个动作或信息点；同一段口播若包含多个观点，必须继续拆镜，并为每镜设计有变化的主体、构图、机位或运动。\n"
                "- finalScript 每段都必须包含 shotNumber、timeRange、shotSizeCamera、visual、soundNarration，以及 text、narration、purpose、shootingTechnique、subtitle、bgmSound；镜号从 1 连续递增，时间、画面、机位与声音必须逐镜逐段对齐。\n"
                "- hookSuggestion 必须输出一条可直接使用的 3-5 秒开场钩子，并与 finalScript 第一镜的旁白和画面相互呼应，不得为空。\n"
                "- draftScript 和 finalScript 均不得为空；所有必填文本必须有内容。\n"
                "JSON 形状：\n"
                + json.dumps(output_shape, ensure_ascii=False, indent=2)
            ),
        ]
    )
