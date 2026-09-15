"""Request correlation and bounded request-body handling."""
from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from contextvars import ContextVar
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_context: ContextVar[str] = ContextVar("request_id", default="-")


class _RequestTooLarge(Exception):
    pass


def get_request_id() -> str:
    return request_id_context.get()


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_context.get()
        return True


class RequestContextMiddleware:
    """Attach a request ID and reject bodies that exceed the configured limit.

    The receive wrapper enforces the limit even when a client omits Content-Length
    and streams chunks, so field-level validation cannot be bypassed with chunking.

    ``larger_body_paths`` raises the ceiling for specific path prefixes whose
    payloads are legitimately large (the data-backup upload streams straight to
    disk, so the body size costs no memory); every other path keeps the default.
    """

    def __init__(
        self,
        app: ASGIApp,
        max_body_bytes: int,
        *,
        larger_body_paths: Mapping[str, int] | None = None,
    ) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.larger_body_paths = dict(larger_body_paths or {})

    def _limit_for(self, scope: Scope) -> int:
        # 精确匹配而不是前缀匹配：前缀会让 /upload-extra 这类兄弟路径也静默拿到
        # 放宽的额度。归一化结尾斜杠，使 /upload/ 与 /upload 表现一致。
        path = scope.get("path", "").rstrip("/")
        return self.larger_body_paths.get(path, self.max_body_bytes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = self._request_id(scope)
        token = request_id_context.set(request_id)
        response_started = False
        max_body_bytes = self._limit_for(scope)

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            if self._declared_size(scope) > max_body_bytes:
                await self._send_too_large(send_with_request_id, max_body_bytes)
                return

            received = 0

            async def limited_receive() -> Message:
                nonlocal received
                message = await receive()
                if message["type"] == "http.request":
                    received += len(message.get("body", b""))
                    if received > max_body_bytes:
                        raise _RequestTooLarge
                return message

            try:
                await self.app(scope, limited_receive, send_with_request_id)
            except _RequestTooLarge:
                if response_started:
                    raise
                await self._send_too_large(send_with_request_id, max_body_bytes)
        finally:
            request_id_context.reset(token)

    @staticmethod
    def _request_id(_scope: Scope) -> str:
        # 请求 ID 用于日志关联，应由服务端生成，不能信任客户端提供的可伪造值。
        return uuid4().hex

    @staticmethod
    def _declared_size(scope: Scope) -> int:
        for name, value in scope.get("headers", []):
            if name.lower() != b"content-length":
                continue
            try:
                return max(0, int(value))
            except ValueError:
                return 0
        return 0

    async def _send_too_large(self, send: Send, max_body_bytes: int) -> None:
        body = json.dumps(
            {"detail": f"请求体过大，最大允许 {max_body_bytes // (1024 * 1024)} MB"},
            ensure_ascii=False,
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
