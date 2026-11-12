from pydantic import BaseModel

class TagSchema(BaseModel):
    id: str
    name: str
    description: str
    prompt: str

class TagCategorySchema(BaseModel):
    id: str
    name: str
    tags: list[TagSchema]