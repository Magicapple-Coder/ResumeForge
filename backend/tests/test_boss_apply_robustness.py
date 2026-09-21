"""投递健壮性：窗口可见性保障与「聊天页开在新标签页」的收养。

两条都是 2026-09-20 真实投递失败换来的修复，并用真实浏览器复现验证过：

1. 窗口最小化 / 被遮挡时页面 ``visibilityState`` 为 ``hidden``，BOSS 对这种页面上的
   可信点击**静默忽略**（事件以 isTrusted=true 到达按钮，页面毫无反应），投递最终在
   "等聊天输入框"上超时。修复：每次可信点击前先 ``ensure_page_visible``。
2. 点击「立即沟通」后聊天页可能开在**新标签页**，原标签页停在岗位详情。修复：等待
   循环比对点击前后的标签页快照，把**新出现**的聊天标签页收养为后续填写/发送的目标；
   点击前就存在的聊天标签页（可能是用户自己开着的旧会话）绝不能碰。
"""
from __future__ import annotations

import pytest

from app.services.browser.cdp_client import CdpClient, CdpError
from app.services.browser.page_ready import ReadyWait
from app.services.apply.task_runner import StopAwareCdpClient
from app.services.sites.boss import BossAdapter
from app.services.sites.boss_apply import _chat_state_script

FAST_WAIT = ReadyWait(timeout=0.05, poll_interval=0.001)

JOB_URL = "https://www.zhipin.com/job_detail/new.html"
CHAT_URL = "https://www.zhipin.com/web/geek/chat"
GREETING = "您好（测试）"


def _chat_state(**overrides):
    state = {
        "on_chat": True,
        "input_found": True,
        "found": True,
        "kind": "contenteditable",
        "position": "后端开发",
        "name": "成女士",
        "url": CHAT_URL,
        "title": "聊天",
    }
    state.update(overrides)
    return state


class RobustFakeClient(CdpClient):
    """可控的假 CDP 客户端：能模拟窗口可见性与标签页集合的变化。"""

    def __init__(self, *, chat_tab: dict | None = None):
        self.visible_state = "hidden"
        self.window_state = "minimized"
        self.ensure_calls = 0
        self.switched_to: str | None = None
        self.targets: list[dict] = [
            {"id": "tab-detail", "type": "page", "url": JOB_URL, "webSocketDebuggerUrl": "ws://x"}
        ]
        if chat_tab is not None:
            self.targets.append(chat_tab)
        # evaluate 分派：默认返回详情页上的聊天状态（input_found=False，逼等待循环走收养）。
        self.chat_responses: list[dict] = [
            _chat_state(input_found=False, on_chat=False, url=JOB_URL),
            _chat_state(input_found=False, on_chat=False, url=JOB_URL),
        ]
        self.evaluate_calls = 0

    # ---- CdpClient 协议 ----
    def list_targets(self):
        return [dict(t) for t in self.targets]

    def new_tab(self, url: str = "about:blank") -> str:
        return "tab"

    def send(self, method, params=None, *, timeout=None):
        if method == "Browser.getWindowForTarget":
            return {"windowId": 1, "bounds": {"windowState": self.window_state}}
        if method == "Browser.setWindowBounds":
            self.window_state = (params or {}).get("bounds", {}).get(
                "windowState", self.window_state
            )
            if self.window_state == "normal":
                self.visible_state = "visible"
            return {}
        return {}

    def evaluate(self, expression, *, timeout=None):
        self.evaluate_calls += 1
        if "visibilityState" in expression:
            return self.visible_state
        if _chat_state_script()[:40] in expression or "rf:chat-state" in expression:
            if self.chat_responses:
                return self.chat_responses.pop(0)
            return _chat_state(input_found=True)
        return None

    def close(self):
        return None

    # ---- 可选能力（与 WebsocketCdpClient 同名同语义）----
    def ensure_page_visible(self, *, timeout_seconds: float = 8.0) -> bool:
        self.ensure_calls += 1
        # 模拟真实修复路径：还原窗口后可见。
        self.window_state = "normal"
        self.visible_state = "visible"
        return True

    def switch_to_target(self, target_id: str) -> bool:
        if any(t.get("id") == target_id for t in self.targets):
            self.switched_to = target_id
            return True
        return False


def _adapter():
    return BossAdapter(ready_wait=FAST_WAIT)


