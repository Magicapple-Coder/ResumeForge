"""日历提醒：把"什么时候该做什么"从人脑里搬到本地日程。

提醒不自己发明时机，只记录用户或流程**明确给出**的时点（面试时间、测评截止、该催 HR 回复了）。
它同时绑定三个可选对象——求职进度（``application_track``）、岗位（``job``）、简历版本
（``resume_record``），但三者都可空：一条"周日整理简历"的提醒不绑定任何漏斗，一条
"跟进某岗位"的提醒只绑岗位。绑定用 ``SET NULL``：被绑对象删除后提醒仍保留，只是失去关联。

设计要点：

- **``kind`` 四类**（interview/assessment_deadline/hr_reply/other）：决定提醒在界面上怎么
  归类展示，不决定提醒内容本身。
- **``status`` 三态**（pending/done/dismissed）：只回答"待办 / 已完成 / 已忽略"，不含
  复杂的调度状态机——调度留给 P3 的服务层，表里只存结果。
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .profile import utcnow

# ===== 提醒种类（前后端共用一份取值）=====
REMINDER_KIND_INTERVIEW = "interview"
REMINDER_KIND_ASSESSMENT_DEADLINE = "assessment_deadline"
REMINDER_KIND_HR_REPLY = "hr_reply"
REMINDER_KIND_OTHER = "other"
REMINDER_KINDS = (
    REMINDER_KIND_INTERVIEW,
    REMINDER_KIND_ASSESSMENT_DEADLINE,
    REMINDER_KIND_HR_REPLY,
    REMINDER_KIND_OTHER,
)

# ===== 提醒状态 =====
REMINDER_STATUS_PENDING = "pending"
REMINDER_STATUS_DONE = "done"
REMINDER_STATUS_DISMISSED = "dismissed"
REMINDER_STATUSES = (
    REMINDER_STATUS_PENDING,
    REMINDER_STATUS_DONE,
    REMINDER_STATUS_DISMISSED,
)


class Reminder(Base):
    """一条日历提醒。"""

    __tablename__ = "reminder"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    # 提醒时间：提醒的唯一权威时点，列表按它升序排"接下来要做什么"。
    remind_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    kind: Mapped[str] = mapped_column(String(32), default=REMINDER_KIND_OTHER)
    status: Mapped[str] = mapped_column(String(16), default=REMINDER_STATUS_PENDING, index=True)
    # 三个可选绑定对象，均为 SET NULL：被绑对象删除后提醒仍保留。
    track_id: Mapped[int | None] = mapped_column(
        ForeignKey("application_track.id", ondelete="SET NULL"), nullable=True
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), nullable=True, index=True
    )
    resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resume_record.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    # 软删除时间戳：NULL 表示「没删」。列表查询一律复用 ``services/trash.live_only``。
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


__all__ = [
    "REMINDER_KINDS",
    "REMINDER_KIND_ASSESSMENT_DEADLINE",
    "REMINDER_KIND_HR_REPLY",
    "REMINDER_KIND_INTERVIEW",
    "REMINDER_KIND_OTHER",
    "REMINDER_STATUSES",
    "REMINDER_STATUS_DISMISSED",
    "REMINDER_STATUS_DONE",
    "REMINDER_STATUS_PENDING",
    "Reminder",
]
