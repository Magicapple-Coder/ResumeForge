"""模拟面试官：一次面试会话与其中的问答记录。

与求职助手的分工：助手是"随问随答的顾问"，模拟面试是**有固定流程的角色扮演**——
面试官按设定的类型、难度、风格和轮数推进，结束后给出一份评分报告。因此单独建表，
而不是塞进 chat_conversation：两者的生命周期和字段都不一样。
"""
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .profile import utcnow

# 面试类型：覆盖校招/社招常见形式，前端按这个清单给选项。
INTERVIEW_TYPES = (
    "技术面",
    "项目深挖",
    "行为面（STAR）",
    "HR 面",
    "综合面",
    "案例分析",
    "英语面试",
    "压力面",
)

INTERVIEW_DIFFICULTIES = ("初级", "中级", "高级")

# 面试官风格：影响提问语气与追问强度。
INTERVIEWER_STYLES = (
    "严谨专业",
    "温和引导",
    "持续追问",
    "压力质询",
)

INTERVIEW_STATUS_ACTIVE = "active"
INTERVIEW_STATUS_FINISHED = "finished"


class InterviewSession(Base):
    __tablename__ = "interview_session"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(128), default="")
    # 目标岗位（快照保存：岗位被删除后这场面试仍然可用）
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_title: Mapped[str] = mapped_column(String(128), default="")
    company: Mapped[str] = mapped_column(String(128), default="")
    interview_type: Mapped[str] = mapped_column(String(32), default="技术面")
    difficulty: Mapped[str] = mapped_column(String(16), default="中级")
    interviewer_style: Mapped[str] = mapped_column(String(32), default="严谨专业")
    # 计划轮数：面试官问答满这些轮次后收尾并出报告。
    rounds: Mapped[int] = mapped_column(Integer, default=6)
    # 用户自定义的面试官人设与考察重点（会拼进系统提示）。
    persona: Mapped[str] = mapped_column(Text, default="")
    focus: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(16), default=INTERVIEW_STATUS_ACTIVE, index=True)
    # 结束时的评分报告：{"score": 78, "dimensions": [...], "strengths": [...], "improvements": [...], "summary": "..."}
    report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    model: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    messages: Mapped[list["InterviewMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="InterviewMessage.id",
    )


class InterviewMessage(Base):
    __tablename__ = "interview_message"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("interview_session.id", ondelete="CASCADE"), index=True
    )
    # interviewer：面试官提问；user：候选人回答；note：系统提示（如"第 3/6 题"）
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="complete")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    session: Mapped[InterviewSession] = relationship(back_populates="messages")
