"""对抗性测试：停止语义必须"真的停得下来"。

关键用户承诺（主理人最关心的一条）：用户点「停止」后，工作线程必须在**有限时间内干净退出**，
任务置为「已停止」，且**不留下悬挂线程**。这里不重跑工程师的用例，而是从边界下手：

- 刚启动就停止 / 停止后重复停止 / 停止一个已完成的任务 / 暂停中停止；
- 停止信号在「翻页之间」「岗位投递前后」「CDP 调用前后」是否生效；
- 并发起两个任务是否被拒绝；
- 线程是否残留（按名字扫 ``threading.enumerate()``）。

只在测试目录内操作，不碰用户真实数据库。
"""
from __future__ import annotations

import threading
import time

import pytest

from app.models.apply import ApplyTask, ApplyTaskItem
from app.models.job import Job
from app.models.resume import ResumeRecord
from app.schemas.apply import ApplyConfigIn
from app.services.apply import apply_service
from app.services.apply.task_runner import TaskRunner, TaskRunnerError
from app.services.browser.cdp_client import CdpClient
from app.services.sites.base import (
    ApplyOutcome,
    CollectQuery,
    RiskProfile,
    SearchPage,
    SearchResult,
    SiteAdapter,
)
from app.services.sites.registry import SiteRegistry

THREAD_PREFIX = "rf-task-"


class _FastClock:
    """每次读表都大步前进，让岗位间限速立即结束。"""

    def __init__(self) -> None:
        self._t = 0.0

    def __call__(self) -> float:
        self._t += 100.0
        return self._t


class FakeCdp(CdpClient):
    def __init__(self) -> None:
        self.events: list[tuple] = []
        self.closed = False

    def list_targets(self):
        return []

    def new_tab(self, url: str = "about:blank") -> str:
        self.events.append(("new_tab", url))
        return "target-1"

    def send(self, method, params=None, *, timeout=None):
        self.events.append(("send", method))
        return {}

    def evaluate(self, expression, *, timeout=None):
        self.events.append(("evaluate", expression))
        return None

    def set_file_input(self, selector, files, *, timeout=None):
        self.events.append(("file", selector))

    def navigate(self, url, *, timeout=None):
        self.events.append(("navigate", url))
        return {}

    def close(self):
        self.closed = True


class GatedAdapter(SiteAdapter):
    """在 ``open_apply`` 里阻塞，模拟"正在投递某个岗位"的中途状态。"""

    key = "gated"
    display_name = "示例站点"
    hosts = ("zhipin.com",)

    def __init__(self, gate: threading.Event) -> None:
        self._gate = gate
        self.applied: list[str] = []

    def matches(self, url_or_source: str) -> bool:
        return True

    def risk_profile(self) -> RiskProfile:
        return RiskProfile(key=self.key)

    def collect_search(self, client, query, page) -> SearchPage:  # pragma: no cover
        raise AssertionError("投递不应触发采集")

    def open_apply(self, client, job) -> None:
        client.evaluate("rf:open")
        self._gate.wait(timeout=10)

    def fill_and_submit(self, client, data, greeting) -> ApplyOutcome:
        # 走到下一次 CDP 调用时，StopAwareCdpClient 的守卫应当抛 TaskStopped。
        client.evaluate("rf:submit")
        self.applied.append(getattr(data, "get", lambda *_: "")("job_intent"))
        return ApplyOutcome(success=True, greeting_sent=greeting)


def _registry(adapter: SiteAdapter) -> SiteRegistry:
    registry = SiteRegistry()
    registry.register(adapter)
    return registry


def _runner(adapter: SiteAdapter) -> TaskRunner:
    return TaskRunner(
        registry=_registry(adapter),
        client_factory=lambda _config: FakeCdp(),
        sleeper=lambda _seconds: None,
        clock=_FastClock(),
        poll_interval=0.01,
    )


def _config(**overrides) -> ApplyConfigIn:
    data = {
        "interval_seconds": 1,
        "interval_jitter_seconds": 0,
        "breaker_threshold": 3,
        "daily_limit": 60,
        "per_task_limit": 20,
    }
    data.update(overrides)
    return ApplyConfigIn(**data)


