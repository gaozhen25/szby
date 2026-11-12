from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class TrainingScript:
    version: str
    text: str
    min_duration_seconds: int
    max_duration_seconds: int
    recommended_duration_seconds: int
    instructions: tuple[str, ...]

    @property
    def digest(self) -> str:
        return sha256(self.text.encode("utf-8")).hexdigest()


DEFAULT_TRAINING_SCRIPT = TrainingScript(
    version="zh_cn_v1",
    text=(
        "你好，很高兴在这里和你见面。接下来，我会用清晰、自然的声音，"
        "为你分享实用的信息和有趣的故事。无论是工作、生活，还是新的想法，"
        "我都希望能够认真表达，让每一次交流更加简单、真实和有价值。"
        "现在，让我们一起开始今天的内容创作吧。"
    ),
    min_duration_seconds=10,
    max_duration_seconds=60,
    recommended_duration_seconds=35,
    instructions=(
        "建议竖屏 9:16，至少 720p",
        "单人正面出镜，脸部和嘴部无遮挡",
        "在安静环境中完整朗读固定文案",
        "不要剪辑、变速或添加背景音乐",
        "开头和结尾各保持约 1 秒静止",
    ),
)


def get_training_script(version: str) -> TrainingScript:
    if version != DEFAULT_TRAINING_SCRIPT.version:
        raise ValueError("不支持的训练文案版本")
    return DEFAULT_TRAINING_SCRIPT
