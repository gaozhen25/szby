from pydantic import BaseModel


class DashboardSchema(BaseModel):
    views: str
    changeCount: int
    creation: int
    tools: int
    competitorCount: int
    competitorPosts: int
    materialCount: int


class SummaryItemSchema(BaseModel):
    id: str
    name: str
    type: str
    dashboard: DashboardSchema
