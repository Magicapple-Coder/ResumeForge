"""LLM Provider 抽象与工厂。"""
from ...schemas.setting import LLMConfig
from .base import BaseLLMProvider, LLMError
from .openai_compat import OpenAICompatProvider

__all__ = ["BaseLLMProvider", "LLMError", "OpenAICompatProvider", "create_provider"]


def create_provider(config: LLMConfig, *, request_overrides: dict | None = None) -> BaseLLMProvider:
    """按配置创建模型调用器。

    目前全部走 OpenAI 兼容协议（DeepSeek/豆包/Kimi/智谱/Ollama 均支持）；
    未来接入非兼容协议（如 Claude 原生 API）时，在此按 provider 分发即可。

    ``request_overrides`` 是**单次请求**的附加参数（例如助手页选的思考强度），
    不落库、不影响其它调用；provider 只会采纳白名单里的键。

    助手当前是构造完再把 ``request_overrides`` 赋到实例上的，因为它的测试替身都只实现
    ``(config)`` 一个签名；这个参数本身是可用的（由测试守着），照签名调用即可。
    """
    return OpenAICompatProvider(config, request_overrides=request_overrides)
