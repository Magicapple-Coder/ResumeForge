"""岗位匹配度分析的数据结构。

两条硬约束：

1. **五类状态取值用 ``Literal`` 硬锁**（与 ``models/apply`` 里的常量逐字一致）。
2. **禁止任何百分比 / 评分字段**：所有模型都设 ``extra="forbid"``，模型若吐出 ``score``
   或 ``percent`` 之类的字段会在校验阶段直接被拒，而不是悄悄渲染成一个数字给用户。
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 单条匹配结论的状态（五类）。
MatchStatus = Literal[
    "matched",
    "expression_gap",
    "evidence_insufficient",
    "real_gap",
    "to_confirm",
]
HardGateResult = Literal["met", "unmet", "unknown"]
AdmissionResult = Literal["allow", "block", "needs_confirm"]

MAX_QUOTE_CHARS = 2000
MAX_EVIDENCE_CHARS = 2000
MAX_ADVICE_CHARS = 2000
MAX_NOTE_CHARS = 500


class MatchCondition(BaseModel):
    """一条匹配项：JD 原文摘录 + 匹配状态 + 证据。

    ``jd_quote`` 与 ``evidence`` 都必须能在来源（JD / 资料 / 简历）里找到，防止模型
    凭空编造。"证据不足"时 ``evidence`` 写"资料中未提供"。
    """

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=255)
    jd_quote: str = Field(default="", max_length=MAX_QUOTE_CHARS)
    status: MatchStatus
    evidence: str = Field(default="", max_length=MAX_EVIDENCE_CHARS)


class JobMatchResult(BaseModel):
    """岗位匹配度分析的完整结论（也直接落进 ``job_match_analysis.result``）。"""

    model_config = ConfigDict(extra="forbid")

    hard_conditions: list[MatchCondition] = Field(default_factory=list)
    core_abilities: list[MatchCondition] = Field(default_factory=list)
    bonus_items: list[MatchCondition] = Field(default_factory=list)
    # 硬性门槛总体结论：任一硬性条件命中 real_gap → unmet。
    hard_gate: HardGateResult = "unknown"
    # 由 admission_of() 逐项映射后取最保守的结论得出（allow / block / needs_confirm）。
    admission: AdmissionResult = "needs_confirm"
    advice: str = Field(default="", max_length=MAX_ADVICE_CHARS)
    notes: list[str] = Field(default_factory=list, max_length=20)


class JobMatchOut(BaseModel):
    """落库后的匹配结论（GET /api/jobs/{id}/match-analysis 的响应）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int | None = None
    job_title: str = ""
    company: str = ""
    result: JobMatchResult = Field(default_factory=JobMatchResult)
    hard_gate: HardGateResult = "unknown"
    requires_confirm: bool = False
    model: str = ""
    created_at: datetime
    updated_at: datetime


__all__ = [
    "AdmissionResult",
    "HardGateResult",
    "JobMatchOut",
    "JobMatchResult",
    "MatchCondition",
    "MatchStatus",
]
