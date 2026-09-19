"""日历提醒（R-12）的请求/响应结构。

提醒把"什么时候该做什么"落成一条记录：标题是提醒内容，``remind_at`` 是唯一权威时点，
``kind`` 决定归类，``status`` 三态只回答"待办 / 已完成 / 已忽略"。三个绑定对象
（``track_id``/``job_id``/``resume_id``）都可空，被删对象置空（外键 SET NULL）。

写入侧严格校验（标题非空、时点必填、kind/status 白名单）；读取侧如实回显。
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models.reminder import (
    REMINDER_KINDS,
    REMINDER_STATUSES,
    REMINDER_KIND_OTHER,
    REMINDER_STATUS_PENDING,
)

MAX_REMINDER_TITLE_CHARS = 200
MAX_REMINDER_NOTE_CHARS = 4000

ReminderKind = Literal["interview", "assessment_deadline", "hr_reply", "other"]
ReminderStatus = Literal["pending", "done", "dismissed"]
ReminderUrgency = Literal["overdue", "soon", "upcoming", "later"]


def _validate_kind(value: str) -> str:
    cleaned = (value or "").strip()
    if cleaned not in REMINDER_KINDS:
        raise ValueError(f"无效的提醒类型，可选值：{'、'.join(REMINDER_KINDS)}")
    return cleaned


def _validate_status(value: str) -> str:
    cleaned = (value or "").strip()
    if cleaned not in REMINDER_STATUSES:
        raise ValueError(f"无效的提醒状态，可选值：{'、'.join(REMINDER_STATUSES)}")
    return cleaned


class ReminderCreate(BaseModel):
    """新增一条提醒。标题与提醒时间是必填，其余都有默认值。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=MAX_REMINDER_TITLE_CHARS)
    remind_at: datetime
    kind: ReminderKind = REMINDER_KIND_OTHER
    status: ReminderStatus = REMINDER_STATUS_PENDING
    track_id: int | None = Field(default=None, ge=1)
    job_id: int | None = Field(default=None, ge=1)
    resume_id: int | None = Field(default=None, ge=1)
    note: str = Field(default="", max_length=MAX_REMINDER_NOTE_CHARS)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("提醒标题不能为空")
        return cleaned

    @field_validator("kind")
    @classmethod
    def kind_must_be_supported(cls, value: str) -> str:
        return _validate_kind(value)

    @field_validator("status")
    @classmethod
    def status_must_be_supported(cls, value: str) -> str:
        return _validate_status(value)


class ReminderUpdate(BaseModel):
    """PATCH 语义：只更新显式给出的字段，未给出的保持不变。"""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=MAX_REMINDER_TITLE_CHARS)
    remind_at: datetime | None = None
    kind: ReminderKind | None = None
    status: ReminderStatus | None = None
    track_id: int | None = Field(default=None, ge=1)
    job_id: int | None = Field(default=None, ge=1)
    resume_id: int | None = Field(default=None, ge=1)
    note: str | None = Field(default=None, max_length=MAX_REMINDER_NOTE_CHARS)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("提醒标题不能为空")
        return cleaned

    @field_validator("kind")
    @classmethod
    def kind_must_be_supported(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_kind(value)

    @field_validator("status")
    @classmethod
    def status_must_be_supported(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_status(value)


class ReminderOut(ReminderCreate):
    """读取回显：在写入结构之外补上服务端生成字段。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class ReminderUpcomingOut(ReminderOut):
    """待办提醒的首页回显：在 ReminderOut 之外补紧急度与展示标签。

    ``urgency`` / ``due_label`` 不在表里，由 ``services/reminder_service`` 统一计算。
    """

    urgency: ReminderUrgency = "later"
    due_label: str = ""


__all__ = [
    "MAX_REMINDER_NOTE_CHARS",
    "MAX_REMINDER_TITLE_CHARS",
    "ReminderCreate",
    "ReminderKind",
    "ReminderOut",
    "ReminderStatus",
    "ReminderUpcomingOut",
    "ReminderUpdate",
    "ReminderUrgency",
]