def _setup_task(db_session, count: int = 2, **config_overrides) -> ApplyTask:
    task = ApplyTask(
        kind="apply",
        status="pending",
        total=count,
        config=_config(**config_overrides).model_dump(),
    )
    db_session.add(task)
    db_session.flush()
    for index in range(count):
        job = Job(
            title=f"后端开发{index}",
            company=f"公司{index}",
            source="BOSS直聘",
            source_url=f"https://www.zhipin.com/job/{index}",
        )
        db_session.add(job)
        db_session.flush()
        resume = ResumeRecord(
            title=f"后端版{index}", job_id=job.id, job_title=job.title, content={}
        )
        db_session.add(resume)
        db_session.flush()
        db_session.add(
            ApplyTaskItem(
                task_id=task.id,
                job_id=job.id,
                job_title=job.title,
                company=job.company,
                resume_id=resume.id,
                resume_title=resume.title,
                sort_order=index,
            )
        )
    db_session.commit()
    return task


def _wait_thread_exit(runner: TaskRunner, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while runner.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    return not runner.is_running()


def _leftover_threads() -> list[str]:
    return [t.name for t in threading.enumerate() if t.name.startswith(THREAD_PREFIX)]


def _wait_no_leftover(timeout: float = 3.0) -> bool:
    """线程退出与 ``threading.enumerate()`` 之间有一瞬间的窗口，轮询等它消失。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _leftover_threads():
            return True
        time.sleep(0.01)
    return not _leftover_threads()


# ===== 边界：刚启动就停止 =====


def test_stopping_immediately_after_start_still_leaves_a_stopped_task(db_session):
    gate = threading.Event()
    task = _setup_task(db_session, 3)
    runner = _runner(GatedAdapter(gate))

    runner.start(task.id)
    # 不给工作线程任何喘息机会：立刻停止。停止信号必须在步骤间的检查点被读到。
    runner.stop(task.id)
    gate.set()

    assert _wait_thread_exit(runner), "点停止后工作线程没有在有限时间内退出"
    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    assert stored.status == "stopped"
    assert stored.stop_reason == "user"
    assert _wait_no_leftover(), f"残留线程：{_leftover_threads()}"
    assert runner.current_task_id() is None


def test_stop_before_the_worker_begins_still_records_a_finish_time(db_session):
    """停止早于工作线程开始时应与正常停止**同形**：写 finished_at、剩余条目标为已跳过。

    回归钉死（对应工程师修复 3）：早停路径复用 ``_stop_remaining``，不得再留下"已停止但无结束
    时间、条目仍 pending"的半截记录。本条原为 ``xfail``，修复后转为普通断言。
    """
    gate = threading.Event()
    task = _setup_task(db_session, 3)
    runner = _runner(GatedAdapter(gate))

    runner.start(task.id)
    runner.stop(task.id)
    gate.set()
    assert _wait_thread_exit(runner), "点停止后工作线程没有在有限时间内退出"

    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    items = (
        db_session.query(ApplyTaskItem)
        .filter_by(task_id=task.id)
        .order_by(ApplyTaskItem.sort_order)
        .all()
    )
    assert stored.status == "stopped"
    assert stored.stop_reason == "user"
    assert stored.finished_at is not None, "提前停止也必须写入结束时间"
    assert [item.status for item in items] == ["skipped", "skipped", "skipped"]
    assert all(item.finished_at is not None for item in items)
    assert _wait_no_leftover(), f"残留线程：{_leftover_threads()}"
    assert runner.current_task_id() is None


# ===== 边界：停止后重复停止 =====


def test_second_stop_after_the_thread_exited_is_rejected_not_crashed(db_session):
    gate = threading.Event()
    task = _setup_task(db_session, 1)
    runner = _runner(GatedAdapter(gate))

    runner.start(task.id)
    runner.stop(task.id)
    gate.set()
    assert _wait_thread_exit(runner)

    # 第一次停止已让线程退出；再停一次应当是明确的"未在运行"错误，而不是静默成功或崩溃。
    with pytest.raises(TaskRunnerError):
        runner.stop(task.id)


# ===== 边界：停止一个已完成的任务 =====


def test_stopping_a_completed_task_is_rejected(db_session):
    gate = threading.Event()
    task = _setup_task(db_session, 1)
    runner = _runner(GatedAdapter(gate))

    runner.start(task.id)
    gate.set()
    assert _wait_thread_exit(runner)
    db_session.expire_all()
    assert db_session.get(ApplyTask, task.id).status == "completed"

    with pytest.raises(TaskRunnerError):
        runner.stop(task.id)


# ===== 边界：暂停状态下停止 =====


def test_stop_while_paused_unblocks_and_stops(db_session):
    gate = threading.Event()
    task = _setup_task(db_session, 3)
    runner = _runner(GatedAdapter(gate))

    runner.start(task.id)
    # 让工作线程进入 open_apply（STEP_FILLING 之前的阻塞点）。
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        db_session.expire_all()
        if db_session.get(ApplyTask, task.id).status == "running":
            break
        time.sleep(0.01)

    runner.pause(task.id)
    db_session.expire_all()
    assert db_session.get(ApplyTask, task.id).status == "paused"

    # 暂停中停止：不能卡在 _resume 等待里，必须退出。
    runner.stop(task.id)
    gate.set()
    assert _wait_thread_exit(runner), "暂停中停止后线程卡住了"
    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    assert stored.status == "stopped"
    assert stored.stop_reason == "user"
    assert _wait_no_leftover(), f"残留线程：{_leftover_threads()}"


# ===== 停止信号在 CDP 调用前后生效 =====


def test_stop_midway_through_an_item_skips_it_and_the_rest(db_session):
    gate = threading.Event()
    task = _setup_task(db_session, 3)
    adapter = GatedAdapter(gate)
    runner = _runner(adapter)

    runner.start(task.id)
    # 停在工作线程已经进入 open_apply 但还没提交的时候。
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        db_session.expire_all()
        if db_session.get(ApplyTask, task.id).status == "running":
            break
        time.sleep(0.01)

    runner.stop(task.id)
    gate.set()  # 放行被卡住的 open_apply，之后下一次 CDP 调用应当被守卫拦下
    assert _wait_thread_exit(runner)

    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    items = (
        db_session.query(ApplyTaskItem)
        .filter_by(task_id=task.id)
        .order_by(ApplyTaskItem.sort_order)
        .all()
    )
    assert stored.status == "stopped"
    # 当前岗位被记为跳过（未完成），后续岗位也全部跳过。
    assert [item.status for item in items] == ["skipped", "skipped", "skipped"]
    # 没有任何岗位真的投递成功。
    assert stored.succeeded == 0


# ===== 并发两个任务被拒绝 =====


def test_starting_a_second_task_while_one_runs_is_rejected(db_session, monkeypatch):
    from app.services.apply import task_runner as task_runner_module

    gate = threading.Event()
    task = _setup_task(db_session, 2)
    runner = _runner(GatedAdapter(gate))

    runner.start(task.id)
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and not runner.is_running():
        time.sleep(0.01)

    other = _setup_task(db_session, 1)
    with pytest.raises(TaskRunnerError):
        runner.start(other.id)

    # 业务层同样要在建批次前拒绝（不是等到线程里才炸）：把单例替身设为"忙"。
    class _BusyRunner:
        def is_running(self) -> bool:
            return True

        def start(self, task_id: int) -> None:  # pragma: no cover - 不应被调用
            raise AssertionError("已有任务时不应再启动")

    monkeypatch.setattr(task_runner_module, "get_task_runner", lambda: _BusyRunner())
    other_job = db_session.query(Job).order_by(Job.id.desc()).first()
    with pytest.raises(apply_service.ApplyConflict):
        apply_service.create_apply_task(
            db_session, apply_service.ApplyTaskCreate(job_ids=[other_job.id], use_queue=False)
        )

    runner.stop(task.id)
    gate.set()
    assert _wait_thread_exit(runner)
    assert _wait_no_leftover(), f"残留线程：{_leftover_threads()}"


# ===== 采集：翻页之间停止 =====


class _PagingAdapter(SiteAdapter):
    key = "paging"
    display_name = "示例采集站"
    hosts = ("zhipin.com",)

    def __init__(self, gate: threading.Event) -> None:
        self._gate = gate
        self.pages_requested = 0

    def matches(self, url_or_source: str) -> bool:
        return True

    def risk_profile(self) -> RiskProfile:
        return RiskProfile(key=self.key)

    def collect_search(self, client, query: CollectQuery, page: int) -> SearchPage:
        self.pages_requested += 1
        if page == 1:
            self._gate.wait(timeout=10)  # 第一页抓好后卡住，给"翻页之间停止"留出窗口
        results = [
            SearchResult(
                title=f"岗位{page}-{i}",
                company=f"公司{page}",
                url=f"https://www.zhipin.com/job/{page}/{i}",
                source=self.display_name,
            )
            for i in range(3)
        ]
        return SearchPage(results=results, page=page, has_next=True)

    def open_apply(self, client, job) -> None:  # pragma: no cover
        raise AssertionError("采集不应触发投递")

    def fill_and_submit(self, client, data, greeting):  # pragma: no cover
        raise AssertionError("采集不应触发投递")


def test_collect_stop_between_pages_exits_cleanly(db_session):
    from app.schemas.apply import CollectConfigIn

    gate = threading.Event()
    adapter = _PagingAdapter(gate)
    task = ApplyTask(
        kind="collect",
        status="pending",
        total=20,
        config=CollectConfigIn(keywords=["后端"], per_task_limit=20).model_dump(),
    )
    db_session.add(task)
    db_session.commit()

    runner = TaskRunner(
        registry=_registry(adapter),
        client_factory=lambda _config: FakeCdp(),
        sleeper=lambda _seconds: None,
        clock=_FastClock(),
        poll_interval=0.01,
    )
    runner.start(task.id)
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        db_session.expire_all()
        if db_session.get(ApplyTask, task.id).status == "running":
            break
        time.sleep(0.01)

    runner.stop(task.id)
    gate.set()
    assert _wait_thread_exit(runner), "采集中途停止后线程没有退出"

    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    assert stored.status == "stopped"
    assert stored.stop_reason == "user"
    assert _wait_no_leftover(), f"残留线程：{_leftover_threads()}"


# ===== 采集：无条目批次的提前停止收尾（对应工程师修复 3 的采集路径） =====


def _collect_task(db_session, *, total: int = 20) -> ApplyTask:
    from app.schemas.apply import CollectConfigIn

    task = ApplyTask(
        kind="collect",
        status="pending",
        total=total,
        config=CollectConfigIn(keywords=["后端"], per_task_limit=20).model_dump(),
    )
    db_session.add(task)
    db_session.commit()
    return task


def test_early_stop_on_a_collect_task_records_a_finish_time(db_session):
    """采集批次没有 apply_task_item；刚启动就被停止时也必须正常收尾。

    无论停止信号被早停分支还是中途检查点读到，最终都应落 ``stopped / user`` 且有结束时间。
    """
    gate = threading.Event()
    adapter = _PagingAdapter(gate)
    task = _collect_task(db_session)
    runner = TaskRunner(
        registry=_registry(adapter),
        client_factory=lambda _config: FakeCdp(),
        sleeper=lambda _seconds: None,
        clock=_FastClock(),
        poll_interval=0.01,
    )

    runner.start(task.id)
    runner.stop(task.id)
    gate.set()
    assert _wait_thread_exit(runner), "采集任务点停止后线程没有退出"

    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    assert stored.status == "stopped"
    assert stored.stop_reason == "user"
    assert stored.finished_at is not None, "采集任务提前停止也必须写入结束时间"
    assert _wait_no_leftover(), f"残留线程：{_leftover_threads()}"


def test_finalize_early_stop_handles_a_collect_task_without_items(db_session):
    """直击 ``_finalize_early_stop`` 在采集（无条目）路径：items=[] 只收尾任务、不抛异常。"""
    task = _collect_task(db_session)
    runner = _runner(GatedAdapter(threading.Event()))

    runner._finalize_early_stop(db_session, task)

    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    assert stored.status == "stopped"
    assert stored.stop_reason == "user"
    assert stored.finished_at is not None
    assert db_session.query(ApplyTaskItem).filter_by(task_id=task.id).count() == 0
