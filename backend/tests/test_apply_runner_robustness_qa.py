"""对抗性测试：异常不吞、熔断重置、每日上限口径。

针对工程师自述里最容易"看起来对、其实有洞"的三处：
- 工作线程的异常必须被兜底成"失败 + 可读 message + ``logger.exception`` 留痕 + 线程干净退出"，
  不能静默死掉；
- 熔断的连续失败计数在**成功一次后必须归零**（这是常见 bug，专门钉死）；
- 每日上限**只计成功投递**，失败 / 重试不占额度。
"""
from __future__ import annotations

import logging
import threading
import time

import pytest

from app.models.apply import ApplyTask, ApplyTaskItem
from app.models.job import Job
from app.models.profile import utcnow
from app.models.resume import ResumeRecord
from app.schemas.apply import ApplyConfigIn
from app.services.apply import apply_service
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


class _FastClock:
    def __init__(self) -> None:
        self._t = 0.0

    def __call__(self) -> float:
        self._t += 100.0
        return self._t


class FakeCdp(CdpClient):
    def list_targets(self):
        return []

    def new_tab(self, url: str = "about:blank") -> str:
        return "target-1"

    def send(self, method, params=None, *, timeout=None):
        return {}

    def evaluate(self, expression, *, timeout=None):
        return None

    def set_file_input(self, selector, files, *, timeout=None):
        return None

    def navigate(self, url, *, timeout=None):
        return {}

    def close(self):
        return None


class ScriptedAdapter(SiteAdapter):
    """按脚本返回结果：第 n 次调用取 ``script[n-1]``；``None`` 表示成功。"""

    key = "scripted"
    display_name = "示例站点"
    hosts = ("zhipin.com",)

    def __init__(self, script: list, *, raise_on: int | None = None) -> None:
        self._script = list(script)
        self._raise_on = raise_on
        self.calls = 0

    def matches(self, url_or_source: str) -> bool:
        return True

    def risk_profile(self) -> RiskProfile:
        return RiskProfile(key=self.key)

    def collect_search(self, client, query, page) -> SearchPage:  # pragma: no cover
        raise AssertionError("投递不应触发采集")

    def open_apply(self, client, job) -> None:
        client.evaluate("rf:open")

    def fill_and_submit(self, client, data, greeting) -> ApplyOutcome:
        self.calls += 1
        if self._raise_on is not None and self.calls == self._raise_on:
            raise RuntimeError("模拟单岗位内部异常")
        category = self._script[min(self.calls - 1, len(self._script) - 1)] if self._script else None
        if category:
            raise SiteFailure(category, f"模拟失败：{category}")
        return ApplyOutcome(success=True, greeting_sent=greeting)


class _BrokenRegistry:
    """``all()`` 直接抛异常，用来逼出运行器顶层的兜底分支。"""

    def all(self):  # noqa: D401 - 测试替身
        raise RuntimeError("模拟运行器内部错误")

    def for_job(self, job):  # pragma: no cover
        raise AssertionError("不应走到这里")


def _runner(adapter) -> TaskRunner:
    registry = adapter if isinstance(adapter, _BrokenRegistry) else _registry(adapter)
    return TaskRunner(
        registry=registry,
        client_factory=lambda _config: FakeCdp(),
        sleeper=lambda _seconds: None,
        clock=_FastClock(),
        poll_interval=0.01,
    )


def _registry(adapter: SiteAdapter) -> SiteRegistry:
    registry = SiteRegistry()
    registry.register(adapter)
    return registry


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


def _setup_task(db_session, count: int, **config_overrides) -> ApplyTask:
    return _make_apply_task(db_session, count, _config(**config_overrides))


