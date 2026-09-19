import json
import logging

import httpx
import pytest

from app.schemas.setting import UNLIMITED_MAX_TOKENS, LLMConfig
from app.services.llm.base import LLMError
from app.services.llm.openai_compat import (
    _MAX_STREAM_CHARS,
    _MIN_STREAM_CHARS,
    OpenAICompatProvider,
)


def _provider(
    handler,
    *,
    base_url: str = "https://api.example.com/v1",
    max_tokens: int = 4096,
) -> OpenAICompatProvider:
    config = LLMConfig(base_url=base_url, api_key="secret-key", model="test", max_tokens=max_tokens)
    return OpenAICompatProvider(config, transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.example.com/v1",
        "http://localhost:11434/v1",
        "http://model.localhost:11434/v1",
        "http://127.0.0.1:11434/v1",
        "http://127.10.20.30:11434/v1",
        "http://[::1]:11434/v1",
    ],
)
def test_base_url_allows_https_and_loopback_http(base_url):
    provider = OpenAICompatProvider(LLMConfig(base_url=base_url, model="test"))

    assert provider._endpoint().endswith("/chat/completions")


@pytest.mark.parametrize(
    "base_url",
    [
        "http://api.example.com/v1",
        "http://192.168.1.20:11434/v1",
        "ftp://localhost/v1",
        "not-a-url",
        "https://user:password@api.example.com/v1",
        "https://api.example.com/v1?token=secret",
        "https://api.example.com/v1#fragment",
    ],
)
def test_base_url_rejects_unsafe_addresses(base_url):
    provider = OpenAICompatProvider(LLMConfig(base_url=base_url, model="test"))

    with pytest.raises(LLMError):
        provider._endpoint()


def test_headers_omit_authorization_when_api_key_is_empty():
    provider = OpenAICompatProvider(
        LLMConfig(base_url="http://localhost:11434/v1", api_key="", model="test")
    )

    assert provider._headers() == {"Content-Type": "application/json"}


async def test_chat_maps_invalid_json_to_llm_error():
    provider = _provider(lambda _request: httpx.Response(200, text="<html>bad gateway</html>"))

    with pytest.raises(LLMError, match="无法解析"):
        await provider.chat([{"role": "user", "content": "test"}])


async def test_chat_enforces_response_size_while_reading():
    provider = _provider(lambda _request: httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1)))

    with pytest.raises(LLMError, match="内容过大"):
        await provider.chat([{"role": "user", "content": "test"}])


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"choices": []},
        {"choices": [{"message": {"content": {"unexpected": True}}}]},
    ],
)
async def test_chat_maps_invalid_response_shape_to_llm_error(payload):
    provider = _provider(lambda _request: httpx.Response(200, json=payload))

    with pytest.raises(LLMError, match="无法解析"):
        await provider.chat([{"role": "user", "content": "test"}])


async def test_stream_rejects_malformed_frames():
    provider = _provider(
        lambda _request: httpx.Response(
            200,
            text="data: this-is-not-json\n\ndata: [DONE]\n\n",
            headers={"Content-Type": "text/event-stream"},
        )
    )

    with pytest.raises(LLMError, match="流式响应"):
        await _collect_stream(provider)


async def test_stream_enforces_total_output_limit():
    oversized = "x" * 64_001
    body = f"data: {json.dumps({'choices': [{'delta': {'content': oversized}}]})}\n\ndata: [DONE]\n\n"
    provider = _provider(
        lambda _request: httpx.Response(
            200,
            text=body,
            headers={"Content-Type": "text/event-stream"},
        ),
        max_tokens=256,
    )

    with pytest.raises(LLMError, match="输出过大"):
        await _collect_stream(provider)


@pytest.mark.parametrize("stream", [False, True])
def test_payload_includes_max_tokens_unless_output_is_unlimited(stream):
    limited = _provider(lambda _request: httpx.Response(200), max_tokens=4096)
    unlimited = _provider(lambda _request: httpx.Response(200), max_tokens=UNLIMITED_MAX_TOKENS)

    assert limited._build_payload([], stream=stream)["max_tokens"] == 4096
    # 省略而不是发送 0/-1：部分服务商会把越界或零值当作非法参数拒绝。
    assert "max_tokens" not in unlimited._build_payload([], stream=stream)


