"""LLM Provider 抽象层。

新增模型提供商只需继承 BaseLLMProvider 并实现 chat / stream_chat，
业务代码（简历生成等）只依赖本抽象，不感知具体协议。
"""
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ...schemas.setting import LLMConfig


class LLMError(Exception):
    """对外暴露的模型调用错误，message 为可直接展示给用户的中文提示。"""


class BaseLLMProvider(ABC):
    def __init__(self, config: LLMConfig):
        self.config = config

    @abstractmethod
    async def chat(self, messages: list[dict]) -> str:
        """一次性对话，返回完整回复。"""

    @abstractmethod
    async def stream_chat(self, messages: list[dict]) -> AsyncIterator[str]:
        """流式对话，逐段产出回复文本。"""
        yield ""  # pragma: no cover - 抽象方法的占位实现
