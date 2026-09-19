"""岗位模型：保存手动录入或从粘贴文本解析后确认的岗位。"""
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, String, Text
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
    # 备注里的图片（受限的 base64 data URL 列表）：招聘截图、内推码截图等。
    note_images: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 招聘信息的录入方式，用于方便用户溯源：手动填写 / 粘贴文本识别 / 图片识别 /
    # 文档识别 / 备选岗位导入。旧数据为空字符串，界面按"未记录"处理。
    recognition_source: Mapped[str] = mapped_column(String(32), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    # 软删除时间戳：NULL 表示「没删」。列表查询一律加 `deleted_at IS NULL`，
    # 回收站里则只看非 NULL 的行（见 ``services/trash.py``）。
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
