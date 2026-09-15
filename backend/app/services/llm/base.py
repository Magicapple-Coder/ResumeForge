"""LLM Provider 抽象层。

新增模型提供商只需继承 BaseLLMProvider 并实现 chat / stream_chat，
业务代码（简历生成等）只依赖本抽象，不感知具体协议。
"""
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from ...schemas.setting import LLMConfig


class LLMError(Exception):
    """对外暴露的模型调用错误，message 为可直接展示给用户的中文提示。"""


@dataclass
class LLMDelta:
    """流式响应的一帧。

    一帧要么是正文片段，要么是一组**已经拼接完整**的工具调用（协议里工具调用的
    参数是碎片化到达的，拼接由 provider 负责，调用方拿到的一定是可直接 json 解析
    的字符串）。
    """

    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    finish_reason: str | None = None


class BaseLLMProvider(ABC):
    def __init__(self, config: LLMConfig):
        self.config = config

    @abstractmethod
    async def chat(self, messages: list[dict]) -> str:
        """一次性对话，返回完整回复。"""

    @abstractmethod
    async def stream_chat(self, messages: list[dict]) -> AsyncIterator[str]:
        """流式对话，逐段产出回复文本。"""
        yield ""  # pragma: no cover - 抽象方法的占位实现，声明它是异步生成器

    async def stream_chat_events(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> AsyncIterator[LLMDelta]:
        """带工具调用的流式对话。

        默认实现忽略 tools、退化成纯文本流：不支持工具调用的服务商与测试里的假
        Provider 都能继续工作，代价是不会产出 tool_calls。真正支持的 provider
        覆盖本方法。
        """
        async for chunk in self.stream_chat(messages):
            yield LLMDelta(text=chunk)
