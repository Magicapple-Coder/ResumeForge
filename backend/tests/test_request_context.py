import json
import logging

from app import main as app_main
from app.middleware import RequestContextMiddleware


def _scope(headers=()):
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/test",
        "raw_path": b"/api/test",
        "query_string": b"",
        "headers": list(headers),
        "client": ("127.0.0.1", 1234),
        "server": ("127.0.0.1", 8000),
    }


def test_http_client_does_not_log_full_request_urls_at_info():
    assert app_main.app is not None
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING


async def _collect_response(middleware, scope, request_messages):
    sent = []

    async def receive():
        return request_messages.pop(0)

    async def send(message):
        sent.append(message)

    await middleware(scope, receive, send)
    return sent


async def test_request_limit_rejects_declared_size_without_reading_body():
    async def downstream(_scope, _receive, _send):  # pragma: no cover - must not run
        raise AssertionError("oversized request reached downstream app")

    middleware = RequestContextMiddleware(downstream, max_body_bytes=4)
    sent = await _collect_response(
        middleware,
        _scope([(b"content-length", b"5"), (b"x-request-id", b"test-request")]),
        [],
    )

    assert sent[0]["status"] == 413
    request_ids = [value for name, value in sent[0]["headers"] if name == b"x-request-id"]
    assert len(request_ids) == 1
    assert request_ids[0] != b"test-request"
    assert len(request_ids[0]) == 32
    assert "请求体过大" in json.loads(sent[1]["body"])["detail"]


async def test_request_limit_rejects_chunked_body_without_content_length():
    async def downstream(scope, receive, send):
        while True:
            message = await receive()
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = RequestContextMiddleware(downstream, max_body_bytes=4)
    sent = await _collect_response(
        middleware,
        _scope(),
        [
            {"type": "http.request", "body": b"abc", "more_body": True},
            {"type": "http.request", "body": b"def", "more_body": False},
        ],
    )

    assert sent[0]["status"] == 413
    assert any(name == b"x-request-id" for name, _ in sent[0]["headers"])


async def test_request_id_replaces_downstream_header():
    async def downstream(_scope, _receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 204,
                "headers": [(b"x-request-id", b"downstream-value")],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    middleware = RequestContextMiddleware(downstream, max_body_bytes=4)
    sent = await _collect_response(middleware, _scope(), [])

    request_ids = [value for name, value in sent[0]["headers"] if name == b"x-request-id"]
    assert len(request_ids) == 1
    assert request_ids[0] != b"downstream-value"
    assert len(request_ids[0]) == 32


def _scope_at(path, headers=()):
    scope = _scope(headers)
    scope["path"] = path
    scope["raw_path"] = path.encode()
    return scope


def _echo_body_middleware():
    """返回 (middleware, 收到的请求体字典)，用于断言放行是否生效。"""
    received = {}

    async def downstream(_scope, receive, send):
        received["body"] = (await receive()).get("body", b"")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = RequestContextMiddleware(
        downstream,
        max_body_bytes=4,
        larger_body_paths={"/api/settings/backup/upload": 64},
    )
    return middleware, received


async def test_larger_body_path_accepts_a_body_over_the_default_limit():
    middleware, received = _echo_body_middleware()
    sent = await _collect_response(
        middleware,
        _scope_at("/api/settings/backup/upload", [(b"content-length", b"8")]),
        [{"type": "http.request", "body": b"12345678", "more_body": False}],
    )

    assert sent[0]["status"] == 200
    assert received["body"] == b"12345678"


async def test_larger_body_path_does_not_apply_to_a_sibling_path():
    """前缀匹配会让 upload-xxx 这类路径静默继承放宽的额度，必须精确匹配。"""
    middleware, _received = _echo_body_middleware()
    sent = await _collect_response(
        middleware,
        _scope_at("/api/settings/backup/upload-extra", [(b"content-length", b"8")]),
        [],
    )

    assert sent[0]["status"] == 413


async def test_larger_body_path_tolerates_a_trailing_slash():
    middleware, received = _echo_body_middleware()
    sent = await _collect_response(
        middleware,
        _scope_at("/api/settings/backup/upload/", [(b"content-length", b"8")]),
        [{"type": "http.request", "body": b"12345678", "more_body": False}],
    )

    assert sent[0]["status"] == 200
    assert received["body"] == b"12345678"
