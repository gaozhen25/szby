"""社媒账号定位请求的公共结构。"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


PlatformName = Literal["小红书", "抖音", "快手"]


class AccountReferenceRequest(BaseModel):
    """使用账号号值或公开主页链接定位一个平台账号。"""

    platform: PlatformName | None = None
    accountId: str = Field(default="", max_length=255)
    profileUrl: str = Field(default="", max_length=2048)

    @model_validator(mode="after")
    def validate_reference(self) -> "AccountReferenceRequest":
        self.accountId = self.accountId.strip()
        self.profileUrl = self.profileUrl.strip()
        if bool(self.accountId) == bool(self.profileUrl):
            raise ValueError("accountId 和 profileUrl 必须且只能提供一个")
        if self.accountId and self.platform is None:
            raise ValueError("使用 accountId 时必须提供 platform")
        return self
