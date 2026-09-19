"""内推管理（R-13）的请求/响应结构。

内推与投递台自动投递是两件事：这里记录的是"通过人脉拿到的一次推荐机会"。``converted``
是**冗余展示字段**，权威口径由关联的 ``ApplicationTrack`` 后置位派生（有 track 且进入
面试及以上才算转化），因此**写入侧不接受 ``converted``**——避免在表里再手算一份口径。
"""
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models.referral import REFERRAL_STATUSES, REFERRAL_STATUS_ACTIVE

MAX_REFERRAL_TEXT_CHARS = 128
MAX_RELATION_CHARS = 64
MAX_CHANNEL_CHARS = 32
MAX_NOTE_CHARS = 4000
MAX_REFERRAL_CODE_CHARS = 64
MAX_NOTE_IMAGES = 9

ReferralStatus = Literal["active", "submitted", "closed", "invalid"]

# YYYY-MM-DD，未知为空串（与资料库/台账的日期字段保持一致）。
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_status(value: str) -> str:
    cleaned = (value or "").strip()
    if cleaned not in REFERRAL_STATUSES:
        raise ValueError(f"无效的内推状态，可选值：{'、'.join(REFERRAL_STATUSES)}")
    return cleaned


def _validate_date(value: str) -> str:
    cleaned = (value or "").strip()
    if cleaned and not _DATE_RE.fullmatch(cleaned):
        raise ValueError("投递日期必须是 YYYY-MM-DD 格式，留空表示未知")
    return cleaned


class ReferralCreate(BaseModel):
    """新增一条内推。公司/岗位/内推岗位都是快照，删岗位不连坐。"""

    model_config = ConfigDict(extra="forbid")

    job_id: int | None = Field(default=None, ge=1)
    job_title: str = Field(default="", max_length=MAX_REFERRAL_TEXT_CHARS)
    company: str = Field(default="", max_length=MAX_REFERRAL_TEXT_CHARS)
    referrer_name: str = Field(default="", max_length=MAX_REFERRAL_TEXT_CHARS)
    referrer_contact: str = Field(default="", max_length=MAX_REFERRAL_TEXT_CHARS)
    relation: str = Field(default="", max_length=MAX_RELATION_CHARS)
    position: str = Field(default="", max_length=MAX_REFERRAL_TEXT_CHARS)
    channel: str = Field(default="", max_length=MAX_CHANNEL_CHARS)
    status: ReferralStatus = REFERRAL_STATUS_ACTIVE
    track_id: int | None = Field(default=None, ge=1)
    submitted_at: str = Field(default="", max_length=16)
    note: str = Field(default="", max_length=MAX_NOTE_CHARS)
    # 内推码（第 6 批落地）：官网/牛客内推码等，选填。
    referral_code: str | None = Field(default=None, max_length=MAX_REFERRAL_CODE_CHARS)
    # 备注图片：上传接口返回的相对路径列表，缩略预览用。
    note_images: list[str] = Field(default_factory=list, max_length=MAX_NOTE_IMAGES)

    @field_validator("status")
    @classmethod
    def status_must_be_supported(cls, value: str) -> str:
        return _validate_status(value)

    @field_validator("submitted_at")
    @classmethod
    def submitted_at_must_be_valid(cls, value: str) -> str:
        return _validate_date(value)


class ReferralUpdate(BaseModel):
    """PATCH 语义：只更新显式给出的字段。"""

    model_config = ConfigDict(extra="forbid")

    job_id: int | None = Field(default=None, ge=1)
    job_title: str | None = Field(default=None, max_length=MAX_REFERRAL_TEXT_CHARS)
    company: str | None = Field(default=None, max_length=MAX_REFERRAL_TEXT_CHARS)
    referrer_name: str | None = Field(default=None, max_length=MAX_REFERRAL_TEXT_CHARS)
    referrer_contact: str | None = Field(default=None, max_length=MAX_REFERRAL_TEXT_CHARS)
    relation: str | None = Field(default=None, max_length=MAX_RELATION_CHARS)
    position: str | None = Field(default=None, max_length=MAX_REFERRAL_TEXT_CHARS)
    channel: str | None = Field(default=None, max_length=MAX_CHANNEL_CHARS)
    status: ReferralStatus | None = None
    track_id: int | None = Field(default=None, ge=1)
    submitted_at: str | None = Field(default=None, max_length=16)
    note: str | None = Field(default=None, max_length=MAX_NOTE_CHARS)
    referral_code: str | None = Field(default=None, max_length=MAX_REFERRAL_CODE_CHARS)
    note_images: list[str] | None = Field(default=None, max_length=MAX_NOTE_IMAGES)

    @field_validator("status")
    @classmethod
    def status_must_be_supported(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_status(value)

    @field_validator("submitted_at")
    @classmethod
    def submitted_at_must_be_valid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_date(value)


class ReferralOut(BaseModel):
    """读取回显。``converted`` 由服务层按关联漏斗后置位派生。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int | None
    job_title: str
    company: str
    referrer_name: str
    referrer_contact: str
    relation: str
    position: str
    channel: str
    status: str
    track_id: int | None
    converted: bool
    submitted_at: str
    note: str
    referral_code: str
    note_images: list[str]
    created_at: datetime
    updated_at: datetime


class ReferralImageUploadOut(BaseModel):
    """内推备注图片上传结果：``path`` 是相对数据目录的相对路径。"""

    path: str


class ReferralStatsOut(BaseModel):
    """内推转化率：``converted`` 已转化、``total`` 有效内推（非 closed/invalid）。"""

    total: int
    converted: int
    rate: float


__all__ = [
    "MAX_CHANNEL_CHARS",
    "MAX_NOTE_CHARS",
    "MAX_NOTE_IMAGES",
    "MAX_REFERRAL_CODE_CHARS",
    "MAX_REFERRAL_TEXT_CHARS",
    "MAX_RELATION_CHARS",
    "ReferralCreate",
    "ReferralImageUploadOut",
    "ReferralOut",
    "ReferralStatsOut",
    "ReferralStatus",
    "ReferralUpdate",
]
