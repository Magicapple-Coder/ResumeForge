"""后台采集的运行器：登记、停止信号、关闭收尾。

停止是**协作式**的：置一个标记，采集器在下一个检查点自己停下来。这里守的就是那条链路——
标记置了要能被检查点看到、检查点抛出的取消要能被采集器认成"已停止"而不是"失败"，
以及**任务结束后标记必须清掉**（不清的话同一个 run_id 下次会被立刻叫停）。
"""
from __future__ import annotations

import asyncio

import pytest

from app.services.sites.official.collector import CollectCancelled
from app.services.sites.official.runner import OfficialRunner


async def _wait_until(predicate, *, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("条件没有在超时前成立")


class _Hold:
    """一个可以被外部放行的任务体，模拟"还在跑"的采集。"""

    def __init__(self, runner: OfficialRunner, run_id: int) -> None:
        self.release = asyncio.Event()
        runner.start(run_id, self._work())

    async def _work(self) -> None:
        await self.release.wait()

    async def finish(self) -> None:
        self.release.set()
        await asyncio.sleep(0)


async def test_started_task_is_tracked_and_forgotten():
    runner = OfficialRunner()
    hold = _Hold(runner, 1)

    assert runner.is_running(1) is True
    assert runner.running_run_ids() == [1]

    await hold.finish()
    await _wait_until(lambda: not runner.is_running(1))
    assert runner.running_run_ids() == []


async def test_stopping_an_unknown_run_reports_failure():
    """任务不在跑时返回 ``False``，由调用方决定怎么说明——而不是悄悄成功。"""
    assert OfficialRunner().request_stop(404) is False


async def test_checkpoint_is_silent_until_a_stop_is_requested():
    runner = OfficialRunner()
    check = runner.checkpoint_for(1)

    check()  # 没请求停止时不该抛
    assert runner.request_stop(1) is False, "任务没在跑，叫停不成立"
    check()  # 标记没置上，仍然不该抛


async def test_checkpoint_raises_after_a_stop_request():
    runner = OfficialRunner()
    hold = _Hold(runner, 1)
    check = runner.checkpoint_for(1)

    assert runner.request_stop(1) is True
    with pytest.raises(CollectCancelled):
        check()

    await hold.finish()
    await _wait_until(lambda: not runner.is_running(1))


async def test_stop_flag_is_cleared_when_the_task_ends():
    """**标记必须随任务一起清掉**：不清的话同一个 run_id 下一轮会被立刻叫停。"""
    runner = OfficialRunner()
    first = _Hold(runner, 1)
    runner.request_stop(1)
    await first.finish()
    await _wait_until(lambda: not runner.is_running(1))

    second = _Hold(runner, 1)
    runner.checkpoint_for(1)()  # 不抛，说明上一轮的标记已经随任务清掉了
    await second.finish()


async def test_shutdown_lets_running_tasks_finish_gracefully():
    """关闭时先请它们自己收尾：协作式停下比强杀多保住一份完整的账目。"""
    runner = OfficialRunner()
    stopped: list[str] = []

    async def collect() -> None:
        # 模拟采集器：反复在检查点上看有没有人叫停。
        try:
            while True:
                runner.checkpoint_for(1)()
                await asyncio.sleep(0.005)
        except CollectCancelled:
            stopped.append("cancelled")

    runner.start(1, collect())
    await asyncio.sleep(0.02)

    await runner.shutdown()

    assert stopped == ["cancelled"], "任务应当是被检查点叫停的，而不是被强杀"
    assert runner.running_run_ids() == []


async def test_shutdown_cancels_a_task_that_ignores_the_signal():
    """完全不看检查点的任务会被取消——应用退出不该被一次采集无限拖住。

    取消不是常规路径（采集器每个检查点都会看标记），但**必须有**：否则一个卡住的请求
    会让进程永远退不掉。
    """
    runner = OfficialRunner()
    cancelled: list[str] = []

    async def stubborn() -> None:
        try:
            while True:
                await asyncio.sleep(0.005)
        except asyncio.CancelledError:
            cancelled.append("cancelled")
            raise

    runner.start(1, stubborn())
    await asyncio.sleep(0.02)

    # 把宽限期压到几乎为零，免得用例真的等 5 秒。
    import app.services.sites.official.runner as module

    original = module.SHUTDOWN_GRACE_SECONDS
    module.SHUTDOWN_GRACE_SECONDS = 0.01
    try:
        await runner.shutdown()
    finally:
        module.SHUTDOWN_GRACE_SECONDS = original

    # 取消是**调度**出去的，要让出一轮事件循环才看得到它的效果。
    await asyncio.sleep(0.02)

    assert cancelled == ["cancelled"]
    assert runner.running_run_ids() == []


async def test_shutdown_is_safe_with_nothing_running():
    await OfficialRunner().shutdown()