def _make_apply_task(db_session, count: int, config: ApplyConfigIn) -> ApplyTask:
    task = ApplyTask(
        kind="apply", status="pending", total=count, config=config.model_dump()
    )
    db_session.add(task)
    db_session.flush()
    for index in range(count):
        job = Job(
            title=f"岗位{index}",
            company=f"公司{index}",
            source="BOSS直聘",
            source_url=f"https://www.zhipin.com/job/{index}",
        )
        db_session.add(job)
        db_session.flush()
        resume = ResumeRecord(
            title=f"简历{index}", job_id=job.id, job_title=job.title, content={}
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


def _wait(runner: TaskRunner, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while runner.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)


def _leftover_threads() -> list[str]:
    return [t.name for t in threading.enumerate() if t.name.startswith("rf-task-")]


def _wait_no_leftover(timeout: float = 3.0) -> bool:
    """线程退出与 ``threading.enumerate()`` 之间有一瞬间的窗口，轮询等它消失。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _leftover_threads():
            return True
        time.sleep(0.01)
    return not _leftover_threads()


# ===== 熔断计数在成功一次后必须归零 =====


def test_breaker_counter_resets_after_a_success(db_session):
    """失败 2 次 → 成功 1 次 → 再失败 2 次，阈值 3，绝不该熔断。

    若"成功不重置计数"（常见 bug），第 4 次失败时累计会到 3，就会误熔断。
    """
    script = ["selector_invalid", "selector_invalid", None, "selector_invalid", "selector_invalid"]
    adapter = ScriptedAdapter(script)
    task = _setup_task(db_session, 5, breaker_threshold=3)
    runner = _runner(adapter)

    runner.start(task.id)
    _wait(runner)

    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    items = (
        db_session.query(ApplyTaskItem)
        .filter_by(task_id=task.id)
        .order_by(ApplyTaskItem.sort_order)
        .all()
    )
    assert stored.status == "completed", "成功一次后计数未重置，导致误熔断"
    assert stored.succeeded == 1
    assert stored.failed == 4
    assert stored.stop_reason == "done"
    assert [item.status for item in items] == ["failed", "failed", "success", "failed", "failed"]


def test_breaker_triggers_when_failures_are_truly_consecutive(db_session):
    """反向对照：中间没有成功时，连续 3 次失败必须熔断。"""
    adapter = ScriptedAdapter(["selector_invalid"])  # 每次调用都失败
    task = _setup_task(db_session, 5, breaker_threshold=3)
    runner = _runner(adapter)

    runner.start(task.id)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        db_session.expire_all()
        if db_session.get(ApplyTask, task.id).status == "breaker_paused":
            break
        time.sleep(0.01)

    db_session.expire_all()
    assert db_session.get(ApplyTask, task.id).status == "breaker_paused"
    assert "连续 3 次失败" in db_session.get(ApplyTask, task.id).message

    runner.stop(task.id)
    _wait(runner)
    assert _wait_no_leftover(), f"残留线程：{_leftover_threads()}"


# ===== 每日上限只计成功 =====


def test_daily_success_count_counts_only_successes(db_session):
    base = utcnow()
    job = Job(title="岗位", company="公司", source="BOSS直聘", source_url="u")
    db_session.add(job)
    db_session.flush()
    # 同一批次里挂两条：一条成功、一条失败，都应算"今天"。
    task = ApplyTask(kind="apply", status="completed", total=2, config={})
    db_session.add(task)
    db_session.flush()
    db_session.add(
        ApplyTaskItem(
            task_id=task.id, job_id=job.id, status="success", finished_at=base, created_at=base
        )
    )
    db_session.add(
        ApplyTaskItem(
            task_id=task.id, job_id=job.id, status="failed", finished_at=base, created_at=base
        )
    )
    db_session.commit()

    assert apply_service.daily_success_count(db_session) == 1


def test_failed_items_do_not_consume_the_daily_quota(db_session):
    """daily_limit=1：一个失败 + 两个成功，只允许成功占额度。

    若失败也计数，第一次失败就会把额度用光，第二个岗位会被直接跳过。
    """
    adapter = ScriptedAdapter(["selector_invalid", None, None])
    task = _setup_task(db_session, 3, daily_limit=1, breaker_threshold=5)
    runner = _runner(adapter)

    runner.start(task.id)
    _wait(runner)

    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    items = (
        db_session.query(ApplyTaskItem)
        .filter_by(task_id=task.id)
        .order_by(ApplyTaskItem.sort_order)
        .all()
    )
    # 失败 1 + 成功 1，达到上限后剩下的被跳过；失败没有占用额度。
    assert stored.failed == 1
    assert stored.succeeded == 1
    assert [item.status for item in items][0] == "failed"
    assert items[1].status == "success"
    assert items[2].status == "skipped"
    assert stored.status == "stopped"
    assert "上限" in stored.message


def test_starting_a_task_is_blocked_only_by_successful_deliveries(db_session, monkeypatch):
    """已达每日上限时应拒绝开始；但只有失败记录时不应拒绝。"""
    from app.services.apply import task_runner as task_runner_module

    class _StubRunner:
        """替身：只记录 start，不起真实线程（避免污染测试库与残留线程）。"""

        def __init__(self) -> None:
            self.started: list[int] = []

        def is_running(self) -> bool:
            return False

        def start(self, task_id: int) -> None:
            self.started.append(task_id)

    stub = _StubRunner()
    monkeypatch.setattr(task_runner_module, "get_task_runner", lambda: stub)

    base = utcnow()
    job = Job(title="岗位", company="公司", source="BOSS直聘", source_url="u")
    db_session.add(job)
    db_session.flush()
    old = ApplyTask(kind="apply", status="completed", total=1, config={})
    db_session.add(old)
    db_session.flush()
    db_session.add(
        ApplyTaskItem(
            task_id=old.id, job_id=job.id, status="failed", finished_at=base, created_at=base
        )
    )
    apply_service.save_apply_config(db_session, _config(daily_limit=1))
    db_session.commit()

    # 只有失败记录：额度未用，允许开始。
    task = apply_service.create_apply_task(
        db_session, apply_service.ApplyTaskCreate(job_ids=[job.id], use_queue=False)
    )
    assert task.id is not None
    assert stub.started == [task.id]

    # 补一条今天的成功记录，把额度用满后再建批次 → 拒绝。
    db_session.add(
        ApplyTaskItem(
            task_id=old.id, job_id=job.id, status="success", finished_at=base, created_at=base
        )
    )
    db_session.commit()
    with pytest.raises(apply_service.ApplyConflict):
        apply_service.create_apply_task(
            db_session, apply_service.ApplyTaskCreate(job_ids=[job.id], use_queue=False)
        )


# ===== 异常不吞 =====


def test_single_item_error_is_logged_and_next_item_continues(db_session, caplog):
    adapter = ScriptedAdapter([None, None], raise_on=1)
    task = _setup_task(db_session, 2)
    runner = _runner(adapter)

    with caplog.at_level(logging.ERROR, logger="app.services.apply.task_runner"):
        runner.start(task.id)
        _wait(runner)

    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    items = (
        db_session.query(ApplyTaskItem)
        .filter_by(task_id=task.id)
        .order_by(ApplyTaskItem.sort_order)
        .all()
    )
    assert stored.status == "completed"
    assert items[0].status == "failed"
    assert items[0].failure_category == "unknown"
    assert items[1].status == "success"
    # 留痕：必须带堆栈，而不是只记一句 message。
    assert any(record.exc_info for record in caplog.records)
    assert "投递单个岗位失败" in caplog.text
    assert _wait_no_leftover(), f"残留线程：{_leftover_threads()}"


def test_top_level_worker_error_marks_task_failed_with_readable_message(db_session, caplog):
    """工作线程顶层异常必须兜底：任务置失败、message 可读、logger.exception 留痕、线程干净退出。"""
    task = ApplyTask(
        kind="collect",
        status="pending",
        total=5,
        config={"keywords": ["后端"], "per_task_limit": 5},
    )
    db_session.add(task)
    db_session.commit()

    runner = TaskRunner(
        registry=_BrokenRegistry(),
        client_factory=lambda _config: FakeCdp(),
        sleeper=lambda _seconds: None,
        clock=_FastClock(),
        poll_interval=0.01,
    )
    with caplog.at_level(logging.ERROR, logger="app.services.apply.task_runner"):
        runner.start(task.id)
        _wait(runner)

    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    assert stored.status == "failed"
    assert stored.stop_reason == "error"
    assert stored.finished_at is not None
    assert stored.message  # 可读的中文提示，不是空串
    assert any(record.exc_info for record in caplog.records)
    assert "任务执行发生内部错误" in caplog.text
    # 线程必须干净收尾，且运行器已释放。
    assert runner.is_running() is False
    assert runner.current_task_id() is None
    assert _wait_no_leftover(), f"残留线程：{_leftover_threads()}"
