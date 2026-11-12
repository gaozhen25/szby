import json

import pytest

from app.services.workflow.workflows.image_prompt_plan import (
    ALLOWED_COLLECTION_MODES,
    ALLOWED_CREATIVITY_LEVELS,
    ALLOWED_IMAGE_COUNTS,
    ALLOWED_RATIOS,
    ALLOWED_VISUAL_STYLES,
    IMAGE_PROMPT_PLAN_SCHEMA_VERSION,
    SERIES_ROLES,
    build_image_prompt_plan_user,
    normalize_image_prompt_plan,
)


CONTEXT = {
    "topic": {
        "title": "为什么努力工作却总得不到晋升",
        "description": "用清单帮助职场人找到晋升受阻原因",
    },
    "account": {
        "name": "星耀职场",
        "industry": "职业教育",
        "purpose": "获取精准咨询",
        "targetAudience": "工作三年仍没有晋升方向的职场人",
        "productService": "职业规划咨询",
    },
    "knowledge": {
        "enabledFields": [
            {"name": "服务范围", "content": "提供一对一职业规划咨询。"},
            {"name": "禁用内容", "content": "不得承诺百分百晋升。"},
        ],
        "disabledFields": [
            {"name": "内部价格", "content": "不要把这一项放进提示词。"},
        ],
    },
}

SERIES_PREFS = {
    "targetPlatform": "小红书",
    "imageCount": 4,
    "collectionMode": "series",
    "ratio": "3:4",
    "creativityLevel": "medium",
    "visualStyle": "lifestyle_editorial",
    "customRequirements": "画面内不要出现夸张收益承诺",
}
INDEPENDENT_PREFS = {
    **SERIES_PREFS,
    "imageCount": 2,
    "collectionMode": "independent",
}

SERIES_RAW = {
    "imageCount": 99,
    "collectionMode": "independent",
    "ratio": "1:1",
    "sharedStyle": "低饱和蓝灰色，柔和侧光，留出标题安全区",
    "prompts": [
        {"title": "封面", "prompt": "封面：职场人在办公室思考，低饱和蓝灰色，柔和侧光，顶部留出标题安全区"},
        {"title": "内容页 1", "prompt": "内容一：目标清单特写，低饱和蓝灰色，柔和侧光，顶部留出标题安全区"},
        {"title": "内容页 2", "prompt": "内容二：反馈复盘场景，低饱和蓝灰色，柔和侧光，顶部留出标题安全区"},
        {"title": "收尾页", "prompt": "结尾：职场人明确下一步，低饱和蓝灰色，柔和侧光，顶部留出标题安全区"},
    ],
    "negativePrompt": "低质量、模糊、畸变",
    "publishCopy": "晋升受阻时，先用这三步检查。",
    "hashtags": ["#职场成长", "晋升", "#职场成长", ""],
}
INDEPENDENT_RAW = {
    "sharedStyle": "",
    "prompts": [
        {"title": "纪实场景", "prompt": "办公室纪实摄影，人物查看晋升计划"},
        {"title": "步骤信息图", "prompt": "极简信息图，用三步清单表现复盘方法"},
    ],
    "negativePrompt": "低质量、模糊",
    "publishCopy": "两种视觉方向，找到适合你的晋升复盘方式。",
    "hashtags": ["#职场成长", "#职业规划"],
}
TWO_PROMPTS_RAW = {**SERIES_RAW, "prompts": SERIES_RAW["prompts"][:2]}


def test_allowed_value_constants_are_exact():
    assert IMAGE_PROMPT_PLAN_SCHEMA_VERSION == 1
    assert ALLOWED_IMAGE_COUNTS == {1, 2, 3, 4}
    assert ALLOWED_COLLECTION_MODES == {"independent", "series"}
    assert ALLOWED_RATIOS == {"1:1", "3:4", "9:16", "4:3", "16:9"}
    assert ALLOWED_CREATIVITY_LEVELS == {"low", "medium", "high"}
    assert ALLOWED_VISUAL_STYLES == {
        "auto",
        "realistic_photography",
        "commercial_poster",
        "lifestyle_editorial",
        "illustration",
        "minimal_graphic",
    }
    assert SERIES_ROLES == {
        2: ["cover", "ending"],
        3: ["cover", "content", "ending"],
        4: ["cover", "content", "content", "ending"],
    }


