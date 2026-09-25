"""官网采集的后台执行：任务登记、停止信号、关闭收尾。

**为什么必须有它**：多页站点一采集就是几十次请求外加限速等待，同步走完会把 HTTP 请求挂住——
界面只能干等，用户也没法中途停下。

**为什么不复用投递台的 ``TaskRunner``**：那是线程模型（驱动浏览器是一串阻塞的 CDP 调用），
而官网采集是 async 的（httpx）。把 async 代码塞进线程要再套一层事件循环，代价大于收益；
两边真正共用的只有"登记、停止、收尾"这三件事，各自几十行，重复的代价小于硬凑一个抽象。

停止信号是**协作式**的：置一个标记，采集器在下一个检查点自己停下来。没有强杀——强杀会让
已暂存的岗位处于半提交状态，而协作式停下来时账目是完整的、能正常落库并给出对账结论。
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from .collector import CollectCancelled

logger = logging.getLogger(__name__)

# 关闭时给运行中的任务多久自行收尾（它们会在下一个检查点看到停止信号）。
# 超时后取消——应用退出不该被一次采集无限拖住。
SHUTDOWN_GRACE_SECONDS = 5.0


class OfficialRunner:
    """进程内的采集任务登记表。"""

    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._stop_requests: set[int] = set()

    def is_running(self, run_id: int) -> bool:
        task = self._tasks.get(run_id)
        return task is not None and not task.done()

    def running_run_ids(self) -> list[int]:
        return [run_id for run_id in self._tasks if self.is_running(run_id)]

    def start(self, run_id: int, coro: Coroutine[Any, Any, None]) -> None:
        """登记并启动。同一个 ``run_id`` 重复启动由调用方负责避免。"""
        # **先清掉上一轮可能残留的停止标记**：清理走的是 ``add_done_callback``，而那是异步
        # 调度的，赶不上紧接着的这一次启动。不清的话，新任务会在第一个检查点被上一轮的请求
        # 叫停——表现为"刚点开始就显示已停止"。
        self._stop_requests.discard(run_id)
        task = asyncio.create_task(coro, name=f"official-collect-{run_id}")
        self._tasks[run_id] = task
        task.add_done_callback(lambda _task: self._forget(run_id))

    def _forget(self, run_id: int) -> None:
        """任务结束后摘掉登记——**停止标记一并清掉**，否则同一个 run_id 下次会被立刻叫停。"""
        self._tasks.pop(run_id, None)
        self._stop_requests.discard(run_id)

    def request_stop(self, run_id: int) -> bool:
        """请求停止；任务不在跑时返回 ``False``（由调用方决定怎么说明）。"""
        if not self.is_running(run_id):
            return False
        self._stop_requests.add(run_id)
        return True

    def checkpoint_for(self, run_id: int) -> Callable[[], None]:
        """给采集器的检查点：被请求停止时抛出 ``CollectCancelled``。

        采集器会在每个检查点（每次取回之前、每条岗位之间）调用它，因此停止的响应粒度是
        "一条岗位"而不是"整次采集"。

        **判据里带上任务状态，而不是只看标记**：标记是在任务结束时由 ``add_done_callback``
        清掉的，而那个回调是**异步调度**的——任务已经结束、标记还没清掉的那一小段时间里，
        只看标记会对着一个已经跑完（或换了一轮）的采集抛取消。
        """
        stop_requests = self._stop_requests
        tasks = self._tasks

        def check() -> None:
            task = tasks.get(run_id)
            if task is None or task.done():
                return
            if run_id in stop_requests:
                raise CollectCancelled()

        return check

    async def shutdown(self) -> None:
        """应用关闭：先请它们自己收尾，给一点时间，超时就取消。

        取消会让任务在下一个 await 点抛 ``CancelledError``——后台协程捕获它之后会把运行记录
        标成"已停止"再重新抛出，所以运行记录不会停在"采集中"。
        """
        for run_id in list(self._tasks):
            self._stop_requests.add(run_id)

        pending = [task for task in self._tasks.values() if not task.done()]
        if pending:
            await asyncio.wait(pending, timeout=SHUTDOWN_GRACE_SECONDS)
        for task in pending:
            if not task.done():
                logger.info("采集任务未在宽限期内收尾，取消它")
                task.cancel()

        self._tasks.clear()
        self._stop_requests.clear()


_RUNNER: OfficialRunner | None = None


def get_official_runner() -> OfficialRunner:
    """进程内共享的运行器单例。

    **延迟构建**：模块导入期可能还没有事件循环，而 ``asyncio.create_task`` 需要它。
    """
    global _RUNNER
    if _RUNNER is None:
        _RUNNER = OfficialRunner()
    return _RUNNER


def reset_official_runner() -> OfficialRunner:
    """测试用：换一个干净的运行器，避免用例之间共享任务状态。

    返回新建的那个，方便调用方在 ``await`` 环境里直接用它（``shutdown`` 是异步的，
    而这里不能 await）。
    """
    global _RUNNER
    _RUNNER = OfficialRunner()
    return _RUNNER


__all__ = [
    "SHUTDOWN_GRACE_SECONDS",
    "OfficialRunner",
    "get_official_runner",
    "reset_official_runner",
]
