from app.services.prompt_builder import build_image_analysis_prompt, build_reverse_image_prompt


def test_image_analysis_prompt_is_bounded_for_fast_vision_response():
    prompt = build_image_analysis_prompt(
        target_platform="小红书",
        topic_title="搞笑漫画",
        copy_text="低成本养狗",
    )

    assert "600字以内" in prompt
    assert "只输出纯文本" in prompt
    assert "构图" in prompt
    assert "主体" in prompt
    assert "尽可能详尽" not in prompt


def test_reverse_image_prompt_requires_all_content_in_chinese():
    prompt = build_reverse_image_prompt(
        target_platform="小红书",
        title="随机一日三餐",
        description="看看今天会吃到什么",
    )

    assert "正面提示词、负面提示词、发布文案和风格标签必须全部使用中文" in prompt
    assert "不得使用英文提示词或英文标签" in prompt
    assert "目标平台：小红书" in prompt
    assert "标题：随机一日三餐" in prompt
    assert "正文：看看今天会吃到什么" in prompt
