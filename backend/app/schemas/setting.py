"""设置 Schema：当前大模型配置与用户保存的配置记录。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# max_tokens 取该值时表示“不限制”：请求体里省略该字段，由服务商/模型决定上限。
# 发送 0 或 -1 在部分服务商上会被当作非法参数拒绝，所以用省略而非哨兵数值。
UNLIMITED_MAX_TOKENS = 0
MIN_MAX_TOKENS = 256


class LLMConfig(BaseModel):
    """兼容 OpenAI Chat Completions 协议的模型配置（DeepSeek/豆包/Kimi/Ollama 等）。"""

    provider: str = Field(default="custom", max_length=32)  # 预设标识，仅用于前端展示
    base_url: str = Field(default="", max_length=512)
    api_key: str = Field(default="", max_length=8192)
    model: str = Field(default="", max_length=128)
    # 简历生成更看重事实稳定性；用户仍可按需调高创意度。
    temperature: float = Field(default=0.1, ge=0, le=2)
    timeout_seconds: int = Field(default=120, ge=10, le=600)
    max_tokens: int = Field(default=4096, ge=UNLIMITED_MAX_TOKENS, le=65536)

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
