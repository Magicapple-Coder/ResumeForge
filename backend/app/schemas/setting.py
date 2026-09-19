"""设置 Schema：当前大模型配置、配置记录与联网搜索设置。"""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# max_tokens 取该值时表示“不限制”：请求体里省略该字段，由服务商/模型决定上限。
# 发送 0 或 -1 在部分服务商上会被当作非法参数拒绝，所以用省略而非哨兵数值。
UNLIMITED_MAX_TOKENS = 0
MIN_MAX_TOKENS = 256

# 接口协议：openai = Chat Completions 兼容（默认），anthropic = Claude Messages 原生。
API_STYLES = ("openai", "anthropic")

# 这些键由 provider 自己填写，用户不该通过 extra_body 覆盖它们。
RESERVED_EXTRA_BODY_KEYS = frozenset(
    {"model", "messages", "stream", "tools", "tool_choice", "system"}
)


class LLMConfig(BaseModel):
    """兼容 OpenAI Chat Completions 协议的模型配置（DeepSeek/豆包/Kimi/Ollama 等）。"""

    provider: str = Field(default="custom", max_length=32)  # 预设标识，仅用于前端展示
    base_url: str = Field(default="", max_length=512)
    api_key: str = Field(default="", max_length=8192)
    model: str = Field(default="", max_length=128)
    # 简历生成更看重事实稳定性；用户仍可按需调高创意度。
    temperature: float = Field(default=0.1, ge=0, le=2)
    timeout_seconds: int = Field(default=120, ge=10, le=600)
    # 默认「不限制」：新用户不调参也能用服务商/模型的默认上限，而不是被一个手写的
    # 4096 悄悄截断。这只影响**默认值**——已保存过 max_tokens 的配置原样保留，
    # 不会因为一次升级就被改写（改动存量等于替用户改他未必想改的东西）。
    max_tokens: int = Field(default=UNLIMITED_MAX_TOKENS, ge=UNLIMITED_MAX_TOKENS, le=65536)
    # 接口协议。Claude 既能用官方的 OpenAI 兼容层（选 openai），也能走原生 Messages
    # 协议（选 anthropic，支持扩展思考与独立的 system 字段）。
    api_style: Literal["openai", "anthropic"] = "openai"
    # 高级调整（可选）：None 表示请求体里不发送该字段，沿用服务商默认值。
    # 这些参数各家支持度不一，所以默认全部关闭，由用户在设置页显式开启。
    top_p: float | None = Field(default=None, ge=0, le=1)
    frequency_penalty: float | None = Field(default=None, ge=-2, le=2)
    presence_penalty: float | None = Field(default=None, ge=-2, le=2)
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)
    top_k: int | None = Field(default=None, ge=0, le=1000)
    repetition_penalty: float | None = Field(default=None, ge=0, le=2)
    # 停止词：命中即让模型停下（最多 4 条，避免服务商直接拒绝整次请求）。
    stop: list[str] = Field(default_factory=list, max_length=4)
    # Anthropic 扩展思考预算（tokens）；0 表示明确关闭，None 表示不发送该字段。
    thinking_budget: int | None = Field(default=None, ge=0, le=100_000)
    # 额外的请求体字段：长尾参数的出口（各家自创参数太多，逐个加字段不现实）。
    extra_body: dict[str, Any] = Field(default_factory=dict)

    @field_validator("stop")
    @classmethod
    def stop_must_be_short_strings(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            text = str(item).strip()
            if not text:
                continue
            if len(text) > 64:
                raise ValueError("停止词不能超过 64 个字符")
            cleaned.append(text)
        return cleaned

    @field_validator("extra_body")
    @classmethod
    def extra_body_must_not_override_protocol(cls, value: dict[str, Any]) -> dict[str, Any]:
        reserved = sorted(set(value) & RESERVED_EXTRA_BODY_KEYS)
        if reserved:
            raise ValueError(f"额外请求体不能覆盖这些字段：{'、'.join(reserved)}")
        if len(value) > 20:
            raise ValueError("额外请求体最多 20 个字段")
        return value

    @field_validator("max_tokens")
    @classmethod
    def max_tokens_must_be_unlimited_or_usable(cls, value: int) -> int:
        # ge=UNLIMITED_MAX_TOKENS 会顺带放行 1..255，这里把下界补回来。
        if value != UNLIMITED_MAX_TOKENS and value < MIN_MAX_TOKENS:
            raise ValueError(
                f"最大输出 Token 需为 {UNLIMITED_MAX_TOKENS}（不限制）或至少 {MIN_MAX_TOKENS}"
            )
        return value

    @property
    def uses_unlimited_output(self) -> bool:
        """是否不限制输出长度；为真时发往模型的请求体不含 max_tokens。"""
        return self.max_tokens == UNLIMITED_MAX_TOKENS


class LLMConfigRecordCreate(LLMConfig):
    """命名保存的配置；同名记录会被更新。"""

    name: str = Field(min_length=1, max_length=64)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("配置名称不能为空")
        return value


class LLMConfigRecordOut(LLMConfigRecordCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class LLMTestRequest(LLMConfig):
    """测试连接使用表单当前值，不一定先保存。"""


class LLMTestResult(BaseModel):
    ok: bool
    latency_ms: int | None = None
    message: str = Field(default="", max_length=1000)


class LLMApiKeyRevealResult(BaseModel):
    """仅响应用户显式查看动作；普通配置读取仍返回脱敏引用。"""

    api_key: str = Field(default="", max_length=8192)


class LLMModelsRequest(LLMConfig):
    """按表单当前值查询服务商可用的模型列表。

    ``api_key`` 留空时后端回退到已保存的密钥，避免用户为了看模型列表先保存一遍。
    """


class LLMModelsResult(BaseModel):
    models: list[str] = Field(default_factory=list, max_length=1000)
    message: str = Field(default="", max_length=1000)


class SearchConfig(BaseModel):
    """联网搜索设置。

    多个来源会并发查询后合并去重：Bing RSS 与 DuckDuckGo 开箱可用，SearXNG 需要
    用户填自己的实例地址（公共实例经常限流，所以不预置默认值）。
    """

    sources: list[Literal["bing", "duckduckgo", "searxng"]] = Field(
        default_factory=lambda: ["bing", "duckduckgo"], min_length=1, max_length=3
    )
    # 自建 SearXNG 实例根地址，例如 http://localhost:8080
    searxng_url: str = Field(default="", max_length=512)
    # 抓取前 N 条结果的正文（0 = 只取摘要）。正文抓取更慢，也可能被站点拒绝。
    fetch_pages: int = Field(default=0, ge=0, le=3)
    # 每次搜索最多返回多少条
    max_results: int = Field(default=8, ge=1, le=15)

    @field_validator("sources")
    @classmethod
    def sources_must_be_unique(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))

    @field_validator("searxng_url")
    @classmethod
    def searxng_url_must_be_http(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value:
            return ""
        if not value.startswith(("http://", "https://")):
            raise ValueError("SearXNG 地址必须以 http:// 或 https:// 开头")
        return value


class ReminderPopupSetting(BaseModel):
    """应用打开时是否弹出近期提醒（默认开）。"""

    enabled: bool = True
