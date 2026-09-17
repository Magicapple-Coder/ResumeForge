"""第二轮对抗：定位 pause/resume 在满载下"恢复后卡在 running"的根因。

背景：工程师修复 1 把"一次性读库断言"改成 DB 状态轮询（10s），但**全量满载复跑仍复现**
同一用例 `test_runner_pause_and_resume` 失败——且失败信息变成"10s 内未到达 completed，实际
观测为 running"。这说明不是"读得太早"，而是**恢复后任务真的没走到 completed**。

本文件用同样时序复现该场景，并在超时时：
- 检查工作线程是否还活着（``runner.is_running()``）；
- 若线程已退出但状态仍是 running，则证明是控制线程把终态**回写覆盖**成了 running；
- 同时 dump 所有线程栈，便于进一步定位。
"""
from __future__ import annotations

import sys
import threading
import time
import traceback

import pytest

from app.models.apply import STEP_FILLING, ApplyTask, ApplyTaskItem
from app.models.job import Job
from app.models.resume import ResumeRecord
from app.schemas.apply import ApplyConfigIn
from app.services.apply.task_runner import TaskRunner
from app.services.browser.cdp_client import CdpClient
from app.services.sites.base import ApplyOutcome, RiskProfile, SiteAdapter
from app.services.sites.registry import SiteRegistry

THREAD_PREFIX = "rf-task-"


class _FastClock:
    def __init__(self) -> None:
        self._t = 0.0

    def __call__(self) -> float:
        self._t += 100.0
        return self._t


class FakeCdp(CdpClient):
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def list_targets(self):
        return []

    def new_tab(self, url: str = "about:blank") -> str:
        return "target-1"

    def send(self, method, params=None, *, timeout=None):
        return {}

    def evaluate(self, expression, *, timeout=None):
        self.events.append(("evaluate", expression))
        return None

    def set_file_input(self, selector, files, *, timeout=None):
        return None

    def navigate(self, url, *, timeout=None):
        return {}

    def close(self):
        return None


class GatedAdapter(SiteAdapter):
    key = "gated"
    display_name = "示例站点"
    hosts = ("zhipin.com",)

    def __init__(self, gate: threading.Event) -> None:
        self._gate = gate

    def matches(self, url_or_source: str) -> bool:
        return True

    def risk_profile(self) -> RiskProfile:
        return RiskProfile(key=self.key)

    def collect_search(self, client, query, page):  # pragma: no cover
        raise AssertionError("投递不应触发采集")

    def open_apply(self, client, job) -> None:
        client.evaluate("rf:open")
        self._gate.wait(timeout=5)

    def fill_and_submit(self, client, data, greeting) -> ApplyOutcome:
        client.evaluate("rf:submit")
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


def _config() -> ApplyConfigIn:
    return ApplyConfigIn(
        interval_seconds=1,
        interval_jitter_seconds=0,
        breaker_threshold=3,
        daily_limit=60,
        per_task_limit=20,
    )


def _setup_task(db_session, count: int = 1) -> ApplyTask:
    task = ApplyTask(kind="apply", status="pending", total=count, config=_config().model_dump())
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


def _status(db_session, task_id: int) -> str:
    db_session.expire_all()
    task = db_session.get(ApplyTask, task_id)
    return task.status if task is not None else "<missing>"


def _task_threads() -> list[str]:
    return [t.name for t in threading.enumerate() if t.name.startswith(THREAD_PREFIX)]


def _dump_stacks() -> str:
    frames = sys._current_frames()
    chunks: list[str] = []
    for thread in threading.enumerate():
        frame = frames.get(thread.ident) if thread.ident is not None else None
        chunks.append(f"--- thread {thread.name} alive={thread.is_alive()} ---")
        if frame is not None:
            chunks.append("".join(traceback.format_stack(frame)))
    return "\n".join(chunks)


