"""CDP 客户端：用 HTTP 端点 + WebSocket 与"投递专用浏览器"对话。

设计要点（决定了它为什么长这样）：

- **传输层可注入**。``WebsocketCdpClient`` 的 HTTP 走既有 ``httpx``，WebSocket 走
  ``websocket-client``；两者都通过构造参数注入（``http_transport`` / ``websocket_factory``），
  于是测试可以用假的传输层把整条链路离线跑起来，不启动真浏览器、不发真 CDP——这与
  LLM 层 ``create_provider(transport=httpx.MockTransport(...))`` 是同一个离线注入点思路。
- **所有调用都有超时**，异常统一收敛成 ``CdpError``，其 message 就是给用户看的中文提示。
- 只连**后端自己用独立 ``user-data-dir`` 拉起的那个浏览器**：Chrome 136+ 禁止在默认用户
  数据目录上开远程调试端口，所以不去碰用户日常浏览器。
"""
from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_COMMAND_TIMEOUT = 30.0
DEFAULT_HTTP_TIMEOUT = 5.0
_MAX_FRAMES_PER_COMMAND = 5000


class CdpError(Exception):
    """对外暴露的 CDP 调用错误，message 为可直接展示给用户的中文提示。"""


class CdpClient(ABC):
    """页面级 CDP 客户端接口。

    业务层只依赖本抽象，不感知 HTTP / WebSocket 细节，因此可以用 ``FakeCdpClient``
    在离线测试里替换掉整条对外链路。
    """

    @abstractmethod
    def list_targets(self) -> list[dict[str, Any]]:
        """列出浏览器里当前的调试目标（标签页 / 页面）。"""

    @abstractmethod
    def new_tab(self, url: str = "about:blank") -> str:
        """新建一个标签页并把它设为后续命令的目标，返回目标 id。"""

    @abstractmethod
    def send(
        self, method: str, params: dict[str, Any] | None = None, *, timeout: float | None = None
    ) -> dict[str, Any]:
        """发送一条 CDP 命令并返回其 ``result``。"""

    @abstractmethod
    def evaluate(self, expression: str, *, timeout: float | None = None) -> Any:
        """在页面里执行一段脚本并返回按值传递的结果。"""

    # 事件订阅是**可选能力**，所以默认实现是"不支持"而不是 abstractmethod：
    # 站点适配器据此退回 DOM 解析（那本来就是保留的兜底路径），而假客户端与
    # 只做简单操作的实现不必为了满足抽象基类去写三个空方法。
    def start_event_capture(self, methods: Sequence[str]) -> None:
        """开始收集指定 CDP 方法的事件帧；不支持时什么都不做。"""
        return None

    def stop_event_capture(self) -> None:
        return None

    def drain_events(self) -> list[dict[str, Any]]:
        return []

    def close(self) -> None:
        """关闭底层连接（不关闭浏览器进程）。"""


def _default_websocket_factory(url: str) -> Any:
    """默认的 WebSocket 连接工厂。

    延迟导入 ``websocket``：只有真正需要连浏览器时才会用到它，模块导入本身不依赖它
    （离线测试注入假工厂时根本不走这里）。
    """
    import websocket  # 局部导入：作为可选的重运行时依赖

    # suppress_origin=True：Chrome 会按 Origin 头做同源校验，不带 Origin 最省事。
    return websocket.create_connection(
        url, timeout=DEFAULT_CONNECT_TIMEOUT, suppress_origin=True
    )


