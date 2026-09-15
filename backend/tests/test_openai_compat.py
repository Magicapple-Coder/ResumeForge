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
