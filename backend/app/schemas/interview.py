"""模拟面试的请求/响应结构。"""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..models.interview import (
    INTERVIEW_DIFFICULTIES,
    INTERVIEW_STATUS_ACTIVE,
    INTERVIEW_STATUS_FINISHED,
    INTERVIEW_TYPES,
    INTERVIEWER_STYLES,
)
from .resume import ResumeSuggestion

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


# ===== R-11 个性化题库 / 答题思路分析 / 反向优化简历 =====
# 题库三类固定：基础题（岗位通识与自我介绍）、项目深挖题（基于简历/台账逐条追问）、
# 反问 HR 题（候选人反向了解公司与岗位）。三类即时生成、不落库。
QUESTION_BANK_TYPES = ("基础题", "项目深挖题", "反问HR题")

# 参考答案（单题）字段的长度上限，复用于题库历史里持久化的参考答案。
MAX_QUESTION_ANSWER_CHARS = 10_000
MAX_SAMPLE_PHRASING_CHARS = 5_000

MAX_QUESTION_BANK_PER_TYPE = 8
MAX_ANALYSIS_QUESTION_CHARS = 2000
MAX_ANALYSIS_CONTEXT_CHARS = 20_000
MAX_OPTIMIZE_ITEMS = 20


class InterviewQuestionItem(BaseModel):
    """题库里的一道题：问题本身 + 考察意图 + 一句话回答提示。

    可选携带已生成的参考答案（answer/key_points/sample_phrasing）：从历史记录打开题库时，
    这些字段若已存在会被直接渲染，不必重新生成。
    """

    question: str = Field(default="", max_length=2000)
    purpose: str = Field(default="", max_length=1000)
    answer_hint: str = Field(default="", max_length=2000)
    answer: str | None = Field(default=None, max_length=MAX_QUESTION_ANSWER_CHARS)
    key_points: list[str] | None = Field(default=None, max_length=20)
    sample_phrasing: str | None = Field(default=None, max_length=MAX_SAMPLE_PHRASING_CHARS)


class QuestionBankGroup(BaseModel):
    """按类型分组的一批题。``type`` 取值见 ``QUESTION_BANK_TYPES``。"""

    type: str = Field(default="", max_length=32)
    questions: list[InterviewQuestionItem] = Field(
        default_factory=list, max_length=MAX_QUESTION_BANK_PER_TYPE
    )


class QuestionBankOut(BaseModel):
    """个性化题库的即时结果。"""

    job_id: int | None = None
    job_title: str = ""
    company: str = ""
    resume_id: int | None = None
    groups: list[QuestionBankGroup] = Field(default_factory=list, max_length=len(QUESTION_BANK_TYPES))
    llm_used: bool = True
    notes: list[str] = Field(default_factory=list)


class InterviewQuestionGenerateRequest(BaseModel):
    """生成题库的输入：岗位与简历都可选，至少给一个才有针对性。"""

    model_config = ConfigDict(extra="forbid")

    job_id: int | None = Field(default=None, ge=1)
    resume_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_a_target(self) -> "InterviewQuestionGenerateRequest":
        if self.job_id is None and self.resume_id is None:
            raise ValueError("请至少关联一个岗位或一份简历，题库才能有针对性")
        return self


class InterviewAnalysisRequest(BaseModel):
    """输入一道真实问题，分析答题思路。"""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=MAX_ANALYSIS_QUESTION_CHARS)
    job_id: int | None = Field(default=None, ge=1)
    resume_id: int | None = Field(default=None, ge=1)
    # 用户补充的背景（如"这是二面的追问"）。
    context: str = Field(default="", max_length=MAX_ANALYSIS_CONTEXT_CHARS)

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("问题不能为空")
        return cleaned


class InterviewAnalysisOut(BaseModel):
    """答题思路：框架 + 要点 + 可能的追问 + 常见误区。"""

    question: str = ""
    framework: str = Field(default="", max_length=10_000)
    key_points: list[str] = Field(default_factory=list, max_length=20)
    follow_up: list[str] = Field(default_factory=list, max_length=20)
    pitfalls: list[str] = Field(default_factory=list, max_length=20)


class InterviewQuestionAnswerRequest(BaseModel):
    """为单道题生成详细参考答案：题目必填，岗位与简历可选（给背景）。"""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=MAX_ANALYSIS_QUESTION_CHARS)
    job_id: int | None = Field(default=None, ge=1)
    resume_id: int | None = Field(default=None, ge=1)

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("问题不能为空")
        return cleaned


class InterviewQuestionAnswerOut(BaseModel):
    """单题的详细参考答案：正文 + 要点 + 一句可套用的话术。"""

    question: str = ""
    answer: str = Field(default="", max_length=MAX_QUESTION_ANSWER_CHARS)
    key_points: list[str] = Field(default_factory=list, max_length=20)
    sample_phrasing: str = Field(default="", max_length=MAX_SAMPLE_PHRASING_CHARS)


class InterviewOptimizeRequest(BaseModel):
    """把面试暴露的短板与高频追问，反向转成简历改写建议。"""

    model_config = ConfigDict(extra="forbid")

    resume_id: int = Field(ge=1)
    job_id: int | None = Field(default=None, ge=1)
    # 面试里暴露的短板（如"项目难点说不清"）。
    weaknesses: list[str] = Field(default_factory=list, max_length=MAX_OPTIMIZE_ITEMS)
    # 面试官的高频追问（如"这个指标怎么算出来的"）。
    follow_ups: list[str] = Field(default_factory=list, max_length=MAX_OPTIMIZE_ITEMS)

    @model_validator(mode="after")
    def require_some_input(self) -> "InterviewOptimizeRequest":
        if not self.weaknesses and not self.follow_ups:
            raise ValueError("请至少填写一条面试暴露的短板或高频追问")
        return self


class InterviewOptimizeOut(BaseModel):
    """反向优化结果：**只产出建议列表**，不直接修改简历正文（回填由前端走既有编辑流程）。"""

    resume_id: int
    suggestions: list[ResumeSuggestion] = Field(default_factory=list, max_length=20)
    llm_used: bool = True
    notes: list[str] = Field(default_factory=list)


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
    "QUESTION_BANK_TYPES",
    "InterviewQuestionItem",
    "QuestionBankGroup",
    "QuestionBankOut",
    "InterviewQuestionGenerateRequest",
    "InterviewAnalysisRequest",
    "InterviewAnalysisOut",
    "InterviewQuestionAnswerRequest",
    "InterviewQuestionAnswerOut",
    "InterviewOptimizeRequest",
    "InterviewOptimizeOut",
]
