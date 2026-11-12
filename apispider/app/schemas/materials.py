from pydantic import BaseModel, Field


class MaterialSchema(BaseModel):
    id: str
    name: str
    type: str
    tags: list[str]
    date: str
    thumb: str
    assets: list[dict[str, object]] = Field(default_factory=list)


class CreateMaterialRequest(BaseModel):
    name: str
    type: str
    tags: list[str]
    date: str
    thumb: str
    assets: list[dict[str, object]] = Field(default_factory=list)
