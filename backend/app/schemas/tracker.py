"""求职进度 Schema。

识别导入走"**先预览、再确认**"两步：解析接口只算不写，把"这条会新增 / 会更新 /
没变化"连同原因一起返回；用户确认后再提交真正的写入。这与岗位多份导入是同一条
原则——识别结果在用户核对之前不落库。

写入路径都不接受 `company_key` / `title_key`：合并键由服务层从公司名与岗位名算出，
不让调用方（包括模型）有机会构造一个"看起来一样但合并不到一起"的键。
"""
from __future__ import annotations

import re
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .extraction import (
    MAX_EXTRACTION_DOCUMENT_COUNT,
    MAX_EXTRACTION_IMAGE_COUNT,
    ExtractionDocumentInput,
    ExtractionImageInput,
)

MAX_TRACK_COMPANY_CHARS = 128
MAX_TRACK_TITLE_CHARS = 128
MAX_TRACK_STAGE_NOTE_CHARS = 64
MAX_TRACK_NOTE_CHARS = 4_000
MAX_TRACK_EVIDENCE_CHARS = 500
MAX_TRACK_NEXT_ACTION_CHARS = 255
MAX_TRACK_DATE_CHARS = 16
# 一次最多处理多少条识别结果：一封邮件通常只对应一条，一次粘贴几十条已经很多了。
MAX_TRACK_RECORDS = 30
MAX_TRACK_TEXT_CHARS = 50_000

_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")


def _is_date_or_empty(value: str) -> bool:
    """``YYYY-MM-DD`` 或空串，且必须是真实存在的日历日（挡掉 2026-02-31）。"""
    if not value:
        return True
    if not _DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


class TrackRecordIn(BaseModel):
    """一条进度记录的内容（识别结果或手工填写），不含 id 与合并键。"""

    model_config = ConfigDict(extra="forbid")

    company: str = Field(default="", max_length=MAX_TRACK_COMPANY_CHARS)
    title: str = Field(default="", max_length=MAX_TRACK_TITLE_CHARS)
    status: str = Field(default="applied", max_length=24)
    stage_note: str = Field(default="", max_length=MAX_TRACK_STAGE_NOTE_CHARS)
    applied_at: str = Field(default="", max_length=MAX_TRACK_DATE_CHARS)
    status_date: str = Field(default="", max_length=MAX_TRACK_DATE_CHARS)
    next_action: str = Field(default="", max_length=MAX_TRACK_NEXT_ACTION_CHARS)
    next_action_date: str = Field(default="", max_length=MAX_TRACK_DATE_CHARS)
    note: str = Field(default="", max_length=MAX_TRACK_NOTE_CHARS)
    # 这一条是从哪句话看出来的。只存简短片段，不存整封邮件。
    evidence: str = Field(default="", max_length=MAX_TRACK_EVIDENCE_CHARS)

    @field_validator("status")
    @classmethod
    def status_must_be_known(cls, value: str) -> str:
        from ..models.tracker import STATUSES

        cleaned = (value or "").strip()
        if cleaned not in STATUSES:
            raise ValueError(f"未知的进度状态「{cleaned}」")
        return cleaned

    @field_validator("applied_at", "status_date", "next_action_date")
    @classmethod
    def dates_must_be_real(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not _is_date_or_empty(cleaned):
            raise ValueError("日期要写成 2026-09-18 这样的真实日期，或留空")
        return cleaned

    @model_validator(mode="after")
    def must_identify_a_position(self) -> "TrackRecordIn":
        """没有公司或没有岗位，就无从判断它该并到哪一条上。"""
        self.company = self.company.strip()
        self.title = self.title.strip()
        self.stage_note = self.stage_note.strip()
        self.next_action = self.next_action.strip()
        self.note = self.note.strip()
        self.evidence = self.evidence.strip()
        if not self.company or not self.title:
            raise ValueError("请填写公司和岗位名称——进度要按这两项合并")
        return self


class TrackCreate(TrackRecordIn):
    """手工新建一条进度。"""

    job_id: int | None = Field(default=None, ge=1)
    resume_id: int | None = Field(default=None, ge=1)


class TrackUpdate(TrackCreate):
    """PUT 语义：整体替换一条进度。"""


class TrackOut(TrackCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    created_at: datetime
    updated_at: datetime


class TrackListOut(BaseModel):
    """列表 + 漏斗统计。统计随列表一起下发，免得前端为了画漏斗再拉一次全量。"""

    items: list[TrackOut]
    total: int
    # 各状态计数（含计数为 0 的状态），界面据此画漏斗。
    status_counts: dict[str, int] = Field(default_factory=dict)
    active_count: int
    offer_count: int
    rejected_count: int
    # 本月投递数：按 applied_at 落在当前自然月统计。
    month_count: int


class TrackMergePreview(BaseModel):
    """一条识别结果合并后会怎样——**不写库**，只回答"会发生什么"。"""

    record: TrackRecordIn
    action: str
    # 面向用户的原因，例如"已有记录处于「面试」，这条更早，保留现有进度"。
    reason: str
    # 合并前该条记录的当前状态；新建时为空串。
    current_status: str = ""


class TrackParseRequest(BaseModel):
    """粘贴的通知文本、通知截图或邮件导出文档（可同时给）。"""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(default="", max_length=MAX_TRACK_TEXT_CHARS)
    images: list[ExtractionImageInput] = Field(
        default_factory=list, max_length=MAX_EXTRACTION_IMAGE_COUNT
    )
    documents: list[ExtractionDocumentInput] = Field(
        default_factory=list, max_length=MAX_EXTRACTION_DOCUMENT_COUNT
    )

    @model_validator(mode="after")
    def require_text_or_attachments(self) -> "TrackParseRequest":
        if not self.text.strip() and not self.images and not self.documents:
            raise ValueError("请粘贴通知内容，或上传至少一张截图或一份文档")
        return self


class TrackParseOut(BaseModel):
    items: list[TrackMergePreview]
    # ai / local：如实告诉用户这次是靠模型还是靠本地关键词匹配。
    parse_engine: str
    notes: list[str] = Field(default_factory=list)


class TrackApplyRequest(BaseModel):
    """用户确认后的写入。只提交勾选的条目。"""

    model_config = ConfigDict(extra="forbid")

    items: list[TrackRecordIn] = Field(default_factory=list, max_length=MAX_TRACK_RECORDS)
    # 这些条目的来源标记，默认「识别导入」；投递台自动记录时不走这个接口。
    source: str = Field(default="recognized", max_length=16)

    @field_validator("source")
    @classmethod
    def source_must_be_known(cls, value: str) -> str:
        from ..models.tracker import SOURCES

        cleaned = (value or "").strip() or "recognized"
        if cleaned not in SOURCES:
            raise ValueError(f"未知的记录来源「{cleaned}」")
        return cleaned


class TrackApplyItemResult(BaseModel):
    company: str
    title: str
    action: str
    status: str
    reason: str = ""


class TrackApplyOut(BaseModel):
    items: list[TrackApplyItemResult]
    created: int
    updated: int
    unchanged: int


__all__ = [
    "MAX_TRACK_RECORDS",
    "TrackApplyItemResult",
    "TrackApplyOut",
    "TrackApplyRequest",
    "TrackCreate",
    "TrackListOut",
    "TrackMergePreview",
    "TrackOut",
    "TrackParseOut",
    "TrackParseRequest",
    "TrackRecordIn",
    "TrackUpdate",
]
