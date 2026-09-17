"""按事实台账深挖的面试会话：一条主张一个考察契约，逐轮验证。

与「模拟面试」的分工：模拟面试是**有固定流程的角色扮演**（设定面试官，按轮数推进，
结束时给一份四维度评分报告）；本模块是**针对你自己写下的主张逐条压力测试**——
它不评总分，而是回答"这条主张我到底讲不讲得清、哪里还站不住"。

三个刻意的设计：

- **提问前先锁定评分契约**（:class:`DrillContract`）。契约里写明这道题要验证什么、
  必须听到哪些证据、什么情况该追问、什么情况可以结束。**契约在看到回答之前就定下来**，
  之后不因回答得好听而放宽——这是防"事后改标准"的唯一办法，也是本模块与"给个分数"
  最根本的区别。
- **用证据状态代替分数**：``已验证 / 部分验证 / 未验证 / 存在矛盾 / 未覆盖``。
  一个 0-100 的分数在这种场景里是伪精确——它无法回答"我该去补什么"。
- **不做推断**：模型只能依据用户**真实说过的内容**给状态，没有新证据就不能升级
  （:func:`should_promote` 单独实现并被测试钉住）。
"""
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .profile import utcnow

# ===== ① 证据状态：本条主张在当前会话里被验证到什么程度 =====
EVIDENCE_VERIFIED = "verified"
EVIDENCE_PARTIAL = "partial"
EVIDENCE_UNVERIFIED = "unverified"
EVIDENCE_CONTRADICTORY = "contradictory"
EVIDENCE_NOT_COVERED = "not_covered"

EVIDENCE_STATUSES = (
    EVIDENCE_VERIFIED,
    EVIDENCE_PARTIAL,
    EVIDENCE_UNVERIFIED,
    EVIDENCE_CONTRADICTORY,
    EVIDENCE_NOT_COVERED,
)

EVIDENCE_LABELS = {
    EVIDENCE_VERIFIED: "已验证：必要证据都讲到了",
    EVIDENCE_PARTIAL: "部分验证：讲到了一部分，还有明确缺口",
    EVIDENCE_UNVERIFIED: "未验证：没能提供最低限度的事实",
    EVIDENCE_CONTRADICTORY: "存在矛盾：与台账或前文对不上",
    EVIDENCE_NOT_COVERED: "未覆盖：这一轮没问到",
}

# 只有这三种需要复练——已验证的不必再练，未覆盖的只是没轮到。
REHEARSE_STATUSES = (EVIDENCE_PARTIAL, EVIDENCE_UNVERIFIED, EVIDENCE_CONTRADICTORY)

# ===== ② 会话状态 =====
DRILL_STATUS_ACTIVE = "active"
DRILL_STATUS_FINISHED = "finished"

# ===== ③ 反馈策略：真实模拟与训练模式的分野 =====
# 真实模拟默认**不在每题后**把判定念给用户（那会让人按判分标准答题，而不是像真面试）；
# 训练模式则每题后立刻给一段简短反馈。
FEEDBACK_DEFERRED = "deferred"
FEEDBACK_IMMEDIATE = "immediate"
FEEDBACK_POLICIES = (FEEDBACK_DEFERRED, FEEDBACK_IMMEDIATE)

# 追问问题的类型：按需选择，不机械遍历。
FOLLOWUP_KINDS = (
    "background",  # 背景：为什么需要它
    "responsibility",  # 职责：本人具体负责什么
    "structure",  # 结构：组件、数据流和边界
    "implementation",  # 实现：关键代码或流程怎么工作
    "decision",  # 决策：为什么这么选
    "alternative",  # 替代：为什么不用另一种方案
    "failure",  # 失败：出过什么问题、如何复现和修复
    "metric",  # 指标：基线、样本、周期和测量方式
    "cost",  # 代价：方案牺牲了什么
    "retrospective",  # 复盘：重新做会改变什么
)

FOLLOWUP_LABELS = {
    "background": "背景",
    "responsibility": "职责",
    "structure": "结构",
    "implementation": "实现",
    "decision": "决策",
    "alternative": "替代方案",
    "failure": "失败与排查",
    "metric": "指标口径",
    "cost": "代价",
    "retrospective": "复盘",
}

