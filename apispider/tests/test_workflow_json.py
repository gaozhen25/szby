from app.services.workflow.workflows.base import normalize_json


def test_normalize_json_accepts_fence_without_newlines():
    assert normalize_json('```JSON {"ok": true} ```') == {"ok": True}


def test_normalize_json_extracts_object_after_non_json_brackets_and_braces():
    raw = '分析步骤 [1]：先检查 {not-json}。最终结果：{"ok": true}\n完成。'

    assert normalize_json(raw) == {"ok": True}


def test_normalize_json_prefers_largest_valid_object():
    raw = '格式示例：{}。最终结果：{"videoScript": [{"text": "正文"}]}'

    assert normalize_json(raw) == {"videoScript": [{"text": "正文"}]}


def test_normalize_json_rejects_truncated_object():
    assert normalize_json('{"items": [1, 2') is None
