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
from .base import BaseLLMProvider, LLMDelta, LLMError

logger = logging.getLogger(__name__)


def _accumulate_tool_calls(pending: dict[int, dict], fragments: object) -> None:
    """把碎片化的 tool_calls 增量按 index 累积起来。

    协议里一个调用的 id / name / arguments 可能分散在多个帧里，帧与帧之间是
    **拼接**关系而不是覆盖关系；index 用来区分同一次响应里的多个并行调用。
    实测一个很短的 JSON 参数会用二十多帧、每帧一到两个字符地到达。
    """
    if not isinstance(fragments, list):
        return
    for fragment in fragments:
        if not isinstance(fragment, dict):
            continue
        try:
            index = int(fragment.get("index", 0))
        except (TypeError, ValueError):
            index = 0
        slot = pending.setdefault(
            index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
        )
        if isinstance(fragment.get("id"), str) and fragment["id"]:
            slot["id"] = fragment["id"]
        if isinstance(fragment.get("type"), str) and fragment["type"]:
            slot["type"] = fragment["type"]
        function = fragment.get("function")
        if isinstance(function, dict):
            if isinstance(function.get("name"), str):
                slot["function"]["name"] += function["name"]
            if isinstance(function.get("arguments"), str):
                slot["function"]["arguments"] += function["arguments"]


def _finalize_tool_calls(pending: dict[int, dict]) -> list[dict]:
    return [pending[index] for index in sorted(pending)]


def _extract_reasoning(delta: dict) -> str:
    """从流式帧里读出模型的思考内容片段。

    **没有一个统一的字段名**，各家的兼容端点各写各的，所以要逐个容忍：

    - ``reasoning_content``：DeepSeek 系（含自建/网关）的思考内容；
    - ``reasoning``：部分 OpenAI 系与第三方网关用的名字。

    两个都缺失就返回空串——**什么都不产出，绝不臆造**。这一点很关键：绝大多数普通
    模型和不开思考的请求本来就没有思考内容，缺失是常态而非异常，静默跳过即可。
    只有确实是字符串且非空时才返回。
    """
    for key in ("reasoning_content", "reasoning"):
        value = delta.get(key)
        if isinstance(value, str) and value:
            return value
    return ""





def _looks_like_unsupported_tools(error: LLMError) -> bool:
    """判断这次失败是否因为服务商不认识 tools 参数。

    ``_http_error`` 刻意不把上游正文带进错误消息（可能回显敏感资料），所以这里
    只能依据状态码。400 也可能是别的原因，但退化成不带工具再试一次是无害的。
    """
    return "（HTTP 400）" in str(error)

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

# 请求级覆盖参数白名单：model / messages / stream 这些关键字段永远不允许被覆盖，
# 否则一个前端参数就能改写整次调用的语义。
_OVERRIDABLE_KEYS = frozenset(
    {
        "reasoning_effort",
        "top_p",
        "frequency_penalty",
        "presence_penalty",
        "seed",
        "temperature",
        "max_tokens",
    }
)


def http_error_message(status: int) -> str:
    """HTTP 状态码对应的中文提示（provider 与模型列表接口共用）。"""
    return _STATUS_MESSAGES.get(status, "模型调用失败")


