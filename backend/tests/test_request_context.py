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
