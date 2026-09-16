"""个人照片（可多张）Schema。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .profile import validate_photo_data_url

MAX_PROFILE_PHOTOS = 8


class ProfilePhotoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=128)
    image: str = ""

    @field_validator("image")
    @classmethod
    def image_must_be_safe(cls, value: str) -> str:
        value = validate_photo_data_url(value)
        if not value:
            raise ValueError("请选择一张照片")
        return value


class ProfilePhotoUpdate(BaseModel):
    """重命名或切换主照片；只提交要改的那一项。"""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=128)
    is_primary: bool | None = None


class ProfilePhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    image: str
    is_primary: bool
    created_at: datetime
