"""Anthropic Messages 协议的 provider 测试。

没有真机 Key 也能验证的部分全部在这里钉住：请求体怎么转、SSE 怎么解析、思考强度
怎么映射。协议细节错一处就是 400/空回复，而这些错误只有在用户真花钱调用时才会
暴露，所以转换逻辑必须有离线测试。
"""
import json

import httpx
import pytest

from app.schemas.setting import LLMConfig
from app.services.llm import create_provider
from app.services.llm.anthropic import AnthropicProvider
from app.services.llm.base import LLMError


def _config(**overrides) -> LLMConfig:
    base = dict(
        api_style="anthropic",
        base_url="https://api.anthropic.com/v1",
        api_key="sk-ant-test",
        model="claude-sonnet-4-5",
        temperature=0.2,
        max_tokens=2048,
    )
    base.update(overrides)
    return LLMConfig(**base)


def _sse(events: list[dict]) -> bytes:
    return "".join(f"data: {json.dumps(event)}\n\n" for event in events).encode("utf-8")


def _provider(handler, **overrides) -> AnthropicProvider:
    return AnthropicProvider(_config(**overrides), transport=httpx.MockTransport(handler))


def test_create_provider_dispatches_on_api_style():
    assert isinstance(create_provider(_config()), AnthropicProvider)
    # 默认仍是 OpenAI 兼容协议。
    assert not isinstance(create_provider(_config(api_style="openai")), AnthropicProvider)


@pytest.mark.asyncio
async def test_request_body_extracts_system_and_converts_tools():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.read())
        return httpx.Response(200, json={"content": [{"type": "text", "text": "好的"}]})

    provider = _provider(handler)
    reply = await provider.chat(
        [
            {"role": "system", "content": "你是面试官"},
            {"role": "user", "content": "开始吧"},
        ]
    )

    assert reply == "好的"
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-ant-test"
    assert captured["headers"]["anthropic-version"]
    body = captured["body"]
    # system 必须是独立字段，而不是 messages 里的一条。
    assert body["system"] == "你是面试官"
    assert [message["role"] for message in body["messages"]] == ["user"]
    assert body["max_tokens"] == 2048
    assert body["temperature"] == 0.2
    assert "tools" not in body


@pytest.mark.asyncio
async def test_tool_result_and_tool_calls_are_converted():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.read())
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})

    provider = _provider(handler)
    await provider.chat(
        [
            {"role": "user", "content": "有哪些岗位？"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "list_jobs", "arguments": '{"limit": 5}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "3 个岗位"},
        ]
    )

    body = captured["body"]
    assistant = body["messages"][1]
    tool_use = [block for block in assistant["content"] if block["type"] == "tool_use"]
    assert tool_use and tool_use[0]["name"] == "list_jobs"
    assert tool_use[0]["input"] == {"limit": 5}
    # 工具结果由 user 角色承载，且是 tool_result 内容块。
    result_message = body["messages"][2]
    assert result_message["role"] == "user"
    assert result_message["content"][0]["type"] == "tool_result"
    assert result_message["content"][0]["tool_use_id"] == "call_1"


@pytest.mark.asyncio
async def test_tools_are_converted_to_input_schema():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.read())
        return httpx.Response(200, content=_sse([{"type": "message_stop"}]))

    provider = _provider(handler)
    async for _ in provider.stream_chat_events(
        [{"role": "user", "content": "hi"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "list_jobs",
                    "description": "列出岗位",
                    "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
                },
            }
        ],
    ):
        pass

    assert captured["body"]["tools"] == [
        {
            "name": "list_jobs",
            "description": "列出岗位",
            "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
        }
    ]


@pytest.mark.asyncio
async def test_stream_parses_text_and_tool_blocks():
    events = [
        {"type": "message_start"},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "你好"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "，世界"}},
        {"type": "content_block_stop", "index": 0},
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "toolu_1", "name": "list_jobs"},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"lim'},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": 'it": 5}'},
        },
        {"type": "content_block_stop", "index": 1},
        {"type": "message_stop"},
    ]

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse(events))

    provider = _provider(handler)
    texts: list[str] = []
    calls: list[dict] = []
    async for delta in provider.stream_chat_events([{"role": "user", "content": "hi"}]):
        texts.append(delta.text)
        calls.extend(delta.tool_calls)

    assert "".join(texts) == "你好，世界"
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "list_jobs"
    # 分片的 JSON 必须拼成可直接解析的字符串。
    assert json.loads(calls[0]["function"]["arguments"]) == {"limit": 5}


@pytest.mark.asyncio
async def test_stream_parses_thinking_delta_and_ignores_signature():
    """extended thinking 的思考内容在 ``thinking_delta``；末尾的 ``signature_delta`` 不采集。

    签名是加密串、唯一用途是原样回传给下一轮；我们当前不回传 thinking 块（见
    ``_convert_messages`` 的说明），所以既不该把它当内容展示，也不该落进 reasoning。
    """
    events = [
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking"}},
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "先想"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "signature_delta", "signature": "SIGNED-bytes=="},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "清楚了"},
        },
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "text"}},
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "text_delta", "text": "答案"},
        },
        {"type": "content_block_stop", "index": 1},
        {"type": "message_stop"},
    ]

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse(events))

    provider = _provider(handler)
    reasoning: list[str] = []
    texts: list[str] = []
    async for delta in provider.stream_chat_events([{"role": "user", "content": "hi"}]):
        if delta.reasoning:
            reasoning.append(delta.reasoning)
        texts.append(delta.text)

    assert "".join(reasoning) == "先想清楚了"
    assert "".join(texts) == "答案"
    assert "SIGNED" not in "".join(reasoning)