def test_pause_resume_completes_without_clobbering_final_status(db_session):
    """复现 pause→resume 时序；若卡在 running，给出线程级诊断。"""
    gate = threading.Event()
    task = _setup_task(db_session, 1)
    runner = _runner(GatedAdapter(gate))

    runner.start(task.id)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if (
            db_session.get(ApplyTask, task.id).current_step == STEP_FILLING
            or _status(db_session, task.id) == "running"
        ):
            break
        time.sleep(0.01)

    runner.pause(task.id)
    gate.set()
    time.sleep(0.05)
    runner.resume(task.id)

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if _status(db_session, task.id) == "completed":
            break
        time.sleep(0.01)

    status = _status(db_session, task.id)
    thread_alive = runner.is_running()
    leftover = _task_threads()

    # 无论成败都收尾，避免残留线程影响其它用例。
    if thread_alive:
        runner.shutdown()

    if status != "completed":
        detail = [
            f"恢复后任务未在 10s 内到达 completed，实际={status!r}",
            f"工作线程还在运行={thread_alive}（若为 False 说明线程已结束，running 是被控制线程回写覆盖的终态）",
            f"残留 rf-task 线程={leftover}",
            _dump_stacks(),
        ]
        pytest.fail("\n".join(detail))

    # 成功路径：任务确实完成，且工作线程干净退出、无残留。
    assert thread_alive is False
    assert leftover == []


def test_set_status_refuses_to_clobber_a_terminal_status(db_session):
    """直击写状态原语：``_set_status`` 绝不把已落终态的任务改回活动态。

    回归钉死（对应修复 A）：原实现是「先 SELECT 判断再盲写」，两步之间存在竞态窗口，
    工作线程抢先提交 completed 后会被 resume() 的 running 覆盖且再无人修正。现改为
    条件 UPDATE（``WHERE status NOT IN 终态``），由数据库原子执行。
    """
    task = _setup_task(db_session, 1)
    runner = _runner(GatedAdapter(threading.Event()))

    # 模拟"工作线程已把任务落为终态 completed"。
    task.status = "completed"
    db_session.commit()

    # 此时控制线程仍尝试把它写成 running（resume 的写法）——必须被拒绝。
    runner._set_status(task.id, "running")

    final = _status(db_session, task.id)
    assert final == "completed", f"终态被 _set_status 覆盖成了 {final!r}"


# ===== 边界攻击：修复 A 的条件 UPDATE 不能误伤正常迁移，也不能并发出事 =====


@pytest.mark.parametrize(
    ("start", "target"),
    [
        ("pending", "paused"),
        ("pending", "stopped"),
        ("running", "paused"),
        ("paused", "running"),
        ("breaker_paused", "running"),
        ("paused", "stopped"),
        ("running", "stopped"),
    ],
)
def test_set_status_allows_normal_lifecycle_transitions(db_session, start, target):
    """活动态之间的正常迁移（含 pause→resume、breaker→resume、→stop）必须照常生效。"""
    task = _setup_task(db_session, 1)
    task.status = start
    db_session.commit()

    runner = _runner(GatedAdapter(threading.Event()))
    runner._set_status(task.id, target)

    assert _status(db_session, task.id) == target, f"{start}→{target} 被条件 UPDATE 误伤"


@pytest.mark.parametrize("terminal", ["completed", "stopped", "failed"])
@pytest.mark.parametrize("target", ["running", "paused", "stopped"])
def test_set_status_never_revives_a_terminal_task(db_session, terminal, target):
    """任何终态都不得被控制接口改回活动态（同状态写入也不动）。"""
    task = _setup_task(db_session, 1)
    task.status = terminal
    db_session.commit()

    runner = _runner(GatedAdapter(threading.Event()))
    runner._set_status(task.id, target)

    assert _status(db_session, task.id) == terminal


def test_concurrent_control_writes_do_not_deadlock_or_raise(db_session):
    """并发 pause/resume/stop 回写同一行：不得抛未处理异常、不得卡死、结果落在合法集合内。"""
    task = _setup_task(db_session, 1)
    task.status = "running"
    db_session.commit()

    runner = _runner(GatedAdapter(threading.Event()))
    errors: list[BaseException] = []

    def _hammer(status: str) -> None:
        try:
            for _ in range(60):
                runner._set_status(task.id, status)
        except BaseException as exc:  # noqa: BLE001 - 并发写不允许把异常漏到线程外
            errors.append(exc)

    threads = [
        threading.Thread(target=_hammer, args=(status,), name=f"qa-ctrl-{status}-{i}")
        for status in ("paused", "running", "stopped")
        for i in range(3)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert not any(t.is_alive() for t in threads), "并发控制写出现卡死（线程未在限时内结束）"
    assert errors == [], f"并发控制写抛出未处理异常：{errors!r}"
    # 一旦 stop 抢先把任务落为终态，后续任何回写都不应把它改回去。
    final = _status(db_session, task.id)
    assert final in {"running", "paused", "stopped"}
    if final == "stopped":
        runner._set_status(task.id, "running")
        assert _status(db_session, task.id) == "stopped", "stop 终态被并发回写复活"
