"""QA 独立对抗测试（第 3 节）：证明"等待真的能被停止/暂停打断"。

用**真实的** ``BossAdapter`` + **真实的** ``TaskRunner`` + 一个"探针永远不就绪"的假 CDP
客户端，制造"页面永远加载不出内容、采集一直卡在等待里"的最坏情形，然后：

- 点停止 → 必须在**远小于等待超时**的时间内干净退出，任务置「已停止」，无悬挂线程；
- 点暂停 → 探针调用立刻冻结（等待停在等待中），继续后能接着跑。

若只能等满超时才停，就是重要级问题。这里把超时设成 30 秒，用真实时钟断言实际退出耗时。
"""
from __future__ import annotations

import threading
import time

from app.models.apply import ApplyTask
from app.schemas.apply import CollectConfigIn
from app.services.apply.task_runner import TaskRunner
from app.services.browser.cdp_client import CdpClient
from app.services.browser.page_ready import ReadyWait
from app.services.sites.boss import BossAdapter
from app.services.sites.registry import SiteRegistry

THREAD_PREFIX = "rf-task-"
# 等待超时故意给到 30 秒；能证明"快速打断"的前提是它没等满。
WAIT_TIMEOUT = 30.0
# 停止动作被观察到的耗时上限（远小于 30 秒）。
FAST_STOP_BOUND = 3.0


class _FastClock:
    """每次读表都大步前进，让岗位间限速/间隔立即结束（不影响等待原语的真实时钟）。"""

    def __init__(self) -> None:
        self._t = 0.0

    def __call__(self) -> float:
        self._t += 100.0
        return self._t


class NeverReadyClient(CdpClient):
    """探针永远返回"未就绪"：页面一直处于加载中，matched=0 且无"无结果"标志。"""

    def __init__(self) -> None:
        self.readiness_probes = 0
        self.navigations: list[str] = []
        self.closed = False

    def list_targets(self):
        return []

    def new_tab(self, url: str = "about:blank") -> str:
        return "tab"

    def navigate(self, url: str, *, timeout=None):
        self.navigations.append(url)
        return {}

    def send(self, method, params=None, *, timeout=None):
        return {}

    def set_file_input(self, selector, files, *, timeout=None):
        return None

    def evaluate(self, expression, *, timeout=None):
        if "rf:url" in expression:
            return {"url": "about:blank"}
        if "rf:readiness" in expression:
            self.readiness_probes += 1
            return {
                "url": "https://www.zhipin.com/web/geek/job?query=x&city=&page=1",
                "title": "加载中",
                "ready_state": "loading",
                "matched": 0,
                "explicitly_empty": False,
            }
        return None

    def close(self):
        self.closed = True


def _registry() -> SiteRegistry:
    registry = SiteRegistry()
    # 生产默认参数之外，仅把"等待超时/间隔"调成便于观察的值；其余行为与生产一致。
    registry.register(BossAdapter(ready_wait=ReadyWait(timeout=WAIT_TIMEOUT, poll_interval=0.05)))
    return registry


def _collect_task(db_session) -> ApplyTask:
    task = ApplyTask(
        kind="collect",
        status="pending",
        total=20,
        config=CollectConfigIn(keywords=["后端"], city="北京", per_task_limit=20).model_dump(),
    )
    db_session.add(task)
    db_session.commit()
    return task


def _runner_with_capture(captured: list[NeverReadyClient]) -> TaskRunner:
    def factory(_config):
        client = NeverReadyClient()
        captured.append(client)
        return client

    return TaskRunner(
        registry=_registry(),
        client_factory=factory,
        sleeper=lambda _seconds: None,  # 岗位间限速不真等
        clock=_FastClock(),
        poll_interval=0.01,
    )


def _wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _wait_thread_exit(runner: TaskRunner, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while runner.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    return not runner.is_running()


def _leftover_threads() -> list[str]:
    return [t.name for t in threading.enumerate() if t.name.startswith(THREAD_PREFIX)]


def _wait_no_leftover(timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _leftover_threads():
            return True
        time.sleep(0.01)
    return not _leftover_threads()


def test_stop_interrupts_a_never_ready_wait_quickly(db_session):
    """探针永远不就绪时点停止：必须在远小于超时的时间内结束，任务置已停止，无悬挂线程。"""
    captured: list[NeverReadyClient] = []
    task = _collect_task(db_session)
    runner = _runner_with_capture(captured)

    runner.start(task.id)
    # 等工作线程真正进入等待循环（已多次探针、且仍在跑）。
    assert _wait_until(lambda: bool(captured) and captured[0].readiness_probes >= 3), (
        "工作线程没有进入采集等待循环"
    )
    assert runner.is_running()

    started = time.monotonic()
    runner.stop(task.id)
    assert _wait_thread_exit(runner), "点停止后工作线程没有在有限时间内退出"
    elapsed = time.monotonic() - started

    assert elapsed < FAST_STOP_BOUND, f"停止耗时 {elapsed:.2f}s，接近/超过等待超时，说明没被及时打断"

    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    assert stored.status == "stopped"
    assert stored.stop_reason == "user"
    assert stored.finished_at is not None
    assert runner.current_task_id() is None
    assert _wait_no_leftover(), f"残留线程：{_leftover_threads()}"
    # 客户端被正确关闭（finally 里的 client.close()）。
    assert captured[0].closed is True


def test_pause_freezes_the_wait_then_resume_continues(db_session):
    """暂停应停在等待中（探针冻结），继续后能接着跑。"""
    captured: list[NeverReadyClient] = []
    task = _collect_task(db_session)
    runner = _runner_with_capture(captured)

    runner.start(task.id)
    assert _wait_until(lambda: bool(captured) and captured[0].readiness_probes >= 3)

    runner.pause(task.id)
    db_session.expire_all()
    assert db_session.get(ApplyTask, task.id).status == "paused"

    # 让任何"已在途"的一次探针跑完，再取基线。
    time.sleep(0.2)
    frozen_at = captured[0].readiness_probes
    time.sleep(0.5)
    # 暂停期间不得再有新的探针调用（等待停在等待中）。
    assert captured[0].readiness_probes == frozen_at, "暂停后探针仍在继续，说明没停住"
    # 暂停时任务不得被意外推进到终态。
    db_session.expire_all()
    assert db_session.get(ApplyTask, task.id).status == "paused"
    assert runner.is_running()

    # 继续：探针重新开始增长。
    runner.resume(task.id)
    assert _wait_until(lambda: captured[0].readiness_probes > frozen_at, timeout=3.0), (
        "继续后等待没有接着跑"
    )

    # 收尾：停止，确保干净退出。
    runner.stop(task.id)
    assert _wait_thread_exit(runner)
    db_session.expire_all()
    assert db_session.get(ApplyTask, task.id).status == "stopped"
    assert _wait_no_leftover(), f"残留线程：{_leftover_threads()}"
