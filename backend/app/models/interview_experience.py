"""面经知识库：把"这家公司这道题问了什么、怎么答"沉淀成可检索的条目。

与模拟面试（``interview`` 模块）的区别：模拟面试是**对话式练习**，本表是**他人或自己的
真实面经**——正文 + 被问到的真实问题清单 + 标签。来源三类：自己（``self``）、同行
（``peer``）、公开渠道（``public``），只做分类不做断言，来源可信度由用户自己判断。

设计要点：

- **岗位被删不连坐**：``job_id`` 用 ``SET NULL``；``company``/``position`` 本身就是快照，
  删岗位后面经仍可读、仍能按公司名检索。
- **``questions`` 是真实问题清单**（JSON list），与 R-11 题库"即时生成、不落库"互补：
  题库不持久化，但用户录进来的真实问题落到这里。
- **``round_type`` 用自由字符串 + 白名单参考**（一面/二面/HR 面/笔试…）：状态枚举不该为
  了"第几轮"无限膨胀，具体轮次与叫法由用户填，常量只提供常见取值供前端下拉。
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .profile import utcnow

# ===== 面经来源（前后端共用一份取值）=====
EXPERIENCE_SOURCE_SELF = "self"
EXPERIENCE_SOURCE_PEER = "peer"
EXPERIENCE_SOURCE_PUBLIC = "public"
EXPERIENCE_SOURCES = (
    EXPERIENCE_SOURCE_SELF,
    EXPERIENCE_SOURCE_PEER,
    EXPERIENCE_SOURCE_PUBLIC,
)

# ===== 常见面试轮次（供前端下拉的白名单参考，存储仍是自由字符串）=====
EXPERIENCE_ROUND_TYPES = ("一面", "二面", "三面", "HR面", "笔试", "其他")


class InterviewExperience(Base):
    """一条面经。"""

    __tablename__ = "interview_experience"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    company: Mapped[str] = mapped_column(String(128), default="", index=True)
    position: Mapped[str] = mapped_column(String(128), default="")
    # 绑定岗位：删除后置空，公司/岗位快照字段仍保留。
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), nullable=True, index=True
    )
    content: Mapped[str] = mapped_column(Text, default="")
    # 被问到的真实问题清单（R-11 录入）。
    questions: Mapped[list[str]] = mapped_column(JSON, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(16), default=EXPERIENCE_SOURCE_SELF)
    difficulty: Mapped[str] = mapped_column(String(16), default="")
    # 面试轮次：自由字符串，参考白名单见 EXPERIENCE_ROUND_TYPES。
    round_type: Mapped[str] = mapped_column(String(32), default="")
    # YYYY-MM-DD；未知为空串。
    interview_date: Mapped[str] = mapped_column(String(10), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    # 软删除时间戳：NULL 表示「没删」。列表查询一律复用 ``services/trash.live_only``。
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


__all__ = [
    "EXPERIENCE_ROUND_TYPES",
    "EXPERIENCE_SOURCES",
    "EXPERIENCE_SOURCE_PEER",
    "EXPERIENCE_SOURCE_PUBLIC",
    "EXPERIENCE_SOURCE_SELF",
    "InterviewExperience",
]
