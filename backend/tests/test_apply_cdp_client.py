"""CDP 客户端离线测试：注入假的 HTTP 传输层与假的 WebSocket，不发真请求。

这正是"传输层可注入"的意义——整条 CDP 链路（端点解析、命令收发、超时、错误映射）
都能在没有浏览器、没有网络的情况下测到位。
"""
import json
from typing import Any

import httpx
import pytest

from app.services.browser.cdp_client import CdpError, WebsocketCdpClient

TARGET = {
    "id": "TAB-1",
    "type": "page",
    "webSocketDebuggerUrl": "ws://127.0.0.1:9333/devtools/page/TAB-1",
}


class FakeWebSocket:
    """假的 WebSocket 连接：把发出去的命令记下来，按脚本回帧。"""

    def __init__(self, responses: Any) -> None:
        self._responses = responses
        self._index = 0
        self.sent: list[dict] = []
        self.closed = False
        self.timeout: float | None = None

    def settimeout(self, value: float) -> None:
        self.timeout = value

    def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))

    def recv(self) -> str:
        if callable(self._responses):
            return self._responses(self.sent[-1])
        if self._index < len(self._responses):
            frame = self._responses[self._index]
            self._index += 1
            return frame
        return self._responses[-1]

    def close(self) -> None:
        self.closed = True


def _responder(results: dict[str, Any], errors: dict[str, dict] | None = None):
    def respond(command: dict) -> str:
        method = command.get("method", "")
        if errors and method in errors:
            return json.dumps({"id": command.get("id"), "error": errors[method]})
        return json.dumps({"id": command.get("id"), "result": results.get(method, {})})

    return respond


def _client(handler, ws: FakeWebSocket | None = None) -> WebsocketCdpClient:
    transport = httpx.MockTransport(handler)
    return WebsocketCdpClient(
        "127.0.0.1",
        9333,
        http_transport=transport,
        websocket_factory=(lambda _url: ws) if ws is not None else None,
    )


def _new_tab_handler(status: int = 200, payload: dict | None = None, calls: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append((request.method, request.url.path))
        if request.url.path == "/json/new":
            if request.method == "PUT" and status != 200:
                return httpx.Response(status)
            return httpx.Response(200, json=payload if payload is not None else TARGET)
        raise httpx.ConnectError("boom", request=request)

    return handler


def _client_with_ws(ws: FakeWebSocket) -> WebsocketCdpClient:
    client = _client(_new_tab_handler(), ws)
    client.new_tab("about:blank")
    return client


def test_list_targets_reads_the_http_endpoint():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/json/list"
        return httpx.Response(200, json=[TARGET, {"id": "TAB-2", "type": "other"}])

    assert _client(handler).list_targets()[0]["id"] == "TAB-1"


def test_new_tab_uses_put_then_falls_back_to_get():
    calls: list = []
    client = _client(_new_tab_handler(status=405, calls=calls))

    target_id = client.new_tab("https://www.example.com/job")

    assert target_id == "TAB-1"
    assert calls == [("PUT", "/json/new"), ("GET", "/json/new")]


def test_new_tab_rejects_a_non_200_response():
    client = _client(_new_tab_handler(status=500))

    with pytest.raises(CdpError, match="打开新标签页失败"):
        client.new_tab("about:blank")


def test_send_round_trips_a_command_over_the_websocket():
    ws = FakeWebSocket(_responder({"Runtime.evaluate": {"result": {"value": "hi"}}}))
    client = _client_with_ws(ws)

    result = client.send("Runtime.evaluate", {"expression": "1"})

    assert result == {"result": {"value": "hi"}}
    assert ws.sent[0]["method"] == "Runtime.evaluate"


def test_send_skips_event_frames_before_the_matching_reply():
    frames = [
        json.dumps({"method": "Page.loadEventFired", "params": {}}),
        json.dumps({"id": 1, "result": {"ok": True}}),
    ]
    client = _client_with_ws(FakeWebSocket(frames))

    assert client.send("Page.enable") == {"ok": True}


def test_send_maps_a_cdp_error_to_a_chinese_message():
    ws = FakeWebSocket(_responder({}, errors={"DOM.setFileInputFiles": {"message": "No node"}}))
    client = _client_with_ws(ws)

    with pytest.raises(CdpError, match="被页面拒绝"):
        client.send("DOM.setFileInputFiles", {})


def test_send_wraps_a_broken_connection_as_timeout_error():
    def broken(_command: dict) -> str:
        raise TimeoutError("no frame")

    client = _client_with_ws(FakeWebSocket(broken))

    with pytest.raises(CdpError, match="收发失败或超时"):
        client.send("Runtime.evaluate", {})


def test_send_rejects_an_unparseable_frame():
    client = _client_with_ws(FakeWebSocket(["this is not json"]))

    with pytest.raises(CdpError, match="无法解析"):
        client.send("Runtime.evaluate", {})


def test_evaluate_returns_the_value_and_rejects_page_exceptions():
    ws = FakeWebSocket(
        _responder({"Runtime.evaluate": {"result": {"value": 42}}})
    )
    assert _client_with_ws(ws).evaluate("1 + 41") == 42

    failing = FakeWebSocket(
        _responder({"Runtime.evaluate": {"exceptionDetails": {"text": "SyntaxError"}}})
    )
    with pytest.raises(CdpError, match="页面脚本执行出错"):
        _client_with_ws(failing).evaluate("!!!")


def test_http_endpoint_failure_is_reported_as_connection_hint():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(CdpError, match="无法连接投递专用浏览器"):
        _client(handler).list_targets()


def test_set_file_input_resolves_object_id_then_calls_dom_command():
    sent_methods: list[str] = []

    def responder(command: dict) -> str:
        sent_methods.append(command["method"])
        if command["method"] == "Runtime.evaluate":
            return json.dumps({"id": command["id"], "result": {"result": {"objectId": "OBJ-1"}}})
        return json.dumps({"id": command["id"], "result": {}})

    ws = FakeWebSocket(responder)
    _client_with_ws(ws).set_file_input("input[type=file]", ["/tmp/resume.pdf"])

    assert sent_methods == ["Runtime.evaluate", "DOM.setFileInputFiles"]
    assert ws.sent[1]["params"]["files"] == ["/tmp/resume.pdf"]
    assert ws.sent[1]["params"]["objectId"] == "OBJ-1"


def test_set_file_input_reports_a_missing_upload_control():
    ws = FakeWebSocket(_responder({"Runtime.evaluate": {"result": {}}}))
    client = _client_with_ws(ws)

    with pytest.raises(CdpError, match="上传控件"):
        client.set_file_input("input[type=file]", ["/tmp/resume.pdf"])


def test_close_closes_the_underlying_connection():
    ws = FakeWebSocket(_responder({"Page.enable": {}}))
    client = _client_with_ws(ws)
    client.send("Page.enable")  # 先建立连接

    client.close()

    assert ws.closed is True
