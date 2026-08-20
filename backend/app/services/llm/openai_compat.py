"""OpenAI Chat Completions 兼容协议实现。

覆盖 DeepSeek、豆包（火山方舟）、Kimi、智谱、OpenAI、Ollama 等
绝大多数大模型服务；直接用 httpx 实现，保持依赖精简与协议透明。
"""
import json
import logging
from collections.abc import AsyncIterator
from ipaddress import ip_address
from urllib.parse import urlsplit

import httpx

from ...schemas.setting import LLMConfig
from .base import BaseLLMProvider, LLMError

logger = logging.getLogger(__name__)

# HTTP 状态码 -> 面向用户的中文提示
_STATUS_MESSAGES = {
    400: "请求格式错误，请检查模型名称与参数设置",
    401: "API Key 无效或已过期，请到「设置」页检查",
    403: "无权限访问该模型，请检查账号权限",
    404: "模型不存在或接口地址错误，请检查 Base URL 与模型名称",
    429: "请求过于频繁或额度不足，请稍后重试",
    500: "模型服务内部错误，请稍后重试",
    502: "模型服务暂不可用，请稍后重试",
    503: "模型服务过载，请稍后重试",
}

_CONNECT_TIMEOUT = 10.0  # 建连超时（秒），与业务超时分开配置
_MAX_CHAT_RESPONSE_BYTES = 2 * 1024 * 1024
_MIN_STREAM_CHARS = 64_000
_MAX_STREAM_CHARS = 2_000_000


class OpenAICompatProvider(BaseLLMProvider):
    def __init__(
        self,
        config: LLMConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        super().__init__(config)
        self._transport = transport

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
        return self._extract_content(data)

    async def stream_chat(self, messages: list[dict]) -> AsyncIterator[str]:
        payload = self._build_payload(messages, stream=True)
        try:
            async with self._client() as client:
                async with client.stream(
                    "POST", self._endpoint(), json=payload, headers=self._headers()
                ) as response:
                    if response.status_code != 200:
                        raise self._http_error(response)
                    total_chars = 0
                    async for line in response.aiter_lines():
                        # SSE 格式：每行 "data: {json}"，流结束标志 "data: [DONE]"
                        if not line.startswith("data:"):
                            continue
                        chunk = line[5:].strip()
                        if not chunk:
                            continue
                        if chunk == "[DONE]":
                            break
                        try:
                            data = json.loads(chunk)
                        except json.JSONDecodeError as exc:
                            raise LLMError("模型返回了无法解析的流式响应") from exc
                        if not isinstance(data, dict):
                            raise LLMError("模型返回了无法解析的流式响应")
                        choices = data.get("choices") or []
                        if not isinstance(choices, list):
                            raise LLMError("模型返回了无法解析的流式响应")
                        if choices:
                            choice = choices[0]
                            if not isinstance(choice, dict):
                                raise LLMError("模型返回了无法解析的流式响应")
                            delta = choice.get("delta") or {}
                            if not isinstance(delta, dict):
                                raise LLMError("模型返回了无法解析的流式响应")
                            text = delta.get("content")
                            if text is not None and not isinstance(text, str):
                                raise LLMError("模型返回了无法解析的流式响应")
                            if text:
                                total_chars += len(text)
                                if total_chars > self._stream_char_limit():
                                    raise LLMError("模型流式输出过大，请调低最大输出长度")
                                yield text
        except httpx.TimeoutException as exc:
            raise LLMError("模型响应超时，请稍后重试或调大超时时间") from exc
        except httpx.RequestError as exc:
            raise LLMError("无法连接模型服务，请检查 Base URL 与网络状态") from exc

    # ===== 内部工具 =====

    def _endpoint(self) -> str:
        """规范化接口地址：兼容用户填 Base URL 或完整接口地址两种情况。"""
        base = self._validated_base_url()
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def _validated_base_url(self) -> str:
        value = self.config.base_url.strip().rstrip("/")
        if not value:
            raise LLMError("请先填写有效的 Base URL")
        try:
            parsed = urlsplit(value)
            hostname = parsed.hostname
        except ValueError as exc:
            raise LLMError("Base URL 格式无效") from exc
        if parsed.scheme.lower() not in {"http", "https"} or not hostname:
            raise LLMError("Base URL 只支持 HTTP 或 HTTPS 地址")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise LLMError("Base URL 不能包含账号、密码、查询参数或片段")
        if parsed.scheme.lower() == "http" and not self._is_loopback_host(hostname):
            raise LLMError("远程模型服务必须使用 HTTPS；HTTP 仅允许本机地址")
        return value

    @staticmethod
    def _is_loopback_host(hostname: str) -> bool:
        normalized = hostname.rstrip(".").casefold()
        if normalized == "localhost" or normalized.endswith(".localhost"):
            return True
        try:
            return ip_address(normalized).is_loopback
        except ValueError:
            return False

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout(), transport=self._transport)

    def _stream_char_limit(self) -> int:
        return min(
            _MAX_STREAM_CHARS,
            max(_MIN_STREAM_CHARS, self.config.max_tokens * 8),
        )

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=_CONNECT_TIMEOUT,
            read=self.config.timeout_seconds,
            write=30.0,
            pool=10.0,
        )

    def _build_payload(self, messages: list[dict], stream: bool) -> dict:
        return {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": stream,
        }

    @staticmethod
    def _extract_content(data: dict) -> str:
        if not isinstance(data, dict):
            raise LLMError("模型返回了无法解析的响应格式")
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("模型返回了无法解析的响应格式") from exc
        if content is None:
            return ""
        if not isinstance(content, str):
            raise LLMError("模型返回了无法解析的响应格式")
        return content

    @staticmethod
    def _http_error(response: httpx.Response) -> LLMError:
        status = response.status_code
        message = _STATUS_MESSAGES.get(status, "模型调用失败")
        # 上游正文可能回显请求或敏感资料，只记录状态码。
        logger.warning("LLM 调用失败 status=%s", status)
        return LLMError(f"{message}（HTTP {status}）")
