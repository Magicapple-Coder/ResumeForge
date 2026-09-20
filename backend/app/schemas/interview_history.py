"""题库历史 / 面试复盘历史（D5）的请求/响应结构。

题库本体与复盘本体都是「即时生成、不落库」的，这里只是把用户主动「保存」的那一份落成历史，
供回看与删除。写入侧做白名单与长度校验；读取侧只如实回显。
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .interview import QUESTION_BANK_TYPES, QuestionBankGroup

MAX_BANK_TITLE_CHARS = 128
MAX_RESUME_TITLE_CHARS = 256
MAX_BANK_MODEL_CHARS = 64
MAX_REVIEW_QUESTIONS = 200
MAX_REVIEW_SUGGESTIONS = 20
MAX_QUESTION_TEXT_CHARS = 2000


class QuestionBankRecordCreate(BaseModel):
    """保存一次生成的题库：三类分组 + 岗位/简历快照。"""

    model_config = ConfigDict(extra="forbid")

    job_id: int | None = Field(default=None, ge=1)
    job_title: str = Field(default="", max_length=MAX_BANK_TITLE_CHARS)
    company: str = Field(default="", max_length=MAX_BANK_TITLE_CHARS)
    resume_id: int | None = Field(default=None, ge=1)
    resume_title: str = Field(default="", max_length=MAX_RESUME_TITLE_CHARS)
    groups: list[QuestionBankGroup] = Field(default_factory=list, max_length=len(QUESTION_BANK_TYPES))
    model: str = Field(default="", max_length=MAX_BANK_MODEL_CHARS)


class QuestionBankRecordOut(BaseModel):
    """一次被保存的题库历史记录。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int | None = None
    job_title: str = ""
    company: str = ""
    resume_id: int | None = None
    resume_title: str = ""
    groups: list[QuestionBankGroup] = Field(default_factory=list)
    model: str = ""
    created_at: datetime
    updated_at: datetime


class QuestionBankRecordUpdate(BaseModel):
    """局部更新题库历史（历史记录富还原：把新生成的参考答案写回同一条记录）。

    只接受需要回写的字段；未提供的字段保持原值。
    """

    model_config = ConfigDict(extra="forbid")

    groups: list[QuestionBankGroup] | None = Field(default=None, max_length=len(QUESTION_BANK_TYPES))
    job_title: str | None = Field(default=None, max_length=MAX_BANK_TITLE_CHARS)
    company: str | None = Field(default=None, max_length=MAX_BANK_TITLE_CHARS)
    resume_title: str | None = Field(default=None, max_length=MAX_RESUME_TITLE_CHARS)


class InterviewReviewRecordCreate(BaseModel):
    """保存一次面试复盘：真实问题清单 + 答题思路 + 反向优化建议。"""

    model_config = ConfigDict(extra="forbid")

    job_id: int | None = Field(default=None, ge=1)
    job_title: str = Field(default="", max_length=MAX_BANK_TITLE_CHARS)
    company: str = Field(default="", max_length=MAX_BANK_TITLE_CHARS)
    resume_id: int | None = Field(default=None, ge=1)
    resume_title: str = Field(default="", max_length=MAX_RESUME_TITLE_CHARS)
    questions: list[str] = Field(default_factory=list, max_length=MAX_REVIEW_QUESTIONS)
    analysis: dict = Field(default_factory=dict)
    suggestions: list[dict] = Field(default_factory=list, max_length=MAX_REVIEW_SUGGESTIONS)
    model: str = Field(default="", max_length=MAX_BANK_MODEL_CHARS)


class InterviewReviewRecordOut(BaseModel):
    """一次被保存的面试复盘历史记录。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int | None = None
    job_title: str = ""
    company: str = ""
    resume_id: int | None = None
    resume_title: str = ""
    questions: list[str] = Field(default_factory=list)
    analysis: dict = Field(default_factory=dict)
    suggestions: list[dict] = Field(default_factory=list)
    model: str = ""
    created_at: datetime
    updated_at: datetime


class InterviewReviewRecordUpdate(BaseModel):
    """局部更新复盘历史（历史记录富还原：把新复盘/反向优化结果写回同一条记录）。

    只接受需要回写的字段；未提供的字段保持原值。
    """

    model_config = ConfigDict(extra="forbid")

    questions: list[str] | None = Field(default=None, max_length=MAX_REVIEW_QUESTIONS)
    analysis: dict | None = Field(default=None)
    suggestions: list[dict] | None = Field(default=None, max_length=MAX_REVIEW_SUGGESTIONS)
    job_title: str | None = Field(default=None, max_length=MAX_BANK_TITLE_CHARS)
    company: str | None = Field(default=None, max_length=MAX_BANK_TITLE_CHARS)
    resume_title: str | None = Field(default=None, max_length=MAX_RESUME_TITLE_CHARS)


__all__ = [
    "InterviewReviewRecordCreate",
    "InterviewReviewRecordOut",
    "InterviewReviewRecordUpdate",
    "MAX_BANK_MODEL_CHARS",
    "MAX_BANK_TITLE_CHARS",
    "MAX_QUESTION_TEXT_CHARS",
    "MAX_RESUME_TITLE_CHARS",
    "MAX_REVIEW_QUESTIONS",
    "MAX_REVIEW_SUGGESTIONS",
    "QuestionBankRecordCreate",
    "QuestionBankRecordOut",
    "QuestionBankRecordUpdate",
    "InterviewReviewRecordUpdate",
]
