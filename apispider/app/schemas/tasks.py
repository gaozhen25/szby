from pydantic import BaseModel, Field


class TaskSchema(BaseModel):
    id: str
    title: str
    type: str
    status: str
    updated: str
    targetPlatform: str
    creationId: str | None = None
    body: str = ""
    tags: list[str] = Field(default_factory=list)
    assignee: str = ""
    dueDate: str = ""
    priority: str = "normal"
    handoffNote: str = ""


class CreateTaskRequest(BaseModel):
    title: str
    type: str
    targetPlatform: str
    creationId: str | None = None
    body: str = ""
    tags: list[str] = Field(default_factory=list)
    assignee: str = ""
    dueDate: str = ""
    priority: str = "normal"
    handoffNote: str = ""


class UpdateTaskStatusRequest(BaseModel):
    status: str
