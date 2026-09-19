"""面试复盘的保存历史（D5）。

面试复盘本体是「录入真实被问问题 → 分析答题思路 → 反向优化简历」的即时流程
（``services/interview_questions.analyze_question`` / ``optimize_resume``），不落库。用户想
**回看某一次复盘**时，把「问题清单 + 分析结果 + 反向优化建议」落成一条历史记录。

设计要点：

- **岗位/简历被删不连坐**：``job_id``/``resume_id`` 外键 ``SET NULL``；``job_title``/
  ``company``/``resume_title`` 是快照，删了源头记录仍可读。
- **``questions`` 是真实问题清单**（JSON list of str），``analysis`` 是答题思路（JSON object），
  ``suggestions`` 是反向优化建议（JSON list）。
- **软删除**：删除走 ``services/trash.soft_delete``，列表查询复用 ``trash.live_only``。
"""
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .profile import utcnow


class InterviewReviewRecord(Base):
    """一次被保存的面试复盘。"""

    __tablename__ = "interview_review_record"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_title: Mapped[str] = mapped_column(String(128), default="")
    company: Mapped[str] = mapped_column(String(128), default="")
    resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resume_record.id", ondelete="SET NULL"), nullable=True
    )
    resume_title: Mapped[str] = mapped_column(String(256), default="")
    # 真实被问的问题清单：["这个项目难点怎么解决？", ...]
    questions: Mapped[list[str]] = mapped_column(JSON, default=list)
    # 答题思路：{"framework","key_points","follow_up","pitfalls"}
    analysis: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # 反向优化建议：[{"priority","section","issue","suggestion","evidence"}]
    suggestions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(64), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    # 软删除时间戳：NULL 表示「没删」。列表查询一律复用 ``services/trash.live_only``。
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


__all__ = ["InterviewReviewRecord"]
