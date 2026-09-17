"""LLM Provider 抽象与工厂。"""
from ...schemas.setting import LLMConfig
from .base import BaseLLMProvider, LLMError
from .openai_compat import OpenAICompatProvider

__all__ = ["BaseLLMProvider", "LLMError", "OpenAICompatProvider", "create_provider"]

# 供设置页展示：哪些协议可选，以及各自的默认地址。
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"


def create_provider(config: LLMConfig, *, request_overrides: dict | None = None) -> BaseLLMProvider:
    """按配置创建模型调用器。

    默认走 OpenAI 兼容协议（DeepSeek/豆包/Kimi/智谱/Ollama 等）；``api_style``
    为 ``anthropic`` 时走 Claude 的 Messages 原生协议（独立的 system 字段、
    扩展思考预算、Anthropic 的工具格式）。

    ``request_overrides`` 是**单次请求**的附加参数（例如助手页选的思考强度），
    不落库、不影响其它调用；provider 只会采纳白名单里的键。

    助手当前是构造完再把 ``request_overrides`` 赋到实例上的，因为它的测试替身都只实现
    ``(config)`` 一个签名；这个参数本身是可用的（由测试守着），照签名调用即可。
    """
    if (config.api_style or "openai") == "anthropic":
        from .anthropic import AnthropicProvider

        return AnthropicProvider(config, request_overrides=request_overrides)
    return OpenAICompatProvider(config, request_overrides=request_overrides)
