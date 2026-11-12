from dataclasses import dataclass


@dataclass
class Task:
    id: str
    title: str
    type: str
    status: str
    updated: str
    targetPlatform: str
    creationId: str | None = None
    body: str = ""
    tags: list[str] | None = None
    assignee: str = ""
    dueDate: str = ""
    priority: str = "normal"
    handoffNote: str = ""