# ===== ④ 复练题型：不原题重复，换一个角度再问 =====
REHEARSE_VARIANT = "variant"
REHEARSE_COUNTERFACTUAL = "counterfactual"
REHEARSE_FAILURE = "failure"
REHEARSE_EVIDENCE = "evidence"
REHEARSE_COMPRESS = "compress"

REHEARSE_KINDS = (
    REHEARSE_VARIANT,
    REHEARSE_COUNTERFACTUAL,
    REHEARSE_FAILURE,
    REHEARSE_EVIDENCE,
    REHEARSE_COMPRESS,
)

REHEARSE_LABELS = {
    REHEARSE_VARIANT: "变体题：换一个输入或限制",
    REHEARSE_COUNTERFACTUAL: "反事实题：条件变了方案还成立吗",
    REHEARSE_FAILURE: "故障题：给一个异常现象，要求定位",
    REHEARSE_EVIDENCE: "证据题：说明代码、数据、日志或统计口径",
    REHEARSE_COMPRESS: "压缩表达：60 秒内讲清同一条主张",
}


def evidence_label(status: str) -> str:
    """面向用户的证据状态说明；未知取值给出中性描述，不猜成"已验证"。"""
    return EVIDENCE_LABELS.get(status, "状态未知")


def needs_rehearsal(status: str) -> bool:
    """这条主张是否需要进复练队列。"""
    return status in REHEARSE_STATUSES


def should_promote(previous: str, incoming: str) -> bool:
    """状态能否从 ``previous`` 变成 ``incoming``。

    **只有拿到新证据才算"更好了"**。这条规则单独成函数是因为它最容易在实现里被绕过：
    "用户这次答得比上次流利"看起来像进步，但如果他没说出任何新事实，状态就不该升级——
    把"背出了上次的建议"当成"已经掌握"，会让复练队列失去意义。

    取值语义：
    - ``not_covered`` 是**起点**（这道题还没判过），不是一种结论。所以从它出发的任何
      明确判定都成立；但反过来**不能升级到它**——那等于把已经判过的结论抹掉。
    - ``contradictory`` 是决定性的：任何时候都可以标记，包括把已验证打回原形；
      而从矛盾中恢复也是一次真实的判定。
    - 同一状态之间不算变化。
    """
    if incoming == EVIDENCE_NOT_COVERED:
        return False
    if previous == incoming:
        return False
    rank = {
        EVIDENCE_UNVERIFIED: 0,
        EVIDENCE_PARTIAL: 1,
        EVIDENCE_VERIFIED: 2,
    }
    # 矛盾是决定性的：任何时候都能标记，也能从它恢复。
    if incoming == EVIDENCE_CONTRADICTORY:
        return True
    # 这道题还没判过 → 第一次判定直接成立。
    if previous == EVIDENCE_NOT_COVERED:
        return incoming in rank
    # 当前处在矛盾状态 → 任何明确结论都算一次新的判定。
    if previous == EVIDENCE_CONTRADICTORY:
        return incoming in rank
    if incoming not in rank or previous not in rank:
        return False
    return rank[incoming] > rank[previous]


