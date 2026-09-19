"""运行时配置模型：当前配置与可切换的大模型配置记录。"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .profile import utcnow


class AppSetting(Base):
    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")  # JSON 序列化后的字符串


class LLMConfigRecord(Base):
    """用户命名保存的 LLM 配置；同名保存时由服务层更新原记录。"""

    __tablename__ = "llm_config_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    provider: Mapped[str] = mapped_column(String(32), default="custom")
    base_url: Mapped[str] = mapped_column(String(512), default="")
    api_key: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    temperature: Mapped[float] = mapped_column(Float, default=0.1)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=120)
    # 0 = 不限制（与 schemas.setting.UNLIMITED_MAX_TOKENS 一致）。服务层保存记录时总是从
    # Pydantic 模型显式带入该字段，这里的默认值只在直接构造 ORM 行时兜底，保持一致即可。
    max_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # 接口协议：openai = Chat Completions 兼容；anthropic = Claude Messages 原生。
    api_style: Mapped[str] = mapped_column(String(16), default="openai", server_default="openai")
    # 高级调整（可选）：为空表示不发送该字段，沿用服务商默认值。
    top_p: Mapped[float | None] = mapped_column(Float, nullable=True)
    frequency_penalty: Mapped[float | None] = mapped_column(Float, nullable=True)
    presence_penalty: Mapped[float | None] = mapped_column(Float, nullable=True)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    top_k: Mapped[int | None] = mapped_column(Integer, nullable=True)
    repetition_penalty: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 停止词（最多 4 条）与 Anthropic 扩展思考预算。
    stop: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    thinking_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 额外的请求体字段（原样合并，白名单过滤后生效），给长尾参数留出口。
    extra_body: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
