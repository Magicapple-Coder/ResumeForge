"""Anthropic Claude 的 Messages 原生协议实现。

为什么值得单独写一个 provider（而不是只用 Anthropic 的 OpenAI 兼容层）：

- system 在 Messages 协议里是**独立字段**，兼容层要被塞进 messages 里；
- 扩展思考（``thinking``）与思考预算只在原生协议下暴露；
- 工具调用是 ``tool_use`` / ``tool_result`` 内容块，和 OpenAI 的
  ``tool_calls`` 不是同一种结构，转换放在这里比塞进兼容层更清楚。

协议要点（按 2026-09 的官方文档口径）：
- 端点 ``POST {base_url}/messages``，鉴权头 ``x-api-key``，另有
  ``anthropic-version: 2023-06-01``；部分第三方网关只认 ``Authorization: Bearer``，
  所以两个头都发（官方会忽略多余的那个）。
- ``max_tokens`` 必填。用户选了「不限制」时用一个足够大的默认值，而不是省略。
- 开启扩展思考时 ``temperature`` 必须为 1，且预算要小于 ``max_tokens``。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ...schemas.setting import LLMConfig
from .base import BaseLLMProvider, LLMDelta, LLMError
from .openai_compat import http_error_message, validated_base_url

logger = logging.getLogger(__name__)

ANTHROPIC_VERSION = "2023-06-01"
# 「不限制输出」时使用的兜底上限：Messages 协议必须给这个字段。
_FALLBACK_MAX_TOKENS = 8192

_MAX_CHAT_RESPONSE_BYTES = 2 * 1024 * 1024
_MIN_STREAM_CHARS = 64_000
_MAX_STREAM_CHARS = 2_000_000

# 思考强度 → 思考预算（tokens）。用于助手页的「思考强度」在原生协议下的映射。
_EFFORT_BUDGETS: dict[str, int] = {
    "minimal": 1_024,
    "low": 2_048,
    "medium": 8_192,
    "high": 16_384,
}


def _data_url_to_image_block(data_url: str) -> dict[str, Any] | None:
    """把 OpenAI 风格的 data URL 图片转成 Anthropic 的 image 内容块。"""
    header, separator, encoded = data_url.partition(",")
    if not separator or not header.startswith("data:") or "base64" not in header:
        return None
    media_type = header[len("data:") :].split(";", 1)[0].strip() or "image/png"
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": encoded},
    }


def _text_from_content(content: Any) -> str:
    """从字符串或块数组里取出纯文本部分。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _anthropic_content_blocks(content: Any) -> list[dict[str, Any]]:
    """把一条消息的 content 转成 Anthropic 的内容块数组。"""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    blocks: list[dict[str, Any]] = []
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                blocks.append({"type": "text", "text": str(block.get("text", ""))})
            elif block.get("type") == "image_url":
                url = block.get("image_url", {})
                url_value = url.get("url") if isinstance(url, dict) else None
                converted = _data_url_to_image_block(str(url_value or ""))
                if converted is not None:
                    blocks.append(converted)
    return blocks or [{"type": "text", "text": ""}]


def _convert_messages(messages: list[dict]) -> tuple[str, list[dict[str, Any]]]:
    """拆分出 system 文本，并把消息转成 Messages 协议的结构。

    转换的三处差异：
    - ``role: "system"`` 抽出来单独返回（协议要求）；
    - 助手消息里的 ``tool_calls`` → ``tool_use`` 内容块；
    - ``role: "tool"`` 的结果 → 紧随其后的 user 消息里的 ``tool_result`` 块
      （协议要求工具结果由 user 角色承载）。
    """
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        if role == "system":
            text = _text_from_content(message.get("content"))
            if text.strip():
                system_parts.append(text)
            continue
        if role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": str(message.get("tool_call_id") or ""),
                "content": _text_from_content(message.get("content")),
            }
            # 工具结果可能连续多条，合并进同一条 user 消息。
            if converted and converted[-1]["role"] == "user" and converted[-1].get("_tool_results"):
                converted[-1]["content"].append(block)
                continue
            converted.append({"role": "user", "content": [block], "_tool_results": True})
            continue

        blocks = _anthropic_content_blocks(message.get("content"))
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            for call in tool_calls:
                function = (call or {}).get("function") or {}
                raw_arguments = function.get("arguments") or "{}"
                try:
                    parsed = json.loads(raw_arguments)
                except (TypeError, ValueError):
                    parsed = {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": str(call.get("id") or ""),
                        "name": str(function.get("name") or ""),
                        "input": parsed if isinstance(parsed, dict) else {},
                    }
                )
        converted.append(
            {"role": "assistant" if role == "assistant" else "user", "content": blocks}
        )

    # 去掉内部标记，协议里没有这个字段。
    for message in converted:
        message.pop("_tool_results", None)
    return "\n\n".join(system_parts), converted