@pytest.mark.asyncio
async def test_reasoning_effort_maps_to_thinking_budget():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.read())
        return httpx.Response(200, content=_sse([{"type": "message_stop"}]))

    provider = AnthropicProvider(
        _config(), transport=httpx.MockTransport(handler), request_overrides={"reasoning_effort": "high"}
    )
    async for _ in provider.stream_chat_events([{"role": "user", "content": "hi"}]):
        pass

    body = captured["body"]
    assert body["thinking"] == {"type": "enabled", "budget_tokens": 16_384}
    # 开启思考时协议要求 temperature 为 1，且预算要小于 max_tokens。
    assert body["temperature"] == 1.0
    assert body["max_tokens"] > 16_384


@pytest.mark.asyncio
async def test_disabled_thinking_is_explicit():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.read())
        return httpx.Response(200, content=_sse([{"type": "message_stop"}]))

    provider = AnthropicProvider(
        _config(), transport=httpx.MockTransport(handler), request_overrides={"reasoning_effort": "none"}
    )
    async for _ in provider.stream_chat_events([{"role": "user", "content": "hi"}]):
        pass

    assert captured["body"]["thinking"] == {"type": "disabled"}
    assert captured["body"]["temperature"] == 0.2


@pytest.mark.asyncio
async def test_stream_error_event_becomes_llm_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_sse([{"type": "error", "error": {"type": "overloaded_error", "message": "忙"}}]),
        )

    provider = _provider(handler)
    with pytest.raises(LLMError, match="忙"):
        async for _ in provider.stream_chat_events([{"role": "user", "content": "hi"}]):
            pass


@pytest.mark.asyncio
async def test_http_400_gives_actionable_message():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "bad"}})

    provider = _provider(handler)
    with pytest.raises(LLMError, match="HTTP 400"):
        await provider.chat([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_thinking_with_tool_history_explains_the_real_cause():
    """开了思考又在多轮工具调用里报 400：要指向真正的原因（thinking 块未回传），
    而不是把用户支去改模型名 / max_tokens / 预算。

    这一组合下的 400 几乎必然是协议层"没回传 thinking 块"；若给通用文案，用户会去改
    一堆无关参数、白忙一场——比不提示更糟。
    """

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "bad"}})

    provider = AnthropicProvider(
        _config(),
        transport=httpx.MockTransport(handler),
        request_overrides={"reasoning_effort": "high"},
    )
    messages = [
        {"role": "user", "content": "查一下岗位"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "t1",
                    "type": "function",
                    "function": {"name": "list_jobs", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "t1", "content": "结果"},
    ]
    with pytest.raises(LLMError, match="思考强度") as excinfo:
        async for _ in provider.stream_chat_events(messages):
            pass

    message = str(excinfo.value)
    assert "回传" in message
    # 不再把用户支去改模型名 / 预算——那才是要修掉的误导。
    assert "检查模型名称" not in message


@pytest.mark.asyncio
async def test_plain_400_keeps_the_generic_message():
    """普通 400 仍是通用提示：改那条文案不能波及其它场景（开思考但没工具、有工具但没开思考）。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "bad"}})

    # 开了思考但没有工具历史 → 通用提示
    thinking_only = AnthropicProvider(
        _config(),
        transport=httpx.MockTransport(handler),
        request_overrides={"reasoning_effort": "high"},
    )
    with pytest.raises(LLMError, match="检查模型名称") as first:
        async for _ in thinking_only.stream_chat_events([{"role": "user", "content": "hi"}]):
            pass
    assert "回传" not in str(first.value)

    # 有工具历史但没开思考 → 通用提示
    tools_only = _provider(handler)
    with pytest.raises(LLMError, match="检查模型名称") as second:
        async for _ in tools_only.stream_chat_events(
            [
                {"role": "user", "content": "查一下"},
                {"role": "tool", "tool_call_id": "t1", "content": "结果"},
            ]
        ):
            pass
    assert "回传" not in str(second.value)


@pytest.mark.asyncio
async def test_unlimited_tokens_fall_back_to_a_concrete_limit():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.read())
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})

    # max_tokens=0 表示「不限制」，但 Messages 协议必须给一个具体值。
    provider = _provider(handler, max_tokens=0)
    await provider.chat([{"role": "user", "content": "hi"}])

    assert captured["body"]["max_tokens"] == 8192


@pytest.mark.asyncio
async def test_image_blocks_are_converted_from_openai_shape():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.read())
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})

    provider = _provider(handler)
    await provider.chat(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "看看这张图"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,aGVsbG8="},
                    },
                ],
            }
        ]
    )

    blocks = captured["body"]["messages"][0]["content"]
    assert blocks[1] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "aGVsbG8="},
    }