def test_stream_char_limit_uses_the_maximum_when_output_is_unlimited():
    limited = _provider(lambda _request: httpx.Response(200), max_tokens=4096)
    unlimited = _provider(lambda _request: httpx.Response(200), max_tokens=UNLIMITED_MAX_TOKENS)

    # 有上限时按 max_tokens 派生，但不低于 _MIN_STREAM_CHARS（4096 * 8 会被抬到该下界）。
    assert limited._stream_char_limit() == _MIN_STREAM_CHARS
    # max_tokens 为 0 时按乘法派生会落到下界，反而变成最严格的限制。
    assert unlimited._stream_char_limit() == _MAX_STREAM_CHARS


async def test_chat_request_body_reflects_the_unlimited_setting():
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    await _provider(handler, max_tokens=4096).chat([{"role": "user", "content": "test"}])
    await _provider(handler, max_tokens=UNLIMITED_MAX_TOKENS).chat(
        [{"role": "user", "content": "test"}]
    )

    assert bodies[0]["max_tokens"] == 4096
    # 断言真正发出去的请求体，而不只是 _build_payload 的返回值。
    assert "max_tokens" not in bodies[1]


async def test_stream_accepts_output_above_the_limited_floor_when_unlimited():
    # 不限制时 max_tokens 为 0；若沿用 max_tokens * 8 派生会落到下界 64_000，
    # 反而比任何显式设置都更早截断。
    chunk = "x" * (_MIN_STREAM_CHARS + 1)
    body = f"data: {json.dumps({'choices': [{'delta': {'content': chunk}}]})}\n\ndata: [DONE]\n\n"
    provider = _provider(
        lambda _request: httpx.Response(
            200,
            text=body,
            headers={"Content-Type": "text/event-stream"},
        ),
        max_tokens=UNLIMITED_MAX_TOKENS,
    )

    assert "".join(await _collect_stream(provider)) == chunk


async def test_http_error_log_does_not_include_upstream_body(caplog):
    provider = _provider(lambda _request: httpx.Response(500, text="UPSTREAM_PRIVATE_BODY_TOKEN"))

    with caplog.at_level(logging.WARNING):
        with pytest.raises(LLMError, match="HTTP 500"):
            await provider.chat([{"role": "user", "content": "test"}])

    assert "UPSTREAM_PRIVATE_BODY_TOKEN" not in caplog.text


async def _collect_stream(provider: OpenAICompatProvider) -> list[str]:
    return [part async for part in provider.stream_chat([{"role": "user", "content": "test"}])]


async def _collect_events(provider: OpenAICompatProvider, tools=None) -> list:
    return [
        delta
        async for delta in provider.stream_chat_events(
            [{"role": "user", "content": "test"}], tools
        )
    ]


def _sse(choices: list[dict]) -> str:
    return "".join(f"data: {json.dumps({'choices': [choice]})}\n\n" for choice in choices)


def _stream_response(body: str) -> httpx.Response:
    return httpx.Response(200, text=body, headers={"Content-Type": "text/event-stream"})


TOOLS = [
    {
        "type": "function",
        "function": {"name": "create_job", "description": "新增岗位", "parameters": {}},
    }
]


