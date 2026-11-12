from app.services.prompt_tags import build_final_prompt, get_selected_prompt_tags, prompt_tag_categories


def test_build_final_prompt_appends_tags_in_category_order_with_quality_last():
    final_prompt = build_final_prompt(
        "未来城市街头的女孩",
        ["night_market", "photography", "8k"],
    )

    assert final_prompt == (
        "未来城市街头的女孩，超现实、高分辨率的照片，皮肤完美光滑，眼睛细节丰富，"
        "光线自然，专业影棚布光，电影级画质，超细节，4K，"
        "霓虹灯、小吃摊、人群、烟火气，夜晚的夜市街道，各种小吃摊位，五颜六色的霓虹灯牌，充满烟火气，"
        "8K ultra HD，extremely detailed，high resolution"
    )


def test_build_final_prompt_deduplicates_prompt_fragments_and_ignores_unknown_tags():
    final_prompt = build_final_prompt("高清细节，产品海报", ["8k", "missing-tag", "8k"])

    assert final_prompt == "高清细节，产品海报，8K ultra HD，extremely detailed，high resolution"


def test_get_selected_prompt_tags_returns_display_order():
    tags = get_selected_prompt_tags(["8k", "photography", "night_market"])

    assert [tag["id"] for tag in tags] == ["photography", "night_market", "8k"]
    assert prompt_tag_categories[-1]["id"] == "quality"