def is_loopback_host(hostname: str) -> bool:
    """HTTP 只允许本机地址；这里同时供 Base URL 校验与模型列表接口复用。"""
    normalized = hostname.rstrip(".").casefold()
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def validated_base_url(value: str) -> str:
    """校验并返回可用的服务根地址。

    远程地址必须 HTTPS，HTTP 只允许本机回环；地址不能包含账号、密码、查询参数或
    片段。provider 与"获取可用模型"接口共用同一套规则，避免两处判断漂移。
    """
    cleaned = (value or "").strip().rstrip("/")
    if not cleaned:
        raise LLMError("请先填写有效的 Base URL")
    try:
        parsed = urlsplit(cleaned)
        hostname = parsed.hostname
    except ValueError as exc:
        raise LLMError("Base URL 格式无效") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        raise LLMError("Base URL 只支持 HTTP 或 HTTPS 地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise LLMError("Base URL 不能包含账号、密码、查询参数或片段")
    if parsed.scheme.lower() == "http" and not is_loopback_host(hostname):
        raise LLMError("远程模型服务必须使用 HTTPS；HTTP 仅允许本机地址")
    return cleaned


def models_endpoint(base_url: str) -> str:
    """由 Base URL 推导模型列表地址。

    兼容用户填 ``https://api.x.com``、``https://api.x.com/v1`` 或完整
    ``.../chat/completions`` 三种情况。
    """
    base = validated_base_url(base_url)
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    return f"{base}/models"


class OpenAICompatProvider(BaseLLMProvider):
    def __init__(
        self,
        config: LLMConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        request_overrides: dict | None = None,
    ):
        # request_overrides 必须转发给基类：`create_provider(..., request_overrides=...)`
        # 是文档化的入口，这里不接的话它会直接抛 TypeError，而调用方只能改成
        # 构造完再赋值属性——看起来能跑，实际绕过了工厂的契约。
        super().__init__(config, request_overrides=request_overrides)
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
        async for delta in self.stream_chat_events(messages):
            if delta.text:
                yield delta.text

    async def stream_chat_events(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> AsyncIterator[LLMDelta]:
        """带工具调用的流式对话。

        工具调用的参数在协议里是**碎片化**到达的（实测一个短 JSON 会用二十多帧、
        每帧一两个字符），必须按 index 累积拼接；拼接结果才是可直接 json 解析的
        字符串，这一点由本方法保证，调用方不必关心。
        """
        try:
            async for delta in self._stream_deltas(messages, tools):
                yield delta
        except LLMError as exc:
            # 不少 OpenAI 兼容端点（本地小模型等）不支持 tools，会直接返回 400。
            # 这里降级成不带工具的普通对话重试一次，而不是让整个功能不可用。
            if tools and _looks_like_unsupported_tools(exc):
                logger.warning("模型不支持工具调用，已降级为普通对话：%s", exc)
                async for delta in self._stream_deltas(messages, None):
                    yield delta
                return
            raise

    async def _stream_deltas(
        self, messages: list[dict], tools: list[dict] | None
    ) -> AsyncIterator[LLMDelta]:
        payload = self._build_payload(messages, stream=True, tools=tools)
        try:
            async with self._client() as client:
                async with client.stream(
                    "POST", self._endpoint(), json=payload, headers=self._headers()
                ) as response:
                    if response.status_code != 200:
                        raise self._http_error(response)
                    total_chars = 0
                    pending: dict[int, dict] = {}
                    finish_reason: str | None = None
                    emitted = False
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
                        if not choices:
                            continue
                        choice = choices[0]
                        if not isinstance(choice, dict):
                            raise LLMError("模型返回了无法解析的流式响应")
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
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
                            yield LLMDelta(text=text)
                        # 思考内容与正文分开产出：它不是要展示给用户的回答，而是"模型
                        # 在想什么"。同样计入 total_chars——它是真实消耗的输出，且不受
                        # 限的话一条只会思考的流会无界增长。
                        reasoning = _extract_reasoning(delta)
                        if reasoning:
                            total_chars += len(reasoning)
                            if total_chars > self._stream_char_limit():
                                raise LLMError("模型流式输出过大，请调低最大输出长度")
                            yield LLMDelta(reasoning=reasoning)
                        _accumulate_tool_calls(pending, delta.get("tool_calls"))
                        # 有的端点不发 finish_reason 就结束，所以下面还要兜一次。
                        if finish_reason and pending and not emitted:
                            emitted = True
                            yield LLMDelta(
                                tool_calls=_finalize_tool_calls(pending),
                                finish_reason=finish_reason,
                            )
                    if pending and not emitted:
                        yield LLMDelta(tool_calls=_finalize_tool_calls(pending))
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
        return validated_base_url(self.config.base_url)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout(), transport=self._transport)

    def _stream_char_limit(self) -> int:
        # 不限制输出时 max_tokens 为 0，按乘法派生会落到下界，反而成为最严格的
        # 限制；这种情况直接用允许的最大值。
        if self.config.uses_unlimited_output:
            return _MAX_STREAM_CHARS
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

    def _build_payload(
        self, messages: list[dict], stream: bool, tools: list[dict] | None = None
    ) -> dict:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "stream": stream,
        }
        # 不限制输出时省略该字段，由服务商/模型决定上限；发送 0 或 -1 在部分
        # 服务商上会被当作非法参数拒绝。注意这不是“真的无限”，有些服务商的
        # 默认值可能小于用户此前手动设置的值。
        if not self.config.uses_unlimited_output:
            payload["max_tokens"] = self.config.max_tokens
        self._apply_advanced_parameters(payload)
        self._apply_request_overrides(payload)
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    def _apply_advanced_parameters(self, payload: dict) -> None:
        """发送用户在「高级调整」里显式开启的参数；未开启（None）就不发送。"""
        for key in (
            "top_p",
            "frequency_penalty",
            "presence_penalty",
            "seed",
            "top_k",
            "repetition_penalty",
        ):
            value = getattr(self.config, key, None)
            if value is not None:
                payload[key] = value
        stop = getattr(self.config, "stop", None)
        if stop:
            payload["stop"] = list(stop)
        # Claude 系（含兼容网关）的扩展思考：0 明确关闭，正数给预算。
        thinking_budget = getattr(self.config, "thinking_budget", None)
        if thinking_budget is not None:
            payload["thinking"] = (
                {"type": "enabled", "budget_tokens": thinking_budget}
                if thinking_budget > 0
                else {"type": "disabled"}
            )
        # 额外请求体：长尾参数的出口。保留键已在校验层拦掉，这里原样合并。
        extra = getattr(self.config, "extra_body", None)
        if isinstance(extra, dict):
            for key, value in extra.items():
                payload.setdefault(key, value)

    def _apply_request_overrides(self, payload: dict) -> None:
        """合并单次请求的覆盖参数（白名单 + 非空值）。"""
        for key, value in self.request_overrides.items():
            if key in _OVERRIDABLE_KEYS and value not in (None, ""):
                payload[key] = value

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
        # 上游正文可能回显请求或敏感资料，只记录状态码。
        logger.warning("LLM 调用失败 status=%s", status)
        return LLMError(f"{http_error_message(status)}（HTTP {status}）")
