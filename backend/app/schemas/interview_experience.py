"""面经知识库（R-15）的请求/响应结构。

与模拟面试（``schemas/interview.py``）分开：模拟面试是对话式练习，这里沉淀的是**真实面经**
——正文 + 被问到的真实问题清单 + 标签。来源三类（自己/同行/公开），只做分类不做断言。

写入侧做严格校验（来源白名单、日期格式、至少有一项内容）；读取侧只如实回显。
"""
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..models.interview_experience import (
    EXPERIENCE_SOURCES,
    EXPERIENCE_SOURCE_SELF,
)

MAX_EXPERIENCE_CONTENT_CHARS = 100_000
MAX_EXPERIENCE_QUESTIONS = 200
MAX_EXPERIENCE_TAGS = 50

ExperienceSource = Literal["self", "peer", "public"]

# YYYY-MM-DD，未知为空串。与资料库/台账的日期字段保持一致的字符串表示。
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_source(value: str) -> str:
    cleaned = (value or "").strip()
    if cleaned not in EXPERIENCE_SOURCES:
        raise ValueError(f"无效的面经来源，可选值：{'、'.join(EXPERIENCE_SOURCES)}")
    return cleaned


def _validate_interview_date(value: str) -> str:
    cleaned = (value or "").strip()
    if cleaned and not _DATE_RE.fullmatch(cleaned):
        raise ValueError("面试日期必须是 YYYY-MM-DD 格式，留空表示未知")
    return cleaned


class InterviewExperienceCreate(BaseModel):
    """新增一条面经。

    ``company``/``position`` 是快照：即便之后绑定的岗位被删除，面经仍可读、仍可按公司检索。
    ``job_id`` 只是可选关联，删除后置空（外键 SET NULL）。
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=200)
    company: str = Field(default="", max_length=128)
    position: str = Field(default="", max_length=128)
    job_id: int | None = Field(default=None, ge=1)
    content: str = Field(default="", max_length=MAX_EXPERIENCE_CONTENT_CHARS)
    # 被问到的真实问题清单（R-11 录入）。与题库"即时生成、不落库"互补。
    questions: list[str] = Field(default_factory=list, max_length=MAX_EXPERIENCE_QUESTIONS)
    tags: list[str] = Field(default_factory=list, max_length=MAX_EXPERIENCE_TAGS)
    source: ExperienceSource = EXPERIENCE_SOURCE_SELF
    difficulty: str = Field(default="", max_length=16)
    round_type: str = Field(default="", max_length=32)
    interview_date: str = Field(default="", max_length=10)

    @field_validator("source")
    @classmethod
    def source_must_be_supported(cls, value: str) -> str:
        return _validate_source(value)

    @field_validator("interview_date")
    @classmethod
    def interview_date_must_be_valid(cls, value: str) -> str:
        return _validate_interview_date(value)

    @field_validator("questions", "tags")
    @classmethod
    def strings_must_be_clean(cls, value: list[str]) -> list[str]:
        return [str(item).strip() for item in value if str(item).strip()][
            : MAX_EXPERIENCE_QUESTIONS
        ]

    @model_validator(mode="after")
    def require_something(self) -> "InterviewExperienceCreate":
        self.title = self.title.strip()
        self.company = self.company.strip()
        self.position = self.position.strip()
        if not self.title and not self.company and not self.content.strip() and not self.questions:
            raise ValueError("请至少填写标题、公司、正文或真实问题清单")
        return self


class InterviewExperienceUpdate(InterviewExperienceCreate):
    """PUT 语义：整体替换一条面经。"""


class InterviewExperienceOut(InterviewExperienceCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


__all__ = [
    "ExperienceSource",
    "InterviewExperienceCreate",
    "InterviewExperienceOut",
    "InterviewExperienceUpdate",
    "MAX_EXPERIENCE_CONTENT_CHARS",
    "MAX_EXPERIENCE_QUESTIONS",
    "MAX_EXPERIENCE_TAGS",
]