def test_trusted_click_ensures_page_visible_first():
    """可信点击前必须先做窗口可见性保障——这是真实失败的第一根因。"""
    client = RobustFakeClient()
    client.visible_state = "hidden"
    client.window_state = "minimized"
    adapter = _adapter()
    adapter._trusted_click(client, 10.0, 20.0)

    assert client.ensure_calls == 1
    assert client.visible_state == "visible"


def test_ensure_failure_does_not_kill_click():
    """无法还原窗口（无头/远程会话）只降级为"继续点击"，不抛异常。"""

    class NeverVisible(RobustFakeClient):
        def ensure_page_visible(self, *, timeout_seconds: float = 8.0) -> bool:
            self.ensure_calls += 1
            return False

    client = NeverVisible()
    adapter = _adapter()
    # 不抛即通过；点击事件仍然发出。
    adapter._trusted_click(client, 1.0, 2.0)
    assert client.ensure_calls == 1


def test_chat_tab_opened_after_click_is_adopted():
    """点击后新出现的聊天标签页要被收养：等待循环切换过去后读到聊天输入框。"""
    client = RobustFakeClient()
    adapter = _adapter()
    known = {t["id"] for t in client.targets}
    # 模拟"点击后"浏览器里新出现一个聊天标签页（不在点击前快照里）。
    client.targets.append(
        {
            "id": "tab-chat-new",
            "type": "page",
            "url": CHAT_URL,
            "webSocketDebuggerUrl": "ws://chat",
        }
    )

    state = adapter._wait_chat_ready(client, known_page_ids=known)

    # 收养动作发生了，并且等待循环最终在（切换后的）聊天页上读到了输入框。
    assert client.switched_to == "tab-chat-new"
    assert state.get("input_found") is True
    # 收养判定本身：新标签页就是候选。
    assert adapter._new_chat_tab_id(client, known) == "tab-chat-new"


def test_preexisting_chat_tab_is_never_adopted():
    """点击前就存在的聊天标签页绝不能收养——那可能是用户开着的旧会话。"""
    client = RobustFakeClient(
        chat_tab={
            "id": "tab-chat-old",
            "type": "page",
            "url": CHAT_URL,
            "webSocketDebuggerUrl": "ws://old",
        }
    )
    adapter = _adapter()
    known = {t["id"] for t in client.targets}
    assert "tab-chat-old" in known
    assert adapter._new_chat_tab_id(client, known) == ""


def test_switch_to_target_requires_known_id():
    client = RobustFakeClient()
    assert client.switch_to_target("nope") is False
    assert client.switch_to_target("tab-detail") is True


# ===== StopAwareCdpClient 的转发 =====


class StopProbe:
    def __init__(self):
        self.checked = 0

    def __call__(self):
        self.checked += 1


def _make_stop_aware(inner):
    return StopAwareCdpClient(inner, lambda: None)


def test_stop_aware_forwards_visibility_and_switch():
    inner = RobustFakeClient()
    wrapped = _make_stop_aware(inner)
    assert wrapped.ensure_page_visible() is True
    assert wrapped.switch_to_target("tab-detail") is True
    assert inner.switched_to == "tab-detail"


class BareClient(CdpClient):
    """没有可选能力的最小客户端：转发必须安全降级为 False。"""

    def list_targets(self):
        return []

    def new_tab(self, url="about:blank"):
        return ""

    def send(self, method, params=None, *, timeout=None):
        return {}

    def evaluate(self, expression, *, timeout=None):
        return None


def test_stop_aware_degrades_without_optional_capability():
    wrapped = _make_stop_aware(BareClient())
    assert wrapped.ensure_page_visible() is False
    assert wrapped.switch_to_target("x") is False


def test_stop_aware_checkpoint_blocks_during_pause():
    class PausedProbe:
        def __init__(self):
            self.calls = 0

        def __call__(self):
            self.calls += 1
            raise CdpError("stop")  # 用异常表达"检查点要求停止"的极端情形

    # checkpoint 抛异常时，转发层应原样抛出（StopAwareCdpClient 不吞停止信号）。
    inner = BareClient()
    wrapped = StopAwareCdpClient(inner, lambda: (_ for _ in ()).throw(CdpError("stop")))
    with pytest.raises(CdpError):
        wrapped.ensure_page_visible()