def test_series_plan_requires_exact_count_and_shared_style():
    result = normalize_image_prompt_plan(SERIES_RAW, SERIES_PREFS)

    assert result["imageCount"] == 4
    assert result["collectionMode"] == "series"
    assert result["targetPlatform"] == "小红书"
    assert result["ratio"] == "3:4"
    assert result["creativityLevel"] == "medium"
    assert result["visualStyle"] == "lifestyle_editorial"
    assert result["sharedStyle"]
    assert [item["slotId"] for item in result["prompts"]] == [
        "topic_1",
        "topic_2",
        "topic_3",
        "topic_4",
    ]
    assert [item["role"] for item in result["prompts"]] == [
        "cover",
        "content",
        "content",
        "ending",
    ]
    assert [item["title"] for item in result["prompts"]] == [
        "封面",
        "内容页 1",
        "内容页 2",
        "收尾页",
    ]
    assert result["negativePrompt"] == "低质量、模糊、畸变"
    assert result["publishCopy"] == "晋升受阻时，先用这三步检查。"
    assert result["hashtags"] == ["#职场成长", "#晋升"]


def test_independent_plan_does_not_require_shared_style():
    result = normalize_image_prompt_plan(INDEPENDENT_RAW, INDEPENDENT_PREFS)

    assert result["collectionMode"] == "independent"
    assert result["sharedStyle"] == ""
    assert len(result["prompts"]) == 2
    assert [item["role"] for item in result["prompts"]] == ["standalone", "standalone"]


def test_plan_rejects_wrong_prompt_count():
    with pytest.raises(ValueError, match="exactly 4 prompts"):
        normalize_image_prompt_plan(TWO_PROMPTS_RAW, SERIES_PREFS)


@pytest.mark.parametrize("raw", ["not json", "[]", [{"prompts": []}]])
def test_plan_rejects_non_object_json(raw):
    with pytest.raises(ValueError, match="格式异常"):
        normalize_image_prompt_plan(raw, INDEPENDENT_PREFS)


def test_plan_accepts_fenced_json_and_rejects_empty_prompt_text():
    fenced = f"```json\n{json.dumps(INDEPENDENT_RAW, ensure_ascii=False)}\n```"
    assert normalize_image_prompt_plan(fenced, INDEPENDENT_PREFS)["prompts"][0]["prompt"]

    raw = {
        **INDEPENDENT_RAW,
        "prompts": [
            {"title": "纪实场景", "prompt": ""},
            INDEPENDENT_RAW["prompts"][1],
        ],
    }
    with pytest.raises(ValueError, match="prompt text"):
        normalize_image_prompt_plan(raw, INDEPENDENT_PREFS)


def test_plan_rejects_empty_card_title():
    raw = {
        **INDEPENDENT_RAW,
        "prompts": [
            {"title": " ", "prompt": "办公室纪实摄影"},
            INDEPENDENT_RAW["prompts"][1],
        ],
    }

    with pytest.raises(ValueError, match="title"):
        normalize_image_prompt_plan(raw, INDEPENDENT_PREFS)


def test_plan_coerces_invalid_optional_publish_fields_to_safe_types():
    raw = {
        **INDEPENDENT_RAW,
        "negativePrompt": ["模糊"],
        "publishCopy": {"text": "不能接收对象"},
        "hashtags": "#不是数组",
    }

    result = normalize_image_prompt_plan(raw, INDEPENDENT_PREFS)

    assert result["negativePrompt"] == ""
    assert result["publishCopy"] == ""
    assert result["hashtags"] == []


