"""任务运行器离线测试：完成 / 暂停恢复 / 停止 / 熔断 / 异常隔离 / 跨线程会话。"""
import threading
import time

import pytest

from app.models.apply import STEP_FILLING, ApplyTask, ApplyTaskItem
from app.models.job import JOB_STATUS_APPLIED, Job
from app.models.resume import ResumeRecord
from app.models.tracker import SOURCE_APPLY, STATUS_APPLIED, ApplicationTrack
from app.schemas.apply import ApplyConfigIn
from app.services.apply.task_runner import TaskRunner
from app.services.browser.cdp_client import CdpClient
from app.services.sites.base import (
    ApplyOutcome,
    RiskProfile,
    SearchPage,
    SiteAdapter,
    SiteFailure,
)
from app.services.sites.registry import SiteRegistry


class _FakeClock:
    """每次读表都大步前进，让岗位间限速立即结束（离线测试不真等）。"""

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


class FakeAdapter(SiteAdapter):
    key = "fake"
    display_name = "示例站点"
    hosts = ("zhipin.com",)

    def __init__(
        self,
        *,
        fail_categories: list[str | None] | None = None,
        gate: threading.Event | None = None,
        raise_first_error: bool = False,
    ) -> None:
        self._fail_categories = list(fail_categories or [])
        self._gate = gate
        self._raise_first_error = raise_first_error
        self.calls = 0

    def matches(self, url_or_source: str) -> bool:
        return True

    def risk_profile(self) -> RiskProfile:
        return RiskProfile(key=self.key)

    def collect_search(self, client, query, page) -> SearchPage:  # pragma: no cover
        raise AssertionError("投递不应触发采集")

    def open_apply(self, client, job) -> None:
        client.evaluate("rf:open")
        if self._gate is not None:
            self._gate.wait(timeout=5)

    def fill_and_submit(self, client, data, greeting) -> ApplyOutcome:
        self.calls += 1
        client.evaluate("rf:submit")
        if self._raise_first_error and self.calls == 1:
            raise RuntimeError("模拟内部异常")
        if self._fail_categories:
            category = self._fail_categories[min(self.calls - 1, len(self._fail_categories) - 1)]
            if category:
                raise SiteFailure(category, f"模拟失败：{category}")
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
        clock=_FakeClock(),
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


def _setup_task(
    db_session, count: int = 1, *, with_resume: bool = True, **config_overrides
) -> ApplyTask:
    task = ApplyTask(kind="apply", status="pending", total=count, config=_config(**config_overrides).model_dump())
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
        resume = None
        if with_resume:
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
                resume_id=resume.id if resume is not None else None,
                resume_title=resume.title if resume is not None else "",
                sort_order=index,
            )
        )
    db_session.commit()
    return task


def _wait(runner: TaskRunner, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while runner.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)