async def test_stream_events_assembles_fragmented_tool_calls():
    """工具参数是一个字符一个字符到达的，必须拼成完整 JSON 再交给调用方。"""
    fragment = '{"title": "后端开发实习生", "company": "字节跳动"}'
    frames = [{"delta": {"tool_calls": [
        {"index": 0, "id": "call_1", "type": "function", "function": {"name": "create_job", "arguments": ""}}
    ]}}]
    frames += [
        {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": character}}]}}
        for character in fragment
    ]
    frames.append({"delta": {}, "finish_reason": "tool_calls"})
    provider = _provider(lambda _request: _stream_response(_sse(frames) + "data: [DONE]\n\n"))

    deltas = await _collect_events(provider, TOOLS)

    calls = [call for delta in deltas for call in delta.tool_calls]
    assert len(calls) == 1
    assert calls[0]["id"] == "call_1"
    assert calls[0]["function"]["name"] == "create_job"
    assert json.loads(calls[0]["function"]["arguments"]) == {
        "title": "后端开发实习生",
        "company": "字节跳动",
    }
    assert deltas[-1].finish_reason == "tool_calls"


async def test_stream_events_keeps_parallel_tool_calls_apart():
    """同一次响应里的多个调用靠 index 区分，不能拼接串台。"""
    frames = [
        {"delta": {"tool_calls": [{"index": 0, "id": "a", "function": {"name": "get_job", "arguments": '{"id"'}}]}},
        {"delta": {"tool_calls": [{"index": 1, "id": "b", "function": {"name": "list_jobs", "arguments": ""}}]}},
        {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": ": 1}"}}]}},
        {"delta": {"tool_calls": [{"index": 1, "function": {"arguments": "{}"}}]}},
        {"delta": {}, "finish_reason": "tool_calls"},
    ]
    provider = _provider(lambda _request: _stream_response(_sse(frames) + "data: [DONE]\n\n"))

    deltas = await _collect_events(provider, TOOLS)

    calls = [call for delta in deltas for call in delta.tool_calls]
    assert [call["function"]["name"] for call in calls] == ["get_job", "list_jobs"]
    assert calls[0]["function"]["arguments"] == '{"id": 1}'


async def test_stream_events_yields_text_alongside_tool_calls():
    frames = [
        {"delta": {"content": "我来查一下。"}},
        {"delta": {"tool_calls": [{"index": 0, "id": "a", "function": {"name": "list_jobs", "arguments": "{}"}}]}},
        {"delta": {}, "finish_reason": "tool_calls"},
    ]
    provider = _provider(lambda _request: _stream_response(_sse(frames) + "data: [DONE]\n\n"))

    deltas = await _collect_events(provider, TOOLS)

    assert "".join(delta.text for delta in deltas) == "我来查一下。"
    assert len([call for delta in deltas for call in delta.tool_calls]) == 1


async def test_stream_events_finalizes_tool_calls_without_a_finish_reason():
    """有的端点不发 finish_reason 就结束，工具调用同样要产出。"""
    frames = [
        {"delta": {"tool_calls": [{"index": 0, "id": "a", "function": {"name": "list_jobs", "arguments": "{}"}}]}},
    ]
    provider = _provider(lambda _request: _stream_response(_sse(frames) + "data: [DONE]\n\n"))

    deltas = await _collect_events(provider, TOOLS)

    assert len([call for delta in deltas for call in delta.tool_calls]) == 1


async def test_stream_events_emits_deepseek_reasoning_content():
    """DeepSeek 系把思考内容放在 ``reasoning_content``，要单独产成 reasoning 帧。"""
    frames = [
        {"delta": {"reasoning_content": "先想"}},
        {"delta": {"reasoning_content": "一下"}},
        {"delta": {"content": "答案"}},
    ]
    provider = _provider(lambda _request: _stream_response(_sse(frames) + "data: [DONE]\n\n"))

    deltas = await _collect_events(provider)

    assert "".join(delta.reasoning for delta in deltas) == "先想一下"
    # 思考内容与正文分属不同字段，不能互相污染。
    assert "".join(delta.text for delta in deltas) == "答案"


async def test_stream_events_tolerates_the_reasoning_field_name():
    """字段名不统一是常态：有的网关用 ``reasoning``，同样要认。"""
    frames = [{"delta": {"reasoning": "思考片段"}}, {"delta": {"content": "好"}}]
    provider = _provider(lambda _request: _stream_response(_sse(frames) + "data: [DONE]\n\n"))

    deltas = await _collect_events(provider)

    assert "".join(delta.reasoning for delta in deltas) == "思考片段"


async def test_stream_events_without_reasoning_produces_nothing():
    """两个字段都缺失是常态（普通模型、未开思考）——什么都不产出，绝不臆造。"""
    frames = [{"delta": {"content": "没有思考内容"}}]
    provider = _provider(lambda _request: _stream_response(_sse(frames) + "data: [DONE]\n\n"))

    deltas = await _collect_events(provider)

    assert all(delta.reasoning == "" for delta in deltas)
    assert "".join(delta.text for delta in deltas) == "没有思考内容"


async def test_stream_events_sends_tools_only_when_asked():
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _stream_response(_sse([{"delta": {"content": "ok"}}]) + "data: [DONE]\n\n")

    await _collect_events(_provider(handler), TOOLS)
    await _collect_events(_provider(handler))

    assert bodies[0]["tools"] == TOOLS
    assert bodies[0]["tool_choice"] == "auto"
    assert "tools" not in bodies[1]


async def test_stream_events_falls_back_when_the_provider_rejects_tools():
    """不支持 tools 的端点会直接 400；此时去掉工具重试一次，而不是整体失败。"""
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "tools" in body:
            return httpx.Response(400, json={"error": {"message": "tools is not supported"}})
        return _stream_response(_sse([{"delta": {"content": "降级后的回答"}}]) + "data: [DONE]\n\n")

    deltas = await _collect_events(_provider(handler), TOOLS)

    assert len(bodies) == 2
    assert "tools" in bodies[0] and "tools" not in bodies[1]
    assert "".join(delta.text for delta in deltas) == "降级后的回答"