def test_series_plan_rejects_missing_shared_style():
    with pytest.raises(ValueError, match="shared style"):
        normalize_image_prompt_plan({**SERIES_RAW, "sharedStyle": ""}, SERIES_PREFS)


def test_series_plan_composes_shared_style_into_unrelated_prompts_once():
    shared_style = "同一位短发职场女性，奶油蓝配色，柔和侧光，居中构图，顶部文字安全区"
    raw = {
        **SERIES_RAW,
        "sharedStyle": shared_style,
        "prompts": [
            {"title": "封面", "prompt": "人物看向镜头"},
            {"title": "内容页 1", "prompt": f"{shared_style}；展示目标清单"},
            {"title": "内容页 2", "prompt": "展示反馈记录"},
            {"title": "收尾页", "prompt": "人物写下下一步行动"},
        ],
    }

    result = normalize_image_prompt_plan(raw, SERIES_PREFS)

    for item in result["prompts"]:
        assert shared_style in item["prompt"]
        assert item["prompt"].count(shared_style) == 1


def test_series_plan_cleans_model_wrappers_before_canonical_composition():
    shared_style = "同一人物、奶油色调、统一柔光、居中构图、顶部字体安全区"
    wrapped_prompt = (
        f"共享视觉约束：{shared_style}；"
        "本页画面要求：人物看镜头"
    )
    raw = {
        **SERIES_RAW,
        "sharedStyle": shared_style,
        "prompts": [
            {"title": "封面", "prompt": wrapped_prompt},
            {"title": "内容页 1", "prompt": "本页画面要求：展示目标清单"},
            {"title": "内容页 2", "prompt": "展示反馈记录"},
            {"title": "收尾页", "prompt": "人物写下下一步行动"},
        ],
    }

    result = normalize_image_prompt_plan(raw, SERIES_PREFS)
    normalized = result["prompts"][0]["prompt"]

    assert normalized == (
        f"共享视觉约束：{shared_style}\n"
        "本页画面要求：人物看镜头"
    )
    assert "共享视觉约束：；" not in normalized
    assert normalized.count("共享视觉约束：") == 1
    assert normalized.count("本页画面要求：") == 1


def test_prompt_builder_serializes_context_preferences_and_exact_shape():
    prompt = build_image_prompt_plan_user(CONTEXT, SERIES_PREFS)

    for expected in (
        "为什么努力工作却总得不到晋升",
        "星耀职场",
        "提供一对一职业规划咨询",
        "不得承诺百分百晋升",
        "小红书",
        '"imageCount": 4',
        '"ratio": "3:4"',
        '"creativityLevel": "medium"',
        '"visualStyle": "lifestyle_editorial"',
        "画面内不要出现夸张收益承诺",
        "只输出一个 JSON 对象",
        '"sharedStyle"',
        '"prompts"',
        '"slotId": "topic_1"',
        '"role": "cover"',
        '"title": "封面"',
        '"negativePrompt"',
        '"publishCopy"',
        '"hashtags"',
    ):
        assert expected in prompt
    assert "不要把这一项放进提示词" not in prompt


def test_series_prompt_requires_shared_visual_constraints_in_every_prompt():
    prompt = build_image_prompt_plan_user(CONTEXT, SERIES_PREFS)

    for expected in ("主体", "色彩", "光线", "构图", "文字安全区"):
        assert expected in prompt
    assert "每项 prompt 只写该页特有" in prompt
    assert "不得重复 sharedStyle" in prompt
    assert '"prompt": "仅描述该页特有的主体动作、场景和信息表达"' in prompt
    assert "共享约束必须明确重复写入每一条 prompt" not in prompt


def test_independent_prompt_requires_standalone_directions():
    prompt = build_image_prompt_plan_user(CONTEXT, INDEPENDENT_PREFS)

    assert "每张图都是可独立使用的创意方向" in prompt
    assert '"role": "standalone"' in prompt
