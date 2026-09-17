"""页面就绪等待原语的离线测试：就绪 / 拦截 / 超时 / 可中断。

这些用例直接驱动 ``wait_for_page_state``，不碰任何浏览器或网络：``probe`` 是普通回调，
``sleeper`` 被替换成"不动时钟"的空实现，``clock`` 用可控的假时钟，于是整个等待逻辑
（含超时与轮询）都能在毫秒级跑完。
"""
from __future__ import annotations

import pytest

from app.services.browser.page_ready import ReadyWait, wait_for_page_state


class _Clock:
    """可控时钟：每次读取推进固定步长，让循环按预期次数推进。"""

    def __init__(self, step: float = 1.0) -> None:
        self._t = 0.0
        self._step = step

    def __call__(self) -> float:
        current = self._t
        self._t += self._step
        return current


def _noop_sleep(_seconds: float) -> None:
    return None


def test_returns_immediately_when_already_ready():
    states = [{"matched": 3}]
    calls = {"n": 0}

    def probe():
        calls["n"] += 1
        return states[0]

    result = wait_for_page_state(
        probe,
        is_ready=lambda state: state.get("matched", 0) > 0,
        on_timeout=lambda _state: AssertionError("不应超时"),
        config=ReadyWait(timeout=10, poll_interval=0.1),
        sleeper=_noop_sleep,
        clock=_Clock(),
    )

    assert result == {"matched": 3}
    assert calls["n"] == 1


def test_polls_until_ready_then_returns():
    states = [{"matched": 0}, {"matched": 0}, {"matched": 2}]
    index = {"i": 0}

    def probe():
        value = states[min(index["i"], len(states) - 1)]
        index["i"] += 1
        return value

    result = wait_for_page_state(
        probe,
        is_ready=lambda state: state.get("matched", 0) > 0,
        on_timeout=lambda _state: AssertionError("不应超时"),
        config=ReadyWait(timeout=100, poll_interval=0.1),
        sleeper=_noop_sleep,
        clock=_Clock(),
    )

    assert result["matched"] == 2
    assert index["i"] == 3


def test_complete_ready_state_does_not_fail_early_but_keeps_polling():
    """``readyState === 'complete'`` 不得被当成"内容该出来了、再没有就失败"。

    它只说明**文档与静态资源**加载完；SPA（如 BOSS 直聘）的岗位卡片是在 ``complete``
    **之后**由异步请求渲染的。原语必须继续轮询到就绪（这里第 4 次才出内容），而不是在
    第 1 次看到 complete 就提前失败。
    """
    sequence = [
        {"ready_state": "complete", "matched": 0},
        {"ready_state": "complete", "matched": 0},
        {"ready_state": "complete", "matched": 0},
        {"ready_state": "complete", "matched": 2},  # complete 之后异步渲染出的内容
    ]
    index = {"i": 0}

    def probe():
        value = sequence[min(index["i"], len(sequence) - 1)]
        index["i"] += 1
        return value

    result = wait_for_page_state(
        probe,
        is_ready=lambda state: state.get("matched", 0) > 0,
        on_timeout=lambda _state: AssertionError("不应在内容到达前失败"),
        config=ReadyWait(timeout=100, poll_interval=0.1),
        sleeper=_noop_sleep,
        clock=_Clock(),
    )

    assert result["matched"] == 2
    assert index["i"] == 4  # 前三次 complete 没有触发失败，直到第 4 次就绪


def test_raises_the_blocker_exception_as_soon_as_it_appears():
    """出现拦截时立刻抛出，不傻等到超时。"""
    seen = {"polls": 0}

    def probe():
        seen["polls"] += 1
        return {"matched": 0, "captcha": True}

    with pytest.raises(RuntimeError, match="验证码"):
        wait_for_page_state(
            probe,
            is_ready=lambda _state: False,
            blocker=lambda state: RuntimeError("需要验证码") if state.get("captcha") else None,
            on_timeout=lambda _state: AssertionError("不应超时"),
            config=ReadyWait(timeout=100, poll_interval=0.1),
            sleeper=_noop_sleep,
            clock=_Clock(),
        )

    assert seen["polls"] == 1


def test_raises_timeout_failure_after_the_deadline():
    with pytest.raises(TimeoutError, match="超时"):
        wait_for_page_state(
            lambda: {"matched": 0},
            is_ready=lambda _state: False,
            on_timeout=lambda _state: TimeoutError("等待超时"),
            config=ReadyWait(timeout=3, poll_interval=1),
            sleeper=_noop_sleep,
            clock=_Clock(step=1.0),
        )


class _Stopped(Exception):
    """模拟运行器在检查点抛出的 TaskStopped。"""


def test_probe_exceptions_propagate_for_stop_signal():
    """probe 抛出的异常（例如 TaskStopped）原样向上传播——这是"可被停止打断"的机制。"""

    def probe():
        raise _Stopped("stop")

    with pytest.raises(_Stopped):
        wait_for_page_state(
            probe,
            is_ready=lambda _state: False,
            on_timeout=lambda _state: AssertionError("不应走到这里"),
            config=ReadyWait(timeout=10, poll_interval=0.1),
            sleeper=_noop_sleep,
            clock=_Clock(),
        )


def test_non_dict_probe_result_is_treated_as_not_ready():
    sequence = [None, "oops", {"matched": 1}]
    index = {"i": 0}

    def probe():
        value = sequence[min(index["i"], len(sequence) - 1)]
        index["i"] += 1
        return value

    result = wait_for_page_state(
        probe,
        is_ready=lambda state: state.get("matched", 0) > 0,
        on_timeout=lambda _state: AssertionError("不应失败"),
        config=ReadyWait(timeout=100, poll_interval=0.1),
        sleeper=_noop_sleep,
        clock=_Clock(),
    )

    assert result["matched"] == 1