class DrillContract(Base):
    """一道深挖题的**评分契约**：提问之前就定下来，看到回答之后不许改。"""

    __tablename__ = "drill_contract"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("drill_session.id", ondelete="CASCADE"), index=True
    )
    # 这条契约在验证哪一条台账主张。主张被删掉后契约仍要可读（SET NULL + 快照）。
    claim_id: Mapped[int | None] = mapped_column(
        ForeignKey("claim_record.id", ondelete="SET NULL"), nullable=True, index=True
    )
    claim_title: Mapped[str] = mapped_column(String(200), default="")

    question: Mapped[str] = mapped_column(Text, default="")
    # 这道题想验证什么（意图）。
    intent: Mapped[str] = mapped_column(Text, default="")
    # 必须听到哪些证据才算过：字符串数组。
    required_evidence: Mapped[list[str]] = mapped_column(JSON, default=list)
    # 出现这些情况就该追问。
    followup_triggers: Mapped[list[str]] = mapped_column(JSON, default=list)
    # 什么情况下这道题可以结束。
    stop_condition: Mapped[str] = mapped_column(Text, default="")

    # 判定结果（回答之后填入）。
    status: Mapped[str] = mapped_column(String(24), default=EVIDENCE_NOT_COVERED, index=True)
    # 已经讲到的证据 / 仍然缺的 / 发现的矛盾。
    evidence_found: Mapped[list[str]] = mapped_column(JSON, default=list)
    missing: Mapped[list[str]] = mapped_column(JSON, default=list)
    contradictions: Mapped[list[str]] = mapped_column(JSON, default=list)
    # 这道题已经追问到第几层。
    followup_depth: Mapped[int] = mapped_column(Integer, default=0)
    # 下一道题该问哪一类（取自 FOLLOWUP_KINDS），用于复练时换个角度。
    next_followup_kind: Mapped[str] = mapped_column(String(24), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class DrillSession(Base):
    """一次按台账深挖的面试会话。"""

    __tablename__ = "drill_session"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(128), default="")
    # 关联岗位（可选，快照保存）。
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), nullable=True
    )
    job_title: Mapped[str] = mapped_column(String(128), default="")
    company: Mapped[str] = mapped_column(String(128), default="")

    status: Mapped[str] = mapped_column(String(16), default=DRILL_STATUS_ACTIVE, index=True)
    feedback_policy: Mapped[str] = mapped_column(String(16), default=FEEDBACK_DEFERRED)
    # 这次要深挖哪些主张（id 列表）；空表示全部已确认的。
    claim_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    # 最多问几道题（每道题含追问）。
    max_questions: Mapped[int] = mapped_column(Integer, default=6)
    current_index: Mapped[int] = mapped_column(Integer, default=0)

    # 结束时的复盘结论（段落文本），以及复练队列。
    review: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    contracts: Mapped[list["DrillContract"]] = relationship(
        cascade="all, delete-orphan", order_by="DrillContract.id"
    )
    turns: Mapped[list["DrillTurn"]] = relationship(
        cascade="all, delete-orphan", order_by="DrillTurn.id"
    )


class DrillTurn(Base):
    """一轮问答：被回答的问题、用户的回答、这一轮的判定，以及下一问。

    "下一问"也记在**这一轮**上（而不是只更新契约），复盘才能按时间顺序还原整场对话；
    只留契约的话，追问的原文就只剩最后一次了。
    """

    __tablename__ = "drill_turn"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("drill_session.id", ondelete="CASCADE"), index=True
    )
    contract_id: Mapped[int | None] = mapped_column(
        ForeignKey("drill_contract.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # 面试官说的话：追问的问题，或（训练模式下）对上一答的简短反馈。
    question: Mapped[str] = mapped_column(Text, default="")
    answer: Mapped[str] = mapped_column(Text, default="")
    # 这一轮之后的证据状态（每轮更新一次契约上的结论，这里留痕便于复盘）。
    status: Mapped[str] = mapped_column(String(24), default="")
    feedback: Mapped[str] = mapped_column(Text, default="")
    # 判定之后要追问的下一个问题；空串表示这道题问完了。
    next_question: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


__all__ = [
    "DRILL_STATUS_ACTIVE",
    "DRILL_STATUS_FINISHED",
    "DrillContract",
    "DrillSession",
    "DrillTurn",
    "EVIDENCE_CONTRADICTORY",
    "EVIDENCE_LABELS",
    "EVIDENCE_NOT_COVERED",
    "EVIDENCE_PARTIAL",
    "EVIDENCE_STATUSES",
    "EVIDENCE_UNVERIFIED",
    "EVIDENCE_VERIFIED",
    "FEEDBACK_DEFERRED",
    "FEEDBACK_IMMEDIATE",
    "FEEDBACK_POLICIES",
    "FOLLOWUP_KINDS",
    "FOLLOWUP_LABELS",
    "REHEARSE_COUNTERFACTUAL",
    "REHEARSE_EVIDENCE",
    "REHEARSE_FAILURE",
    "REHEARSE_KINDS",
    "REHEARSE_LABELS",
    "REHEARSE_STATUSES",
    "REHEARSE_VARIANT",
    "evidence_label",
    "needs_rehearsal",
    "should_promote",
]