def _convert_tools(tools: list[dict] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    converted: list[dict[str, Any]] = []
    for tool in tools:
        function = (tool or {}).get("function") or {}
        name = str(function.get("name") or "")
        if not name:
            continue
        converted.append(
            {
                "name": name,
                "description": str(function.get("description") or ""),
                "input_schema": function.get("parameters")
                or {"type": "object", "properties": {}},
            }
        )
    return converted or None


class AnthropicProvider(BaseLLMProvider):
    def __init__(
        self,
        config: LLMConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        request_overrides: dict | None = None,
    ):
        super().__init__(config, request_overrides=request_overrides)
        self._transport = transport

    # ===== 公共入口 =====

    async def chat(self, messages: list[dict]) -> str:
        payload = self._build_payload(messages, stream=False)
        try:
            async with self._client() as client:
                async with client.stream(
                    "POST", self._endpoint(), json=payload, headers=self._headers()
                ) as response:
                    if response.status_code != 200:
                        raise self._http_error(response)
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > _MAX_CHAT_RESPONSE_BYTES:
                            raise LLMError("模型返回内容过大，请调低最大输出长度")
                        body.extend(chunk)
        except httpx.TimeoutException as exc:
            raise LLMError("模型响应超时，请稍后重试或调大超时时间") from exc
        except httpx.RequestError as exc:
            raise LLMError("无法连接模型服务，请检查 Base URL 与网络状态") from exc
        try:
            data = json.loads(body)
        except (ValueError, UnicodeError) as exc:
            raise LLMError("模型返回了无法解析的响应格式") from exc
        return self._extract_text(data)

    async def stream_chat(self, messages: list[dict]) -> AsyncIterator[str]:
        async for delta in self.stream_chat_events(messages):
            if delta.text:
                yield delta.text

    async def stream_chat_events(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> AsyncIterator[LLMDelta]:
        payload = self._build_payload(messages, stream=True, tools=tools)
        try:
            async with self._client() as client:
                async with client.stream(
                    "POST", self._endpoint(), json=payload, headers=self._headers()
                ) as response:
                    if response.status_code != 200:
                        raise self._http_error(response)
                    async for delta in self._iter_sse(response):
                        yield delta
        except httpx.TimeoutException as exc:
            raise LLMError("模型响应超时，请稍后重试或调大超时时间") from exc
        except httpx.RequestError as exc:
            raise LLMError("无法连接模型服务，请检查 Base URL 与网络状态") from exc

    # ===== 内部实现 =====

    async def _iter_sse(self, response: httpx.Response) -> AsyncIterator[LLMDelta]:
        """解析 Messages 协议的 SSE 事件流。

        文本来自 ``text_delta``；工具调用由 ``content_block_start``（拿到 id 与
        name）与 ``input_json_delta``（分片 JSON 拼接）组成，在块结束时产出。
        """
        total_chars = 0
        pending: dict[int, dict[str, Any]] = {}
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if not chunk:
                continue
            try:
                event = json.loads(chunk)
            except json.JSONDecodeError as exc:
                raise LLMError("模型返回了无法解析的流式响应") from exc
            if not isinstance(event, dict):
                raise LLMError("模型返回了无法解析的流式响应")
            event_type = event.get("type")

            if event_type == "error":
                detail = event.get("error") or {}
                message = detail.get("message") if isinstance(detail, dict) else ""
                raise LLMError(f"模型返回错误：{message or '未知错误'}")

            if event_type == "content_block_start":
                block = event.get("content_block") or {}
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    index = int(event.get("index") or 0)
                    pending[index] = {
                        "id": str(block.get("id") or ""),
                        "type": "function",
                        "function": {
                            "name": str(block.get("name") or ""),
                            "arguments": "",
                        },
                    }
                continue

            if event_type == "content_block_delta":
                delta = event.get("delta") or {}
                if not isinstance(delta, dict):
                    continue
                if delta.get("type") == "text_delta":
                    text = delta.get("text")
                    if isinstance(text, str) and text:
                        total_chars += len(text)
                        if total_chars > self._stream_char_limit():
                            raise LLMError("模型流式输出过大，请调低最大输出长度")
                        yield LLMDelta(text=text)
                elif delta.get("type") == "input_json_delta":
                    index = int(event.get("index") or 0)
                    slot = pending.get(index)
                    if slot is not None:
                        slot["function"]["arguments"] += str(delta.get("partial_json") or "")
                continue

            if event_type == "content_block_stop":
                index = int(event.get("index") or 0)
                slot = pending.pop(index, None)
                if slot is not None:
                    yield LLMDelta(tool_calls=[slot])
                continue

        # 兜底：少数网关不发 content_block_stop。
        if pending:
            yield LLMDelta(tool_calls=[pending[index] for index in sorted(pending)])

    def _endpoint(self) -> str:
        base = validated_base_url(self.config.base_url)
        if base.endswith("/messages"):
            return base
        return f"{base}/messages"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
        }
        if self.config.api_key:
            headers["x-api-key"] = self.config.api_key
            # 第三方网关多数只认 Bearer；官方会忽略它。
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout(), transport=self._transport)

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=10.0,
            read=self.config.timeout_seconds,
            write=30.0,
            pool=10.0,
        )

    def _stream_char_limit(self) -> int:
        if self.config.uses_unlimited_output:
            return _MAX_STREAM_CHARS
        return min(_MAX_STREAM_CHARS, max(_MIN_STREAM_CHARS, self.config.max_tokens * 8))

    def _max_tokens(self) -> int:
        """Messages 协议必须给 max_tokens；「不限制」时用一个较大的兜底值。

        注意这不是"真的无限"——协议没有"省略即不限"的写法，只能给一个足够大的数。
        """
        if self.config.uses_unlimited_output:
            return _FALLBACK_MAX_TOKENS
        return self.config.max_tokens

    def _thinking_budget(self) -> int:
        """本次请求的思考预算：请求级「思考强度」优先，其次配置里的预算。"""
        effort = str(self.request_overrides.get("reasoning_effort") or "").strip()
        if effort:
            if effort == "none":
                return 0
            budget = _EFFORT_BUDGETS.get(effort)
            if budget:
                return budget
        configured = getattr(self.config, "thinking_budget", None)
        return int(configured or 0)

    def _build_payload(
        self, messages: list[dict], stream: bool, tools: list[dict] | None = None
    ) -> dict[str, Any]:
        system_text, converted = _convert_messages(messages)
        max_tokens = self._max_tokens()
        payload: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": max_tokens,
            "messages": converted,
            "stream": stream,
        }
        if system_text:
            payload["system"] = system_text[:60_000]

        budget = self._thinking_budget()
        if budget > 0:
            # 协议要求：开启思考时 temperature 必须为 1，预算要小于 max_tokens。
            payload["thinking"] = {"type": "enabled", "budget_tokens": budget}
            if max_tokens <= budget:
                payload["max_tokens"] = budget + 4_096
            payload["temperature"] = 1.0
        else:
            payload["temperature"] = self.config.temperature
            if str(self.request_overrides.get("reasoning_effort") or "") == "none":
                payload["thinking"] = {"type": "disabled"}

        if self.config.top_p is not None:
            payload["top_p"] = self.config.top_p
        if self.config.top_k is not None:
            payload["top_k"] = self.config.top_k
        if self.config.stop:
            payload["stop_sequences"] = list(self.config.stop)
        # 「额外请求体」在原生协议下同样有效（用户自己知道目标服务支持什么）。
        extra = getattr(self.config, "extra_body", None)
        if isinstance(extra, dict):
            for key, value in extra.items():
                payload.setdefault(key, value)

        tool_payload = _convert_tools(tools)
        if tool_payload:
            payload["tools"] = tool_payload
        return payload

    @staticmethod
    def _extract_text(data: dict) -> str:
        if not isinstance(data, dict):
            raise LLMError("模型返回了无法解析的响应格式")
        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise LLMError("模型返回了无法解析的响应格式")
        parts = [
            str(block.get("text", ""))
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "".join(parts)

    @staticmethod
    def _http_error(response: httpx.Response) -> LLMError:
        status = response.status_code
        logger.warning("Anthropic 调用失败 status=%s", status)
        if status == 400:
            # 原生协议最常见的 400 是模型名或参数问题，提示更具体一点。
            return LLMError(
                "请求格式错误：请检查模型名称、max_tokens 与思考预算设置（HTTP 400）"
            )
        return LLMError(f"{http_error_message(status)}（HTTP {status}）")


__all__ = ["AnthropicProvider"]
