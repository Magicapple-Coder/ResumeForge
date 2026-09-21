"""进程内单例任务运行器：一个工作线程 + 状态落库 + 前端轮询。

为什么自建而不用框架：本项目是单用户本地应用，投递/采集是"几分钟到几十分钟的同步阻塞
工艺"，引入 Celery/RQ 只会增加部署成本。一个 ``threading.Thread`` 足够，但必须守住几条
纪律，否则会变成"停不下来的后台线程"：

- 工作线程**自己建、自己关** ``SessionLocal()``，会话绝不跨线程共享；
- **每一次 CDP 调用前后**都检查停止/暂停信号（用户点停止要真的停得下来）；
- 工作线程的异常**不许被吞**：兜底把任务置失败并写中文 ``message``；
- 连续失败达阈值**熔断**并醒目提示；每日上限**只计成功投递**。
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Sequence
from typing import Any, Callable

from sqlalchemy import update

from ...config import captures_dir
from ...database import SessionLocal
from ...models.apply import (
    ITEM_STATUS_PENDING,
    ITEM_STATUS_SKIPPED,
    STEP_IDLE,
    STEP_OPENING,
    STOP_REASON_ERROR,
    STOP_REASON_USER,
    TASK_KIND_COLLECT,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_PAUSED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_STOPPED,
    ApplyTask,
    ApplyTaskItem,
)
from ...models.profile import utcnow
from ..browser.cdp_client import CdpClient
from . import task_apply, task_collect, task_config

logger = logging.getLogger(__name__)

# 任务终态集合：一旦任务落进这里就表示"这件事结束了"，任何控制接口（暂停 / 恢复 / 停止）
# 都不许再把它改回活动态。用途见 ``TaskRunner._set_status``——它正是 pause/resume 竞态的
# 收敛点：工作线程抢先提交 ``completed`` 后，``resume()`` 的 ``_set_status(RUNNING)`` 必须
# 让位，否则终态会被盖回 ``running`` 且再无人修正，任务永久卡住。
_TERMINAL_STATUSES = frozenset(
    {TASK_STATUS_COMPLETED, TASK_STATUS_STOPPED, TASK_STATUS_FAILED}
)


_is_within = task_collect.is_within


class TaskStopped(Exception):
    """停止信号在步骤之间被检查到时抛出，用于优雅收尾（不是错误）。"""


class TaskRunnerError(Exception):
    """运行器控制类错误（任务未在运行、已有任务在跑等），message 为中文提示。"""


_ItemSkip = task_apply.ItemSkip


class StopAwareCdpClient(CdpClient):
    """包一层 CdpClient，在每次 CDP 调用前检查停止/暂停信号。

    这样即使用户在某个岗位投递的**中途**点停止，也能在"下一次 CDP 调用前"及时退出，
    而不是等整个岗位跑完——这直接对应"停止信号必须在步骤之间被检查到"的硬要求。
    """

    def __init__(self, inner: CdpClient, checkpoint: Callable[[], None]) -> None:
        self._inner = inner
        self._checkpoint = checkpoint

    def _guard(self) -> None:
        self._checkpoint()

    def list_targets(self) -> list[dict[str, Any]]:
        self._guard()
        return self._inner.list_targets()

    def new_tab(self, url: str = "about:blank") -> str:
        self._guard()
        return self._inner.new_tab(url)

    def send(
        self, method: str, params: dict[str, Any] | None = None, *, timeout: float | None = None
    ) -> dict[str, Any]:
        self._guard()
        return self._inner.send(method, params, timeout=timeout)

    def evaluate(self, expression: str, *, timeout: float | None = None) -> Any:
        self._guard()
        return self._inner.evaluate(expression, timeout=timeout)

    def set_file_input(self, selector: str, files: list[str], *, timeout: float | None = None) -> None:
        self._guard()
        return self._inner.set_file_input(selector, files, timeout=timeout)

    def navigate(self, url: str, *, timeout: float | None = None) -> dict[str, Any]:
        self._guard()
        return self._inner.navigate(url, timeout=timeout)

    # 事件订阅必须**显式转发**。``CdpClient`` 给这三个方法提供了"不支持"的空实现，
    # 所以忘了转发不会报错：它安静地返回空事件列表，而站点适配器把"没拦到响应"当作
    # "接口这条路走不通"，于是退回 DOM——**离线测试全绿，生产里网络优先却从未生效**。
    def start_event_capture(self, methods: Sequence[str]) -> None:
        self._guard()
        self._inner.start_event_capture(methods)

    def stop_event_capture(self) -> None:
        # 取走缓冲是纯本地操作，不发 CDP、不等待，所以不插停止检查点：这里抛异常
        # 会让已经拦到的响应白白丢掉。
        self._inner.stop_event_capture()

    def drain_events(self) -> list[dict[str, Any]]:
        return self._inner.drain_events()

    # 窗口可见性与标签页切换同样必须**显式转发**（可选能力，基类没有强制）：
    # - ensure_page_visible：BOSS 对隐藏窗口（最小化 / 被遮挡 / 其他虚拟桌面）上的点击
    #   静默忽略——不还原窗口，可信点击点了也白点，投递会在"等聊天页"上超时。
    # - switch_to_target：点击「立即沟通」后聊天页可能开在新标签页，适配器要在快照比对
    #   后切换过去填写与发送。
    def ensure_page_visible(self, *, timeout_seconds: float = 8.0) -> bool:
        self._guard()
        ensure = getattr(self._inner, "ensure_page_visible", None)
        if ensure is None:
            return False
        return ensure(timeout_seconds=timeout_seconds)

    def switch_to_target(self, target_id: str) -> bool:
        self._guard()
        switch = getattr(self._inner, "switch_to_target", None)
        if switch is None:
            return False
        return switch(target_id)

    def close(self) -> None:
        self._inner.close()


class TaskRunner:
    """单例任务运行器：同一时刻只跑一个批次（投递或采集）。"""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Any] = SessionLocal,
        registry: Any = None,
        client_factory: Callable[[Any], CdpClient] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        poll_interval: float = 0.2,
    ) -> None:
        self._session_factory = session_factory
        self._registry = registry
        self._client_factory = client_factory
        self._sleeper = sleeper
        self._clock = clock
        self._poll = poll_interval
        self._stop = threading.Event()
        self._resume = threading.Event()
        self._resume.set()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._current_task_id: int | None = None

    # ===== 控制接口 =====

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def current_task_id(self) -> int | None:
        return self._current_task_id

    def start(self, task_id: int) -> None:
        """启动一个任务批次：登记运行态并起后台线程；已有任务在跑则抛 TaskRunnerError。"""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise TaskRunnerError("已有任务正在进行中，请先停止或等待其完成")
            self._stop.clear()
            self._resume.set()
            self._current_task_id = task_id
            self._thread = threading.Thread(
                target=self._run, args=(task_id,), name=f"rf-task-{task_id}", daemon=True
            )
            self._thread.start()

    def pause(self, task_id: int) -> None:
        # 先落"暂停"再/与工作线程检查点竞争：若工作线程此刻已跑完并提交终态，
        # _set_status 的终态守卫会拒绝把 completed/stopped/failed 改回 paused。
        self._require_current(task_id)
        self._resume.clear()
        self._set_status(task_id, TASK_STATUS_PAUSED)

    def resume(self, task_id: int) -> None:
        # 唤醒工作线程（_resume.set）后写 running 是竞态高发点：worker 可能在写入前就跑完，
        # 因此必须以"当前状态是否已是终态"为准，而不是无条件回写 running（见 _set_status）。
        self._require_current(task_id)
        self._resume.set()
        self._set_status(task_id, TASK_STATUS_RUNNING)

    def stop(self, task_id: int) -> None:
        # 停止目标本身即终态：若任务其实已经 completed（用户点慢了一步），
        # 终态守卫会保留原终态，不把成功的任务误标成 stopped。
        self._require_current(task_id)
        self._stop.set()
        self._resume.set()  # 释放可能正卡在暂停等待里的工作线程
        self._set_status(task_id, TASK_STATUS_STOPPED, STOP_REASON_USER)

    def shutdown(self) -> None:
        self._stop.set()
        self._resume.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)

    def _require_current(self, task_id: int) -> None:
        if self._current_task_id != task_id or not self.is_running():
            raise TaskRunnerError("该任务当前未在运行，无法执行该操作")

    # ===== 工作线程 =====

    def _run(self, task_id: int) -> None:
        session = self._session_factory()  # 工作线程自建会话
        task: ApplyTask | None = None
        try:
            task = session.get(ApplyTask, task_id)
            if task is None:
                return
            if self._stop.is_set():
                # 停止信号早于工作线程读取任务（如刚 start 就 stop）：与运行中停止保持一致地收尾，
                # 否则会留下"已停止但没有结束时间、条目仍待投递"的半截记录。
                self._finalize_early_stop(session, task)
                return
            task.status = TASK_STATUS_RUNNING
            task.started_at = utcnow()
            task.current_step = STEP_OPENING
            session.commit()
            if task.kind == TASK_KIND_COLLECT:
                self._run_collect(session, task)
            else:
                self._run_apply(session, task)
        except TaskStopped:
            self._finalize(session, task, TASK_STATUS_STOPPED, STOP_REASON_USER)
        except Exception:  # noqa: BLE001 - 工作线程异常必须兜底，绝不能静默丢失
            logger.exception("投递/采集任务执行发生内部错误 task_id=%s", task_id)
            self._finalize(
                session, task, TASK_STATUS_FAILED, STOP_REASON_ERROR, message="任务执行发生内部错误，请查看后端日志"
            )
        finally:
            session.close()  # 工作线程自关会话
            with self._lock:
                self._current_task_id = None
                self._thread = None
            self._stop.clear()
            self._resume.set()

    # ===== 投递批次 =====

    def _run_apply(self, session: Any, task: ApplyTask) -> None:
        task_apply.run_apply(
            self,
            session,
            task,
            stopped_error=TaskStopped,
            wrap_client=lambda client: StopAwareCdpClient(client, self._checkpoint),
            log=logger,
        )

    def _execute_item(
        self,
        session: Any,
        task: ApplyTask,
        item: ApplyTaskItem,
        config: Any,
        client: CdpClient,
        registry: Any,
        apply_service: Any,
    ) -> None:
        task_apply.execute_item(session, task, item, config, client, registry, apply_service)

    # ===== 采集批次 =====

    def _run_collect(self, session: Any, task: ApplyTask) -> None:
        task_collect.run_collect(
            self,
            session,
            task,
            stopped_error=TaskStopped,
            wrap_client=lambda client: StopAwareCdpClient(client, self._checkpoint),
            captures_root_factory=captures_dir,
            log=logger,
        )

    def _collect_adapter(self, session: Any, registry: Any) -> Any:
        return task_collect.collect_adapter(session, registry, self._collect_site_key)

    @staticmethod
    def _collect_site_key(session: Any) -> str:
        return task_collect.collect_site_key(session, log=logger)

    @staticmethod
    def _record_failure_category(task: ApplyTask, category: str) -> None:
        task_collect.record_failure_category(task, category)

    @staticmethod
    def _record_sample_result(task: ApplyTask, recorder: Any) -> None:
        task_collect.record_sample_result(task, recorder)

    @staticmethod
    def _collect_message(task: ApplyTask) -> str:
        return task_collect.collect_message(task)

    @staticmethod
    def _backfill_message(config: dict[str, Any]) -> str:
        return task_collect.backfill_message(config)

    # ===== 信号检查 =====

    def _checkpoint(self) -> None:
        """步骤之间检查信号：停止则抛 ``TaskStopped``，暂停则阻塞等待。"""
        while not self._resume.is_set():
            if self._stop.is_set():
                raise TaskStopped()
            self._resume.wait(timeout=self._poll)
        if self._stop.is_set():
            raise TaskStopped()

    def _wait_resume_or_stop(self) -> bool:
        """阻塞直到恢复运行；返回 False 表示期间用户点了停止。"""
        while not self._resume.wait(timeout=self._poll):
            if self._stop.is_set():
                return False
        return not self._stop.is_set()

    def _interruptible_sleep(self, interval: int, jitter: int) -> bool:
        return task_apply.interruptible_sleep(self, interval, jitter)

    # ===== 状态写入 =====

    def _mark_failed(
        self, session: Any, task: ApplyTask, item: ApplyTaskItem, category: str, detail: str
    ) -> None:
        task_apply.mark_failed(session, task, item, category, detail)

    def _pause_with_message(self, session: Any, task: ApplyTask, message: str) -> None:
        task_apply.pause_with_message(self, session, task, message)

    def _breaker_pause(self, session: Any, task: ApplyTask, count: int) -> None:
        task_apply.breaker_pause(self, session, task, count)

    def _stop_remaining(
        self,
        session: Any,
        task: ApplyTask,
        items: list[ApplyTaskItem],
        start_index: int,
        *,
        reason: str,
        message: str,
    ) -> None:
        for item in items[start_index:]:
            if item.status == ITEM_STATUS_PENDING:
                item.status = ITEM_STATUS_SKIPPED
                item.finished_at = utcnow()
                task.skipped += 1
        task.status = TASK_STATUS_STOPPED
        task.stop_reason = reason
        task.current_step = STEP_IDLE
        task.finished_at = utcnow()
        if message:
            task.message = message
        session.commit()

    def _finalize_early_stop(self, session: Any, task: ApplyTask) -> None:
        """工作线程尚未开始就收到停止信号时的收尾（与运行中停止同一形态）。

        直接复用 ``_stop_remaining``：写 ``finished_at``、把未处理条目标为 ``skipped``，并落
        ``stopped / user``。采集批次没有 ``apply_task_item`` 条目，此时仅收尾任务本身，行为与
        ``_run_collect`` 的停止路径一致。
        """
        items = (
            session.query(ApplyTaskItem)
            .filter(ApplyTaskItem.task_id == task.id)
            .order_by(ApplyTaskItem.sort_order, ApplyTaskItem.id)
            .all()
        )
        self._stop_remaining(session, task, items, 0, reason=STOP_REASON_USER, message="")

    def _finalize(
        self, session: Any, task: ApplyTask | None, status: str, reason: str, message: str = ""
    ) -> None:
        if task is None:
            return
        task.status = status
        task.stop_reason = reason
        task.current_step = STEP_IDLE
        task.finished_at = utcnow()
        if message:
            task.message = message
        session.commit()

    def _set_status(self, task_id: int, status: str, reason: str = "") -> None:
        """在控制接口里即时落一次状态，让界面立刻看到"已暂停/已停止"。

        **终态只读，且必须原子**：``pause()`` / ``resume()`` / ``stop()`` 与工作线程并发写
        同一行。工作线程可能在这一瞬间跑完并提交了终态（``completed`` / ``stopped`` /
        ``failed``）。若这里先 ``SELECT`` 判断再 ``UPDATE``，两步之间就存在一个窗口——
        工作线程的终态提交恰好落在窗口里，随后这次**盲写**会把终态盖回活动态；工作线程已退出，
        再没有人会修正它，任务于是永久卡在 ``running``（违反"暂停可恢复"）。

        因此这里不做"读—判—写"，而是把守卫直接写进 ``WHERE``：只有当**当前仍是活动态**且
        与目标不同才更新。整条 ``UPDATE`` 由数据库原子执行，与工作线程的提交严格串行——
        谁先提交谁生效：控制写在前会被工作线程的终态覆盖，控制写在后则因 ``WHERE`` 不成立
        而彻底不生效。无论如何终态都不会被活动态回写覆盖。

        守卫只加在**控制接口的这条回写路径**上；工作线程自己的提交路径
        （``_finalize`` / ``_stop_remaining`` / ``_finalize_early_stop``）不经此方法，始终
        保有写终态的能力，故不受影响。
        """
        session = self._session_factory()
        try:
            values: dict[str, Any] = {"status": status}
            if reason:
                values["stop_reason"] = reason
            statement = (
                update(ApplyTask)
                .where(ApplyTask.id == task_id)
                .where(ApplyTask.status.notin_(_TERMINAL_STATUSES))
                .where(ApplyTask.status != status)
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            result = session.execute(statement)
            changed = result.rowcount or 0
            session.commit()
            if changed == 0:
                # 没改动：可能是任务已是终态（被拒绝），也可能目标状态与现状相同。读一次只为
                # 留下可检索的日志，不参与写入决策。
                current = session.get(ApplyTask, task_id)
                if current is not None and current.status in _TERMINAL_STATUSES:
                    logger.warning(
                        "拒绝把终态任务改回活动态：task_id=%s 当前状态=%s 目标状态=%s（工作线程已提交终态，控制接口回写让位）",
                        task_id,
                        current.status,
                        status,
                    )
        except Exception:  # noqa: BLE001 - 与工作线程并发写时可能短暂锁库，忽略即可
            logger.warning("更新任务状态失败 task_id=%s", task_id)
        finally:
            session.close()

    # ===== 依赖装配 =====

    def _make_client(self, config: Any) -> CdpClient:
        if self._client_factory is not None:
            return self._client_factory(config)
        from . import apply_service

        session = self._session_factory()
        try:
            manager = apply_service.get_browser_manager(session)
            return manager.client()
        finally:
            session.close()

    @staticmethod
    def _load_config(task: ApplyTask, model: type, *, ignore: Sequence[str] = ()) -> Any:
        return task_config.load_config(task, model, ignore=ignore, log=logger)

    @staticmethod
    def _backfill_job_ids(task: ApplyTask) -> list[int]:
        return task_config.backfill_job_ids(task)


_RUNNER: TaskRunner | None = None
_RUNNER_LOCK = threading.Lock()


def get_task_runner() -> TaskRunner:
    """进程内共享的运行器单例。"""
    global _RUNNER
    with _RUNNER_LOCK:
        if _RUNNER is None:
            _RUNNER = TaskRunner()
        return _RUNNER


def reset_task_runner() -> None:
    """测试用：释放单例，避免用例之间共享线程状态。"""
    global _RUNNER
    with _RUNNER_LOCK:
        if _RUNNER is not None:
            _RUNNER.shutdown()
        _RUNNER = None


__all__ = [
    "StopAwareCdpClient",
    "TaskRunner",
    "TaskRunnerError",
    "TaskStopped",
    "get_task_runner",
    "reset_task_runner",
]
