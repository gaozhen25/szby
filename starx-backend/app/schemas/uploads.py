from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

UploadPurpose = Literal[
    "publish_video",
    "publish_image",
    "knowledge_base_image",
    "generation_reference",
    "generation_material",
    "person_replacement_target",
    "person_replacement_person",
    "digital_human_source",
    "digital_human_editing_asset",
    "digital_human_background_music",
]


class PresignUploadRequest(BaseModel):
    accountId: str | None = None
    purpose: UploadPurpose
    filename: str = Field(min_length=1, max_length=255)
    contentType: str = Field(min_length=1, max_length=128)
    sizeBytes: int = Field(gt=0)
    sha256: str = Field(default="", max_length=64)

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        digest = value.strip().lower()
        if digest and (len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest)):
            raise ValueError("sha256 must be a 64-character hexadecimal digest")
        return digest


class PresignUploadResponse(BaseModel):
    uploadId: str
    method: Literal["PUT"] = "PUT"
    uploadUrl: str
    objectKey: str
    objectUrl: str
    headers: dict[str, str]
    expiresAt: datetime
    maxSizeBytes: int


class UploadedObjectRef(BaseModel):
    uploadId: str = ""
    url: str = Field(min_length=1, max_length=4000)
    filename: str = Field(default="", max_length=255)
    contentType: str = Field(default="", max_length=128)
    sizeBytes: int | None = Field(default=None, ge=0)
    etag: str = Field(default="", max_length=255)
