"""个性化题库的保存历史（D5）。

题库本体是「即时生成、不落库」的（``services/interview/interview_questions.generate_question_bank``），
但用户可能想**回看某一次生成的题目**——这里把生成结果落成一条历史记录，供「历史题库」回看
与删除。与题库生成本身解耦：生成不自动存，用户点「保存题库」才存。

设计要点：

- **岗位/简历被删不连坐**：``job_id``/``resume_id`` 外键 ``SET NULL``；``job_title``/
  ``company``/``resume_title`` 是快照，删了源头记录仍可读。
- **``groups`` 是那次生成的三类题分组**（JSON list），与 ``QuestionBankGroup`` 结构一致。
- **软删除**：删除走 ``services/trash.soft_delete``，列表查询复用 ``trash.live_only``。
"""
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .profile import utcnow


class QuestionBankRecord(Base):
    """一次被保存的题库生成结果。"""

    __tablename__ = "question_bank_record"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 关联岗位与简历：删除后置空，快照字段仍保留。
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_title: Mapped[str] = mapped_column(String(128), default="")
    company: Mapped[str] = mapped_column(String(128), default="")
    resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resume_record.id", ondelete="SET NULL"), nullable=True
    )
    resume_title: Mapped[str] = mapped_column(String(256), default="")
    # 三类题分组：[{"type": "基础题", "questions": [{"question","purpose","answer_hint"}]}]
    groups: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # 生成时使用的模型名（来自「设置」中的配置）。
    model: Mapped[str] = mapped_column(String(64), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    # 软删除时间戳：NULL 表示「没删」。列表查询一律复用 ``services/trash.live_only``。
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


__all__ = ["QuestionBankRecord"]
