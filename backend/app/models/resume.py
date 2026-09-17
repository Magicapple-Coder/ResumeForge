"""简历生成记录模型：每次生成都落库，支持历史查看与导出。"""
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .profile import utcnow


class ResumeRecord(Base):
    __tablename__ = "resume_record"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(256), default="")
    # 目标岗位（快照保存，岗位被删除后记录仍完整可用）
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_title: Mapped[str] = mapped_column(String(128), default="")
    company: Mapped[str] = mapped_column(String(128), default="")
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # 结构化简历
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)  # 一致性校验提醒
    # 历史记录没有该字段时由 SQLite 迁移默认标记为 AI 生成。
    source: Mapped[str] = mapped_column(String(16), default="ai", nullable=False)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    model: Mapped[str] = mapped_column(String(64), default="")
    # 旧数据库中的 tone 列为 NOT NULL 且没有服务端默认值。继续写入默认值仅为
    # 兼容历史表结构；API 和前端均不再暴露定制风格功能。
    tone: Mapped[str] = mapped_column(String(32), default="standard")
    enhancement_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    enhancement_level: Mapped[str] = mapped_column(String(16), default="balanced")
    # 生成时选择的版式参数：重新预览/导出时按同一套参数渲染，改参数不必重新生成。
    template: Mapped[str] = mapped_column(String(32), default="classic", server_default="classic")
    # 格式模板：一组版式覆盖的名字（内置预设名或用户自制格式模板名）；空串表示用样式
    # 模板自带的版式。
    format_name: Mapped[str] = mapped_column(String(64), default="", server_default="")
    page_limit: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    font_scale: Mapped[str] = mapped_column(
        String(16), default="standard", server_default="standard"
    )
    # 用户补充的生成要求原文，留痕以便查看和重新生成。
    custom_instruction: Mapped[str] = mapped_column(Text, default="", server_default="")
    parse_error: Mapped[str] = mapped_column(Text, default="")  # JSON 解析失败时留痕
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
