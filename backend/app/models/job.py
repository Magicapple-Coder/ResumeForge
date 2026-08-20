"""岗位模型：保存手动录入或从粘贴文本解析后确认的岗位。"""
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .profile import utcnow

# 岗位状态的可选值
JOB_STATUS_OPEN = "开放中"
JOB_STATUS_CLOSED = "已截止"
JOB_STATUS_APPLIED = "已投递"
JOB_STATUSES = (JOB_STATUS_OPEN, JOB_STATUS_CLOSED, JOB_STATUS_APPLIED)


class Job(Base):
    __tablename__ = "job"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(128))
    company: Mapped[str] = mapped_column(String(128), default="")
    location: Mapped[str] = mapped_column(String(64), default="")
    salary: Mapped[str] = mapped_column(String(64), default="")
    job_type: Mapped[str] = mapped_column(String(32), default="校招")  # 校招/实习/社招/其他
    description: Mapped[str] = mapped_column(Text, default="")  # JD 全文
    requirements: Mapped[str] = mapped_column(Text, default="")  # 任职要求（可选）
    additional_info: Mapped[str] = mapped_column(Text, default="")  # 福利、流程等招聘补充信息
    # 规则解析出的技能标签：[{"name": "Python", "category": "编程语言"}, ...]
    keywords: Mapped[list[Any]] = mapped_column(JSON, default=list)
    # 保留该列以兼容历史数据；新岗位只会由手动添加接口写入默认值。
    source: Mapped[str] = mapped_column(String(64), default="手动添加")
    source_url: Mapped[str] = mapped_column(String(512), default="")  # 投递链接
    posted_at: Mapped[str] = mapped_column(String(32), default="")  # 发布时间的原始文本
    status: Mapped[str] = mapped_column(String(16), default=JOB_STATUS_OPEN, index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
