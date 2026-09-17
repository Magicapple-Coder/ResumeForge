"""页面"可用于采集/投递"的通用等待原语。

**为什么需要它**：``Page.navigate`` / 打开新标签页只是让浏览器**开始**加载地址，调用返回时
文档往往还是空的。如果紧接着就在空白文档上跑采集脚本，``querySelectorAll`` 会匹配 0 个元素，
脚本返回空列表——于是"什么都没做"被伪装成"采集完成"。本模块把"等页面真的可以用了"收敛成
一个可复用的轮询原语，避免每个站点方法各写一遍、各漏一遍。

设计取舍：

- **站点无关**。它不认识任何选择器、不依赖 ``SiteFailure``——只按调用方给的四个回调运转：
  ``probe``（拉一次页面状态）、``is_ready``（够了没）、``blocker``（出现拦截就立刻失败）、
  ``on_timeout``（超时算什么失败）。这样它既能被 BOSS 的两个采集方法复用，又能被未来的站点
  复用，还能纯离线测。
- **唯一的失败时限是超时**。本原语不认识"页面已加载完成"意味着什么——SPA（如 BOSS 直聘）的
  岗位卡片常在文档 ``readyState === 'complete'`` **之后**才由异步请求渲染出来。若拿
  ``readyState`` 当"内容该出来了、再没有就是选择器失效"的证据，首屏稍慢（哪怕只慢过一两个
  轮询间隔）就会在真实站点上误报"页面结构可能已变化"而失败。因此：就绪与否**只**由调用方的
  ``is_ready`` 判定；``blocker`` 只负责"出现登录失效 / 验证码就**立刻**失败"这条快速路径；
  其余情况一律等满 ``timeout``，再由 ``on_timeout`` 按当时观测到的证据给出诊断。
- **可被"停止"打断**。每一轮轮询都会调用 ``probe``，而 ``probe`` 走的是 CDP 客户端
  （外层 ``StopAwareCdpClient`` 会在每次 CDP 调用前插停止检查点）；两次轮询之间只睡一个很短的
  轮询间隔，绝不用一个长 ``time.sleep`` 把用户点的"停止"堵在外面。
- **超时/间隔可配置**。参数集中在 ``ReadyWait``，默认值合理，绝不写死在业务分支里。
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# 默认等待参数：给足弱网下首屏（及 SPA 在 complete 之后的异步渲染）出内容的时间。这是**唯一**
# 的失败预算——超时后由调用方按证据报错。
PAGE_READY_TIMEOUT_SECONDS = 15.0
PAGE_READY_POLL_INTERVAL_SECONDS = 0.4


@dataclass(frozen=True)
class ReadyWait:
    """一次等待的超时与轮询间隔（秒）。

    ``timeout`` 是**唯一**的失败时限（``blocker`` 命中的快速路径除外）：内容可能在文档
    ``complete`` 之后很久才异步渲染出来，所以这里只给一个整体预算——默认 15s 是"等首屏 XHR
    把卡片渲染出来"的预算，可随站点 / 网络调整；不做任何基于 ``readyState`` 的提前失败。
    """

    timeout: float = PAGE_READY_TIMEOUT_SECONDS
    poll_interval: float = PAGE_READY_POLL_INTERVAL_SECONDS


def _coerce_state(value: Any) -> dict[str, Any]:
    """页面脚本可能返回 None / 非 dict，统一收敛成 dict（未就绪）。"""
    return value if isinstance(value, dict) else {}


def wait_for_page_state(
    probe: Callable[[], Any],
    *,
    is_ready: Callable[[dict[str, Any]], bool],
    on_timeout: Callable[[dict[str, Any]], Exception],
    blocker: Callable[[dict[str, Any]], Exception | None] | None = None,
    config: ReadyWait | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """轮询 ``probe`` 直到就绪、被拦截或超时。

    这里**只**有三种结束方式，且都与 ``readyState`` 无关：

    1. ``is_ready(state)`` 为真 → 立即返回该状态（页面已可用于采集/投递）；
    2. ``blocker(state)`` 返回异常 → 立即抛出（登录失效 / 验证码，不傻等满超时）；
    3. 等到 ``timeout`` 仍未就绪 → 由 ``on_timeout(state)`` 构造异常抛出。

    之所以不给"页面已 complete 却仍无内容"加一条提前失败：SPA 的内容是在 ``complete``
    **之后**异步渲染的，那样做会在首屏稍慢时误报失败（把"还没渲染"当成"选择器失效"）。

    Args:
        probe: 拉取一次当前页面状态并返回 dict 的回调（通常会走一次 CDP 调用 → 停止检查点）。
        is_ready: 状态是否已满足"可用于采集/投递"。
        on_timeout: 超时时构造要抛出的异常（带可操作诊断）。
        blocker: 可选。返回一个异常表示"出现拦截（登录失效 / 验证码）"——**立刻**抛出，
            不傻等满超时。
        config: 等待参数（超时 / 轮询间隔）。
        sleeper / clock: 便于离线测试注入。

    Returns:
        最后一次观测到的状态 dict（就绪时）。

    Raises:
        由 ``blocker`` 返回的异常、或超时时由 ``on_timeout`` 构造的异常。
        ``probe`` 自身抛出的异常（如 ``TaskStopped`` / ``CdpError``）原样向上传播。
    """
    wait = config or ReadyWait()
    interval = max(wait.poll_interval, 0.0)
    deadline = clock() + max(wait.timeout, 0.0)
    state: dict[str, Any] = {}
    while True:
        state = _coerce_state(probe())  # 这一步通常是一次 CDP 调用 → 停止检查点
        if blocker is not None:
            failure = blocker(state)
            if failure is not None:
                raise failure
        if is_ready(state):
            return state
        remaining = deadline - clock()
        if remaining <= 0:
            raise on_timeout(state)
        sleep_for = min(interval, remaining) if interval > 0 else remaining
        if sleep_for > 0:
            sleeper(sleep_for)


__all__ = [
    "PAGE_READY_POLL_INTERVAL_SECONDS",
    "PAGE_READY_TIMEOUT_SECONDS",
    "ReadyWait",
    "wait_for_page_state",
]