class WindowAwareMixin:
    """窗口可见性保障与标签页切换：只在 ``WebsocketCdpClient`` 上实现。

    **为什么需要**（2026-09-20 真实投递失败的根因）：浏览器窗口被最小化 / 遮挡 /
    放在未激活的虚拟桌面上时，页面的 ``document.visibilityState`` 是 ``"hidden"``；
    BOSS 直聘对隐藏页面上的点击**静默忽略**（真实用户不可能点击看不见的页面——这是
    它的反自动化启发式之一）。而 ``Page.bringToFront`` 只能在窗口内部切标签页，
    **不能还原最小化的窗口**，所以点击前必须走 ``Browser.setWindowBounds``。

    实测有效的还原顺序：先按窗口当前状态处理（最小化 → 还原成 normal），再
    ``Page.bringToFront``；若仍不可见，用「最小化 → 还原」切换强制 Windows 重新
    激活窗口（对被完全遮挡、位于其他虚拟桌面的窗口同样有效）。
    """

    _VISIBILITY_PROBE = 'document.visibilityState || "unknown"'

    def ensure_page_visible(self, *, timeout_seconds: float = 8.0) -> bool:
        """确保当前标签页所在窗口可见，返回最终是否 ``visible``。

        失败**不抛异常**、只返回 False：个别环境（无头、远程会话）确实无法还原窗口，
        此时上层流程按原样继续——等待与超时诊断仍然有效，只是把"为什么点不动"这句
        话提前写进日志，而不是让用户面对一条莫名的选择器超时。

        还原手段按强度递增（2026-09-20 实测排序）：
        1. ``Target.activateTarget``——**一步就能把最小化/被遮挡窗口还原并前置**（实测
           ``windowState=minimized`` 下也生效），首选；
        2. 最小化 → ``setWindowBounds(normal)`` 还原；
        3. 「最小化 → 还原」切换强制 Windows 重新激活（对位于其他虚拟桌面的窗口有效）；
        4. ``Page.bringToFront`` 收尾。
        """
        deadline = time.monotonic() + max(timeout_seconds, 0.0)
        last_state = ""
        target_id = str((self._target or {}).get("id", "") or "")
        try:
            self.send("Page.enable")
        except CdpError:
            return False

        def _activate() -> None:
            if target_id:
                try:
                    self.send("Target.activateTarget", {"targetId": target_id})
                except CdpError:
                    pass

        while True:
            try:
                last_state = str(self.evaluate(self._VISIBILITY_PROBE) or "")
                if last_state == "visible":
                    return True
                _activate()
                if str(self.evaluate(self._VISIBILITY_PROBE) or "") == "visible":
                    return True
                window = self.send("Browser.getWindowForTarget")
                window_id = window.get("windowId")
                bounds = window.get("bounds") or {}
                if not window_id:
                    return False
                if bounds.get("windowState") == "minimized":
                    # 最小化：还原即可。
                    self.send(
                        "Browser.setWindowBounds",
                        {"windowId": window_id, "bounds": {"windowState": "normal"}},
                    )
                else:
                    # 被遮挡 / 在未激活的虚拟桌面：最小化→还原切换一次，
                    # 强制窗口管理器重新激活（activateTarget 对这种情况可能无效）。
                    self.send(
                        "Browser.setWindowBounds",
                        {"windowId": window_id, "bounds": {"windowState": "minimized"}},
                    )
                    time.sleep(0.3)
                    self.send(
                        "Browser.setWindowBounds",
                        {"windowId": window_id, "bounds": {"windowState": "normal"}},
                    )
                _activate()
                try:
                    self.send("Page.bringToFront")
                except CdpError:
                    pass
            except CdpError as exc:
                logger.debug("窗口可见性保障失败：%s", exc)
                return False
            if time.monotonic() >= deadline:
                return last_state == "visible"
            time.sleep(0.5)

    def switch_to_target(self, target_id: str) -> bool:
        """把后续命令切换到另一个标签页；切换失败返回 False（调用方自行决定回退）。

        用途：点击岗位页的「立即沟通」后，聊天页**可能开在新标签页**而不是整页跳转。
        调用方先比对 ``list_targets()`` 的前后快照找出新出现的聊天标签页，再切换过去，
        后续填写 / 发送就落在正确的页面上。
        """
        wanted = str(target_id or "").strip()
        if not wanted:
            return False
        try:
            targets = self.list_targets()
        except CdpError:
            return False
        target = next(
            (
                item
                for item in targets
                if item.get("type") == "page" and str(item.get("id", "")) == wanted
            ),
            None,
        )
        if target is None or not target.get("webSocketDebuggerUrl"):
            return False
        current_id = str((self._target or {}).get("id", ""))
        if current_id == wanted and self._connection is not None:
            return True
        self._target = target
        # 目标变了，旧 WebSocket 必须重连（与 new_tab 同一套纪律）。
        self._reset_connection()
        try:
            self._connection_handle()
        except CdpError:
            return False
        return True


