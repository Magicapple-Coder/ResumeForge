"""按台账深挖的面试 Schema。

写入路径都**不接受**证据状态：状态只能由服务层按"提问前锁定的契约"判定，不让调用方
（包括模型）直接指定——否则"这次算过"就成了一个可以被要求出来的结论。
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .extraction import (
    MAX_EXTRACTION_DOCUMENT_COUNT,
    MAX_EXTRACTION_IMAGE_COUNT,
    ExtractionDocumentInput,
    ExtractionImageInput,
)

MAX_DRILL_TITLE_CHARS = 128
MAX_DRILL_ANSWER_CHARS = 8_000
MAX_DRILL_CLAIMS = 12
MAX_DRILL_QUESTIONS = 12
DEFAULT_DRILL_QUESTIONS = 6
MAX_REHEARSAL_ITEMS = 6


class DrillPlan(BaseModel):
    """一道题的评分契约：提问**之前**生成，之后不许改。"""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1_000)
    intent: str = Field(default="", max_length=1_000)
    required_evidence: list[str] = Field(min_length=1, max_length=6)
    followup_triggers: list[str] = Field(default_factory=list, max_length=6)
    stop_condition: str = Field(default="", max_length=1_000)


class DrillContractOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    claim_id: int | None = None
    claim_title: str
    question: str
    intent: str
    required_evidence: list[str] = Field(default_factory=list)
    followup_triggers: list[str] = Field(default_factory=list)
    stop_condition: str
    status: str
    evidence_found: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    followup_depth: int
    next_followup_kind: str
    created_at: datetime


class DrillTurnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contract_id: int | None = None
    question: str
    answer: str
    status: str
    feedback: str
    created_at: datetime


class DrillRehearsalItem(BaseModel):
    claim_title: str = ""
    kind: str = "variant"
    why: str = ""


class DrillActionItem(BaseModel):
    claim_title: str = ""
    # 三选一：他确实做过但没整理出细节 / 这块确实不掌握 / 事实站不住要改弱表述。
    kind: str = "补事实"
    detail: str = ""


class DrillReview(BaseModel):
    covered: str = ""
    verified_summary: str = ""
    gaps_summary: str = ""
    actions: list[DrillActionItem] = Field(default_factory=list, max_length=5)
    rehearsal: list[DrillRehearsalItem] = Field(default_factory=list, max_length=MAX_REHEARSAL_ITEMS)


class DrillSessionBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    job_id: int | None = None
    job_title: str
    company: str
    status: str
    feedback_policy: str
    max_questions: int
    current_index: int
    created_at: datetime


class DrillSessionOut(DrillSessionBrief):
    contracts: list[DrillContractOut] = Field(default_factory=list)
    turns: list[DrillTurnOut] = Field(default_factory=list)
    review: dict = Field(default_factory=dict)
    # 服务端算出的计数；界面不用自己去数。
    summary: dict = Field(default_factory=dict)
    # 当前这道题（还没问完时非空），界面据此显示"下一问"。
    pending: DrillContractOut | None = None


class DrillCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=MAX_DRILL_TITLE_CHARS)
    job_id: int | None = Field(default=None, ge=1)
    # 只深挖这几条主张；留空表示全部「已确认」的。
    claim_ids: list[int] = Field(default_factory=list, max_length=MAX_DRILL_CLAIMS)
    max_questions: int = Field(default=DEFAULT_DRILL_QUESTIONS, ge=1, le=MAX_DRILL_QUESTIONS)
    feedback_policy: str = Field(default="deferred", max_length=16)

    @field_validator("feedback_policy")
    @classmethod
    def policy_must_be_known(cls, value: str) -> str:
        from ..models.drill import FEEDBACK_POLICIES

        cleaned = (value or "").strip() or "deferred"
        if cleaned not in FEEDBACK_POLICIES:
            raise ValueError(f"未知的反馈策略「{cleaned}」")
        return cleaned

    @model_validator(mode="after")
    def claim_ids_must_be_unique(self) -> "DrillCreate":
        seen: list[int] = []
        for claim_id in self.claim_ids:
            if claim_id not in seen:
                seen.append(claim_id)
        self.claim_ids = seen
        return self


class DrillAnswerRequest(BaseModel):
    """一轮回答。只收回答本身——状态由服务层按契约判定。"""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(default="", max_length=MAX_DRILL_ANSWER_CHARS)

    @model_validator(mode="after")
    def answer_must_not_be_empty(self) -> "DrillAnswerRequest":
        self.answer = self.answer.strip()
        if not self.answer:
            raise ValueError("请先写下你的回答")
        return self


class DrillAnswerResult(BaseModel):
    """一轮之后返回的东西：判定（训练模式下才展示）+ 下一问（如果有）。"""

    status: str
    evidence_found: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    # 真实模拟模式下为空——每题后念判定会让人按判分标准答题，而不像真面试。
    feedback: str = ""
    finished: bool = False
    session: DrillSessionOut


class DrillRehearseRequest(BaseModel):
    """把复练队列里的一条变成一个可回答的问题（不落库，用户看完就走）。"""

    model_config = ConfigDict(extra="forbid")

    claim_title: str = Field(default="", max_length=200)
    kind: str = Field(default="variant", max_length=24)
    why: str = Field(default="", max_length=600)


class DrillRehearseOut(BaseModel):
    claim_title: str
    kind: str
    question: str
    # 这条题在要求什么，让用户知道该往哪个方向答。
    expect: str = ""


class DrillImportClaimsRequest(BaseModel):
    """从一段材料里整理出可深挖的主张（复用台账草拟）。"""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(default="", max_length=50_000)
    images: list[ExtractionImageInput] = Field(
        default_factory=list, max_length=MAX_EXTRACTION_IMAGE_COUNT
    )
    documents: list[ExtractionDocumentInput] = Field(
        default_factory=list, max_length=MAX_EXTRACTION_DOCUMENT_COUNT
    )


__all__ = [
    "DEFAULT_DRILL_QUESTIONS",
    "DrillActionItem",
    "DrillAnswerRequest",
    "DrillAnswerResult",
    "DrillContractOut",
    "DrillCreate",
    "DrillPlan",
    "DrillRehearsalItem",
    "DrillRehearseOut",
    "DrillRehearseRequest",
    "DrillReview",
    "DrillSessionBrief",
    "DrillSessionOut",
    "DrillTurnOut",
    "MAX_DRILL_QUESTIONS",
]

