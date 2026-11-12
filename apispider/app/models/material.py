from dataclasses import dataclass, field


@dataclass
class Material:
    id: str
    name: str
    type: str
    tags: list[str]
    date: str
    thumb: str
    assets: list[dict[str, object]] = field(default_factory=list)
