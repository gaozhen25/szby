from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class OnlineSearchFilter(BaseModel):
    needContent: bool = True
    needUrl: bool = False
    sites: str = ""
    blockHosts: str = ""
    authInfoLevel: int = Field(default=0, ge=0)

    def to_provider_payload(self) -> dict[str, Any]:
        return {
            "NeedContent": self.needContent,
            "NeedUrl": self.needUrl,
            "Sites": self.sites,
            "BlockHosts": self.blockHosts,
            "AuthInfoLevel": self.authInfoLevel,
        }


class OnlineSearchQueryControl(BaseModel):
    queryRewrite: bool = False

    def to_provider_payload(self) -> dict[str, Any]:
        return {"QueryRewrite": self.queryRewrite}


class OnlineSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    searchType: Literal["web"] = "web"
    count: int = Field(default=10, ge=1, le=50)
    filter: OnlineSearchFilter = Field(default_factory=OnlineSearchFilter)
    needSummary: bool = True
    timeRange: str = ""
    queryControl: OnlineSearchQueryControl = Field(default_factory=OnlineSearchQueryControl)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be blank")
        return value

    def to_provider_payload(self) -> dict[str, Any]:
        return {
            "Query": self.query,
            "SearchType": self.searchType,
            "Count": self.count,
            "Filter": self.filter.to_provider_payload(),
            "NeedSummary": self.needSummary,
            "TimeRange": self.timeRange,
            "QueryControl": self.queryControl.to_provider_payload(),
        }