def _wait_db(db_session, read, expected, describe: str, timeout: float = 10.0):
    """轮询等待数据库里的观测值到达 ``expected``；超时给出带实测值的可读失败。

    为什么需要它：``_wait()`` 只保证工作线程退出，之后**一次性读库断言**会把"读到还没落库
    的旧状态"当成失败——整机满载时线程调度抖动即触发（典型 flaky：隔离跑常过、满载偶发红）。
    改为对数据库状态做容错轮询，就不再对"提交可见时刻"做任何假设。

    ``read`` 返回当前观测值，``expected`` 是期望值；相等即通过。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        db_session.expire_all()
        observed = read()
        if observed == expected:
            return observed
        time.sleep(0.01)
    db_session.expire_all()
    observed = read()
    raise AssertionError(
        f"{describe}：{timeout}s 内未到达期望值 {expected!r}，实际观测为 {observed!r}"
    )


def _task_status(db_session, task_id: int) -> str:
    task = db_session.get(ApplyTask, task_id)
    return task.status if task is not None else "<missing>"


def _item_statuses(db_session, task_id: int) -> list[str]:
    return [
        item.status
        for item in db_session.query(ApplyTaskItem)
        .filter_by(task_id=task_id)
        .order_by(ApplyTaskItem.sort_order)
        .all()
    ]


def _poll(db_session, predicate, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        db_session.expire_all()
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    db_session.expire_all()
    return predicate()


def test_runner_completes_and_writes_back_job_status(db_session):
    task = _setup_task(db_session, 1)
    runner = _runner(FakeAdapter())

    runner.start(task.id)
    _wait(runner)
    _wait_db(db_session, lambda: _task_status(db_session, task.id), "completed", "任务状态")

    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    item = db_session.query(ApplyTaskItem).filter_by(task_id=task.id).one()
    job = db_session.get(Job, item.job_id)
    assert stored.status == "completed"
    assert stored.succeeded == 1
    assert item.status == "success"
    assert item.greeting  # 默认招呼语已写入记录
    assert job.status == JOB_STATUS_APPLIED


def test_a_custom_greeting_wins_over_the_default_one(db_session):
    """**用户为这个岗位自己写的招呼语，必须真的被发出去**（而不是被默认招呼语顶掉）。

    这条是"用户自定义必须真实生效"里最容易出问题的一类：界面里能逐条编辑招呼语，用户改完
    看到的是"已保存"，但发出去的到底是哪一条，只有断言到**适配器收到什么**才知道。

    验证方式：把招呼语设成一个哨兵串，跑完一轮后看写回记录里的招呼语是不是它——
    运行器会把适配器**实际发出去**的那条写回 `item.greeting`（见 ``task_runner`` 里的
    ``item.greeting = outcome.greeting_sent``），所以记录里是哨兵串就说明自定义那条赢了。
    """
    task = _setup_task(db_session, 1)
    item = db_session.query(ApplyTaskItem).filter_by(task_id=task.id).one()
    item.greeting = "您好，我是自己写的那一条 SENTINEL_GREETING"
    db_session.commit()

    runner = _runner(FakeAdapter())
    runner.start(task.id)
    _wait(runner)
    _wait_db(db_session, lambda: _task_status(db_session, task.id), "completed", "任务状态")

    db_session.expire_all()
    sent = db_session.query(ApplyTaskItem).filter_by(task_id=task.id).one()
    assert sent.greeting == "您好，我是自己写的那一条 SENTINEL_GREETING"


def test_runner_records_a_tracker_row_for_each_successful_apply(db_session):
    """投出去的岗位要自动出现在「求职进度」里，否则用户还得手工再录一遍。"""
    task = _setup_task(db_session, 1)
    runner = _runner(FakeAdapter())

    runner.start(task.id)
    _wait(runner)
    _wait_db(db_session, lambda: _task_status(db_session, task.id), "completed", "任务状态")

    db_session.expire_all()
    item = db_session.query(ApplyTaskItem).filter_by(task_id=task.id).one()
    tracks = db_session.query(ApplicationTrack).all()
    assert len(tracks) == 1
    assert tracks[0].company == item.company
    assert tracks[0].title == item.job_title
    assert tracks[0].status == STATUS_APPLIED
    assert tracks[0].source == SOURCE_APPLY
    assert tracks[0].job_id == item.job_id


def test_runner_allows_an_adapter_that_does_not_require_a_generated_resume(db_session):
    """BOSS 的立即沟通不依赖本地岗位版简历，缺简历时仍应进入站点投递流程。"""

    class _NoResumeAdapter(FakeAdapter):
        requires_resume = False

    task = _setup_task(db_session, 1, with_resume=False)
    adapter = _NoResumeAdapter()
    runner = _runner(adapter)

    runner.start(task.id)
    _wait(runner)
    _wait_db(db_session, lambda: _task_status(db_session, task.id), "completed", "任务状态")

    db_session.expire_all()
    item = db_session.query(ApplyTaskItem).filter_by(task_id=task.id).one()
    assert item.status == "success"
    assert adapter.calls == 1


def test_runner_still_skips_missing_resume_when_the_adapter_requires_it(db_session):
    task = _setup_task(db_session, 1, with_resume=False)
    adapter = FakeAdapter()
    runner = _runner(adapter)

    runner.start(task.id)
    _wait(runner)
    _wait_db(db_session, lambda: _task_status(db_session, task.id), "completed", "任务状态")

    db_session.expire_all()
    item = db_session.query(ApplyTaskItem).filter_by(task_id=task.id).one()
    assert item.status == "skipped"
    assert "未找到可用简历" in item.failure_detail
    assert adapter.calls == 0


def test_runner_pause_and_resume(db_session):
    gate = threading.Event()
    task = _setup_task(db_session, 1)
    runner = _runner(FakeAdapter(gate=gate))

    runner.start(task.id)
    _poll(db_session, lambda: db_session.get(ApplyTask, task.id).current_step == STEP_FILLING)
    runner.pause(task.id)
    db_session.expire_all()
    assert db_session.get(ApplyTask, task.id).status == "paused"

    gate.set()
    time.sleep(0.05)
    db_session.expire_all()
    assert db_session.get(ApplyTask, task.id).status == "paused"  # 暂停确实卡住了

    runner.resume(task.id)
    _wait(runner)
    _wait_db(db_session, lambda: _task_status(db_session, task.id), "completed", "恢复后任务状态")
    db_session.expire_all()
    assert db_session.get(ApplyTask, task.id).status == "completed"
    assert db_session.query(ApplyTaskItem).filter_by(task_id=task.id).one().status == "success"


def test_runner_stop_marks_remaining_items_skipped(db_session):
    gate = threading.Event()
    task = _setup_task(db_session, 2)
    runner = _runner(FakeAdapter(gate=gate))

    runner.start(task.id)
    _poll(db_session, lambda: db_session.get(ApplyTask, task.id).current_step == STEP_FILLING)
    runner.stop(task.id)
    gate.set()
    _wait(runner)
    _wait_db(
        db_session,
        lambda: (_task_status(db_session, task.id), _item_statuses(db_session, task.id)),
        ("stopped", ["skipped", "skipped"]),
        "停止后任务与剩余条目状态",
    )

    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    items = db_session.query(ApplyTaskItem).filter_by(task_id=task.id).order_by(ApplyTaskItem.sort_order).all()
    assert stored.status == "stopped"
    assert stored.stop_reason == "user"
    assert items[0].status == "skipped"
    assert items[1].status == "skipped"


def test_runner_breaker_pauses_after_consecutive_failures(db_session):
    task = _setup_task(db_session, 2, breaker_threshold=1)
    runner = _runner(FakeAdapter(fail_categories=["selector_invalid"]))

    runner.start(task.id)
    _poll(db_session, lambda: db_session.get(ApplyTask, task.id).status == "breaker_paused")
    runner.stop(task.id)
    _wait(runner)
    _wait_db(
        db_session,
        lambda: (_task_status(db_session, task.id), _item_statuses(db_session, task.id)),
        ("stopped", ["failed", "skipped"]),
        "熔断后停止的任务与条目状态",
    )

    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    first = (
        db_session.query(ApplyTaskItem)
        .filter_by(task_id=task.id)
        .order_by(ApplyTaskItem.sort_order)
        .first()
    )
    assert stored.status == "stopped"
    assert first.status == "failed"
    assert first.failure_category == "selector_invalid"
    assert "自动暂停" in stored.message or stored.stop_reason == "user"


def test_runner_isolates_single_item_exception(db_session):
    task = _setup_task(db_session, 2, breaker_threshold=3)
    runner = _runner(FakeAdapter(raise_first_error=True))

    runner.start(task.id)
    _wait(runner)
    _wait_db(
        db_session,
        lambda: (_task_status(db_session, task.id), _item_statuses(db_session, task.id)),
        ("completed", ["failed", "success"]),
        "单岗位异常被隔离后的任务与条目状态",
    )

    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    items = (
        db_session.query(ApplyTaskItem)
        .filter_by(task_id=task.id)
        .order_by(ApplyTaskItem.sort_order)
        .all()
    )
    # 单岗位内部异常不打死线程，后续岗位继续；整体仍跑完。
    assert stored.status == "completed"
    assert items[0].status == "failed"
    assert items[1].status == "success"


# ===== 修复 A：控制接口回写不得覆盖工作线程提交的终态（pause/resume 竞态根因）=====


def _bare_task(db_session, status: str = "running") -> ApplyTask:
    """直接造一条指定状态的任务行，用于白盒直测 ``_set_status`` 的终态守卫。"""
    task = ApplyTask(kind="apply", status=status, total=0, config=_config().model_dump())
    db_session.add(task)
    db_session.commit()
    return task


@pytest.mark.parametrize("terminal", ["completed", "stopped", "failed"])
def test_set_status_refuses_to_overwrite_a_terminal_status(db_session, terminal):
    """白盒直击 ``_set_status``：任务已落终态后，任何活动态回写都必须被拒绝。

    竞态链路——工作线程抢先提交 ``completed`` 后，``resume()`` 会调到
    ``_set_status(RUNNING)``；若此处无条件回写，终态就会被盖成 ``running`` 且再无人修正，
    任务永久卡住。三种终态逐一验证：running / paused / stopped 都无法覆盖。
    """
    runner = _runner(FakeAdapter())
    task = _bare_task(db_session, status=terminal)

    for target in ("running", "paused", "stopped"):
        runner._set_status(task.id, target)

    db_session.expire_all()
    assert _task_status(db_session, task.id) == terminal


def test_set_status_still_applies_active_transitions(db_session):
    """终态守卫只拦"终态→活动态"，不能误伤运行中的暂停 / 恢复 / 停止。"""
    runner = _runner(FakeAdapter())
    task = _bare_task(db_session, status="running")

    runner._set_status(task.id, "paused")
    db_session.expire_all()
    assert _task_status(db_session, task.id) == "paused"

    runner._set_status(task.id, "running")
    db_session.expire_all()
    assert _task_status(db_session, task.id) == "running"

    # 运行中停止仍应生效（当前是活动态，允许写入 stopped 与原因）。
    runner._set_status(task.id, "stopped", "user")
    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    assert stored.status == "stopped"
    assert stored.stop_reason == "user"


def test_resume_after_worker_completed_keeps_the_terminal_status(db_session):
    """端到端复现：任务已 completed，控制线程再补一次 running 回写必须被拒绝。"""
    runner = _runner(FakeAdapter())
    task = _bare_task(db_session, status="completed")

    # 模拟 resume() 在 worker 抢先提交 completed 之后才执行的那一次回写。
    runner._set_status(task.id, "running")

    db_session.expire_all()
    assert _task_status(db_session, task.id) == "completed"


def test_pause_resume_cycle_never_strands_a_task_in_running(db_session):
    """真实 worker + 控制接口并发：pause→resume 收尾后必须停在终态，绝不残留 running。

    这是竞态的最强回归：``resume()`` 的 ``_set_status(RUNNING)`` 必须在**数据库层**原子地
    让位于工作线程已提交的终态。只要回写是"先读后盲写"，工作线程的 completed 就有机会落在
    读与写之间被盖掉，任务永久卡在 running——本用例对该时序做端到端把关。
    """
    gate = threading.Event()
    task = _setup_task(db_session, 1)
    runner = _runner(FakeAdapter(gate=gate))

    runner.start(task.id)
    _poll(db_session, lambda: db_session.get(ApplyTask, task.id).current_step == STEP_FILLING)
    runner.pause(task.id)
    gate.set()
    time.sleep(0.05)
    runner.resume(task.id)

    _wait(runner)
    _wait_db(db_session, lambda: _task_status(db_session, task.id), "completed", "恢复后任务状态")
    # pause/resume 的控制回写不得把 worker 已提交的终态改回 running。
    assert _task_status(db_session, task.id) == "completed"
    assert db_session.query(ApplyTaskItem).filter_by(task_id=task.id).one().status == "success"
