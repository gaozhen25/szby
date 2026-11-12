from app.services.workflow.workflows.video_filetrans_results import (
    normalize_filetrans_timeline,
    normalize_flash_fallback_timeline,
)


def test_filetrans_timeline_offsets_sentences_words_and_emotion():
    payload = {
        "transcripts": [{
            "text": "第一句第二句",
            "sentences": [
                {
                    "begin_time": 100,
                    "end_time": 1200,
                    "text": "第一句",
                    "emotion": "happy",
                    "language": "zh",
                    "words": [{
                        "begin_time": 100,
                        "end_time": 500,
                        "text": "第一",
                        "punctuation": "",
                    }],
                },
                {
                    "begin_time": 1500,
                    "end_time": 2600,
                    "text": "第二句",
                    "emotion": "sad",
                    "language": "zh",
                    "words": [],
                },
            ],
        }],
    }

    timeline = normalize_filetrans_timeline(
        payload,
        chunk_start_seconds=60,
        chunk_duration_seconds=30,
    )

    assert timeline[0]["timeRange"] == "01:00.100-01:01.200"
    assert timeline[0]["beginMs"] == 60100
    assert timeline[0]["emotion"] == "happy"
    assert timeline[0]["emotionLabel"] == "愉快"
    assert timeline[0]["words"][0] == {
        "beginMs": 60100,
        "endMs": 60500,
        "text": "第一",
        "punctuation": "",
    }
    assert timeline[1]["timeRange"] == "01:01.500-01:02.600"
    assert timeline[1]["emotionLabel"] == "悲伤"


def test_flash_fallback_timeline_splits_sentences_and_estimates_absolute_ranges():
    timeline = normalize_flash_fallback_timeline(
        "第一句。第二句！",
        chunk_start_seconds=60,
        chunk_duration_seconds=30,
    )

    assert [item["text"] for item in timeline] == ["第一句。", "第二句！"]
    assert timeline[0]["beginMs"] == 60000
    assert timeline[0]["endMs"] == 75000
    assert timeline[1]["beginMs"] == 75000
    assert timeline[1]["endMs"] == 90000
    assert all(item["emotion"] == "neutral" for item in timeline)
