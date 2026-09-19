"""知识库条目（第 7 批业务代码的地基）。

第 5 批只建表 + 注册进 ``Base.metadata``，**不实现增删改查业务代码**——那部分属于后续批。
这里先把结构与软删除语义定下来：标题、分类、标签、正文、来源，全部带 ``deleted_at`` 软删除
（进回收站），列表查询届时统一复用 ``services/trash.live_only``。
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .profile import utcnow


class KnowledgeEntry(Base):
    """一条知识库条目。"""

    __tablename__ = "knowledge_entry"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    category: Mapped[str] = mapped_column(String(32), default="", index=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    content: Mapped[str] = mapped_column(Text, default="")
    # 来源（如「手动录入」「面经导入」等，第 7 批定义白名单）。
    source: Mapped[str] = mapped_column(String(64), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    # 软删除时间戳：NULL 表示「没删」。列表查询一律复用 ``services/trash.live_only``。
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


__all__ = ["KnowledgeEntry"]
