"""模拟面试的请求/响应结构。"""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models.interview import (
    INTERVIEW_DIFFICULTIES,
    INTERVIEW_STATUS_ACTIVE,
    INTERVIEW_STATUS_FINISHED,
    INTERVIEW_TYPES,
    INTERVIEWER_STYLES,
)

MAX_INTERVIEW_ROUNDS = 12
MIN_INTERVIEW_ROUNDS = 3
MAX_ANSWER_CHARS = 8000
MAX_PERSONA_CHARS = 2000
MAX_FOCUS_CHARS = 255

InterviewType = Literal[
    "技术面",
    "项目深挖",
    "行为面（STAR）",
    "HR 面",
    "综合面",
    "案例分析",
    "英语面试",
    "压力面",
]
InterviewDifficulty = Literal["初级", "中级", "高级"]
InterviewerStyle = Literal["严谨专业", "温和引导", "持续追问", "压力质询"]
InterviewStatus = Literal["active", "finished"]


class InterviewCreate(BaseModel):
    """开一场模拟面试。

    只有 ``job_id`` 是可选的关联，其余都有默认值——用户可以"打开就能开始"，
    也可以把难度、风格、轮数、人设都调一遍。
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=128)
    job_id: int | None = Field(default=None, ge=1)
    interview_type: InterviewType = "技术面"
    difficulty: InterviewDifficulty = "中级"
    interviewer_style: InterviewerStyle = "严谨专业"
    rounds: int = Field(default=6, ge=MIN_INTERVIEW_ROUNDS, le=MAX_INTERVIEW_ROUNDS)
    # 自定义面试官人设（会拼进系统提示，优先级高于默认风格）。
    persona: str = Field(default="", max_length=MAX_PERSONA_CHARS)
    focus: str = Field(default="", max_length=MAX_FOCUS_CHARS)

    @field_validator("interview_type")
    @classmethod
    def type_must_be_supported(cls, value: str) -> str:
        return _validate_choice(value, INTERVIEW_TYPES, "面试类型")

    @field_validator("difficulty")
    @classmethod
    def difficulty_must_be_supported(cls, value: str) -> str:
        return _validate_choice(value, INTERVIEW_DIFFICULTIES, "难度")

    @field_validator("interviewer_style")
    @classmethod
    def style_must_be_supported(cls, value: str) -> str:
        return _validate_choice(value, INTERVIEWER_STYLES, "面试官风格")


class InterviewAnswerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=MAX_ANSWER_CHARS)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("回答不能为空")
        return cleaned


class InterviewMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    context: dict[str, Any] = Field(default_factory=dict)
    status: str
    error: str
    created_at: datetime


class InterviewBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    job_id: int | None
    job_title: str
    company: str
    interview_type: str
    difficulty: str
    interviewer_style: str
    rounds: int
    status: InterviewStatus
    created_at: datetime
    updated_at: datetime
    # 已完成的问答轮数，列表里显示"第 3/6 轮"。
    answered_rounds: int = 0


class InterviewDetail(InterviewBrief):
    persona: str = ""
    focus: str = ""
    model: str = ""
    report: dict[str, Any] = Field(default_factory=dict)
    messages: list[InterviewMessageOut] = Field(default_factory=list)


class InterviewAnswerResult(BaseModel):
    """一轮问答的结果：点评 + 下一题（或收尾）。"""

    session: InterviewDetail
    feedback: str = ""
    # 为真表示这场面试已经结束（达到计划轮数或候选人要求收尾），此时应生成报告。
    finished: bool = False


def _validate_choice(value: str, allowed: tuple[str, ...], label: str) -> str:
    cleaned = (value or "").strip()
    if cleaned not in allowed:
        raise ValueError(f"无效的{label}，可选值：{'、'.join(allowed)}")
    return cleaned


__all__ = [
    "MAX_INTERVIEW_ROUNDS",
    "MIN_INTERVIEW_ROUNDS",
    "InterviewAnswerCreate",
    "InterviewAnswerResult",
    "InterviewBrief",
    "InterviewCreate",
    "InterviewDetail",
    "InterviewMessageOut",
    "INTERVIEW_STATUS_ACTIVE",
    "INTERVIEW_STATUS_FINISHED",
]