class WebsocketCdpClient(WindowAwareMixin, CdpClient):
    """基于 HTTP 端点 + WebSocket 通道的 CDP 客户端实现。"""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = 0,
        *,
        http_transport: httpx.BaseTransport | None = None,
        websocket_factory: Callable[[str], Any] | None = None,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        command_timeout: float = DEFAULT_COMMAND_TIMEOUT,
        http_timeout: float = DEFAULT_HTTP_TIMEOUT,
    ) -> None:
        self._host = host
        self._port = port
        self._http_transport = http_transport
        self._websocket_factory = websocket_factory or _default_websocket_factory
        self._connect_timeout = connect_timeout
        self._command_timeout = command_timeout
        self._http_timeout = http_timeout
        self._target: dict[str, Any] | None = None
        self._connection: Any | None = None
        # 事件收集：见 start_event_capture 的说明。
        self._capture_methods: set[str] = set()
        self._captured_events: list[dict[str, Any]] = []
        self._command_id = 0

    # ===== 浏览器级端点（HTTP）=====

    def _base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    def _request(self, method: str, path: str) -> httpx.Response:
        try:
            with httpx.Client(
                transport=self._http_transport, timeout=self._http_timeout
            ) as client:
                return client.request(method, f"{self._base_url()}{path}")
        except httpx.TimeoutException as exc:
            raise CdpError("连接投递专用浏览器超时，请确认浏览器已启动且未被安全软件拦截") from exc
        except httpx.RequestError as exc:
            raise CdpError("无法连接投递专用浏览器，请先在投递台点击「启动浏览器」") from exc

    @staticmethod
    def _decode(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise CdpError("投递专用浏览器返回了无法解析的响应") from exc

    def list_targets(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/json/list")
        if response.status_code != 200:
            raise CdpError(f"读取浏览器标签页失败（HTTP {response.status_code}）")
        payload = self._decode(response)
        if not isinstance(payload, list):
            raise CdpError("投递专用浏览器返回了无法解析的响应")
        return [item for item in payload if isinstance(item, dict)]

    def new_tab(self, url: str = "about:blank") -> str:
        # Chrome 111+ 要求用 PUT 打开新标签页，旧版本只认 GET；先 PUT，405 再退 GET。
        path = f"/json/new?{quote(url, safe='')}"
        response = self._request("PUT", path)
        if response.status_code == 405:
            response = self._request("GET", path)
        if response.status_code != 200:
            raise CdpError(f"打开新标签页失败（HTTP {response.status_code}）")
        target = self._decode(response)
        if not isinstance(target, dict):
            raise CdpError("投递专用浏览器返回了无法解析的响应")
        self._target = target
        # 目标变了，旧的 WebSocket 连接不再可用。
        self._reset_connection()
        return str(target.get("id", ""))

    # ===== 页面级通道（WebSocket）=====

    def _websocket_url(self) -> str:
        target = self._target
        if target is None or not target.get("webSocketDebuggerUrl"):
            targets = self.list_targets()
            page = next(
                (
                    item
                    for item in targets
                    if item.get("type") == "page" and item.get("webSocketDebuggerUrl")
                ),
                None,
            )
            if page is None:
                raise CdpError("没有可用的浏览器页面，请先在投递台启动浏览器并打开一个标签页")
            target = page
            self._target = page
        url = target.get("webSocketDebuggerUrl")
        if not url:
            raise CdpError("当前标签页没有可用的调试通道")
        return str(url)

    def _connection_handle(self) -> Any:
        if self._connection is not None:
            return self._connection
        url = self._websocket_url()
        try:
            connection = self._websocket_factory(url)
        except CdpError:
            raise
        except Exception as exc:  # noqa: BLE001 - 传输层异常统一收敛为可展示的中文提示
            raise CdpError("无法连接投递专用浏览器的调试通道，请确认浏览器仍在运行") from exc
        self._connection = connection
        return connection

    def _reset_connection(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:  # noqa: BLE001 - 关闭失败不该阻断后续流程
                pass
        self._connection = None

    def send(
        self, method: str, params: dict[str, Any] | None = None, *, timeout: float | None = None
    ) -> dict[str, Any]:
        connection = self._connection_handle()
        self._command_id += 1
        command_id = self._command_id
        payload: dict[str, Any] = {"id": command_id, "method": method}
        if params:
            payload["params"] = params
        effective_timeout = timeout if timeout is not None else self._command_timeout
        if hasattr(connection, "settimeout"):
            connection.settimeout(effective_timeout)
        try:
            connection.send(json.dumps(payload, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            self._reset_connection()
            raise CdpError(f"CDP 命令 {method} 发送失败，连接可能已断开") from exc

        deadline = time.monotonic() + effective_timeout
        for _ in range(_MAX_FRAMES_PER_COMMAND):
            if time.monotonic() > deadline:
                raise CdpError(f"CDP 命令 {method} 超时，请确认浏览器窗口没有被阻塞")
            try:
                frame = connection.recv()
            except Exception as exc:  # noqa: BLE001
                self._reset_connection()
                raise CdpError(f"CDP 命令 {method} 收发失败或超时，请确认浏览器仍在运行") from exc
            if frame is None or frame == "":
                self._reset_connection()
                raise CdpError(f"CDP 连接在等待 {method} 结果时被关闭")
            try:
                message = json.loads(frame)
            except (ValueError, TypeError) as exc:
                raise CdpError("投递专用浏览器返回了无法解析的响应") from exc
            if not isinstance(message, dict):
                raise CdpError("投递专用浏览器返回了无法解析的响应")
            if message.get("id") != command_id:
                # 事件帧（没有对应命令 id）。订阅中的那些要攒起来——"网络响应优先"
                # 正是靠它们工作的；其余的直接跳过。
                self._capture(message)
                continue
            if "error" in message:
                error = message.get("error") or {}
                detail = error.get("message", "未知错误") if isinstance(error, dict) else str(error)
                raise CdpError(f"CDP 命令 {method} 被页面拒绝：{detail}")
            result = message.get("result")
            return result if isinstance(result, dict) else {}
        raise CdpError(f"CDP 命令 {method} 收到过多无关消息，已中止")

    def evaluate(self, expression: str, *, timeout: float | None = None) -> Any:
        result = self.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
            timeout=timeout,
        )
        if result.get("exceptionDetails"):
            raise CdpError("页面脚本执行出错，可能页面结构已变化")
        inner = result.get("result")
        if not isinstance(inner, dict):
            return None
        return inner.get("value")

    def navigate(self, url: str, *, timeout: float | None = None) -> dict[str, Any]:
        return self.send("Page.navigate", {"url": url}, timeout=timeout)

    def start_event_capture(self, methods: Sequence[str]) -> None:
        """开始收集指定 CDP 方法的事件帧，直到 :meth:`stop_event_capture`。

        用途是"**网络响应优先，DOM 兜底**"：招聘网站的岗位列表与详情都是 XHR 渲染的，
        直接读接口响应比解析 DOM 稳得多（不受渲染时序、字体反爬和改版影响）。但 CDP 的
        事件是异步推送的，而本客户端是**同步收发**模型，所以这里用"先订阅、再攒帧"：
        ``send`` 期间收到的非命令帧被存进缓冲区，命令结束后由 ``drain_events`` 取走。

        参数必须是站点自己关心的那几个方法（例如 ``Network.responseReceived``），
        而不是全部——把所有事件都攒下来会让缓冲区迅速膨胀，还会拖慢每一次命令。
        """
        self._capture_methods = set(methods)
        self._captured_events = []
        for method in methods:
            # Network / Page 等域的启用是幂等的，重复调用不会报错。
            domain = method.split(".", 1)[0]
            try:
                self.send(f"{domain}.enable")
            except CdpError:
                # 个别域（例如某些内核不支持的）启用失败不该让整个采集失败——
                # 订阅不到就退回 DOM 解析，那本来就是我们保留的兜底路径。
                logger.debug("CDP 域 %s 启用失败，将退回 DOM 解析", domain)

    def stop_event_capture(self) -> None:
        """停止收集，**并清掉已攒下的帧**。

        因此调用方必须**先** :meth:`drain_events` **再**停止——反过来会把已经拦到的响应
        一起丢掉，而丢掉的后果是安静地退回 DOM 解析，从外面看不出来。
        """
        self._capture_methods = set()
        self._captured_events = []

    def drain_events(self) -> list[dict[str, Any]]:
        """取走并清空已收集的事件帧。"""
        events = self._captured_events
        self._captured_events = []
        return events

    def _capture(self, message: dict[str, Any]) -> bool:
        """命令期间收到的事件帧；是本客户端关心的就攒起来，返回是否已消费。"""
        method = message.get("method")
        if not method or method not in self._capture_methods:
            return False
        self._captured_events.append(message)
        return True

    def set_file_input(
        self, selector: str, files: list[str], *, timeout: float | None = None
    ) -> None:
        """把本地文件塞进一个 ``<input type="file">``（用于上传简历 PDF）。

        JS 出于安全不允许直接给文件输入框赋值，只能用 ``DOM.setFileInputFiles``，
        而它需要一个节点句柄——所以先用 ``Runtime.evaluate`` 拿到 objectId。
        """
        result = self.send(
            "Runtime.evaluate",
            {
                "expression": f"document.querySelector({json.dumps(selector)})",
                "returnByValue": False,
            },
            timeout=timeout,
        )
        object_id = (result.get("result") or {}).get("objectId")
        if not object_id:
            raise CdpError("页面上没有找到简历上传控件，可能页面结构已变化")
        self.send(
            "DOM.setFileInputFiles",
            {"files": list(files), "objectId": object_id},
            timeout=timeout,
        )

    def close(self) -> None:
        self._reset_connection()


__all__ = [
    "CdpClient",
    "CdpError",
    "DEFAULT_COMMAND_TIMEOUT",
    "DEFAULT_CONNECT_TIMEOUT",
    "DEFAULT_HOST",
    "WebsocketCdpClient",
    "WindowAwareMixin",
]
