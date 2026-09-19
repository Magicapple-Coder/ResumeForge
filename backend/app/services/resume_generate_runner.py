"""简历生成后台任务运行器：进程内单例线程 + 状态落库 + 前端轮询。

为什么自建而不用 Celery/RQ：与 ``services/apply/task_runner.py`` 同一条理由——本项目是
单用户本地应用，生成是"几秒到几分钟的阻塞工艺"，一个 ``threading.Thread`` 足够。但
**不复用** ``apply/task_runner.py`` 的 CDP 内核：那是给采集/投递的浏览器驱动、暂停/熔断/
限速用的；简历生成只有"跑一个 async 生成器 + 完成才落库 + 可取消"，两者没有共享的
执行骨架，硬复用反而要把无关的 CDP 依赖拉进来。

纪律（照抄 apply 运行器踩过的坑）：
- 工作线程自己建、自己关 ``SessionLocal()``，会话绝不跨线程共享；
- 流式循环里**每一块 chunk / 事件之后**检查停止信号（用户点取消要真的停得下来）；
- 异常**不许被吞**：兜底把任务置 failed 并写中文 error；
- **完成才落库**：取消/失败不写 ``resume_record``，只更新任务本身——因此中断不产生
  半成品，但结果整体丢失（与 SSE 时代的旧行为一致，进程重启丢进行中任务也接受）。
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Callable

from ..database import SessionLocal
from ..models.job import Job
from ..models.profile import utcnow
from ..models.resume import (
    GENERATE_STATUS_CANCELLED,
    GENERATE_STATUS_COMPLETED,
    GENERATE_STATUS_FAILED,
    GENERATE_STATUS_PENDING,
    GENERATE_STATUS_RUNNING,
    ResumeGenerateTask,
)
from ..schemas.job import JobOut
from ..schemas.resume import GenerateOptions
from ..services import trash
from ..services.claims import build_baseline
from ..services.llm import create_provider
from ..services.llm.base import LLMError
from ..services.profile_service import get_profile_detail, to_profile_out
from ..services.resume_generator import ResumeGenerator
from ..services.settings_service import get_llm_config

logger = logging.getLogger(__name__)

# 已接收字数写库的粒度：没必要每个 chunk 都 commit 一次，但要让前端 1.5s 轮询能看到
# 进展，所以每累计 200 字符落一次。
_CHAR_COMMIT_STEP = 200


class ResumeGenerateRunnerError(Exception):
    """运行器控制类错误（任务未在运行等），message 为中文提示。"""


class _GenerationCancelled(Exception):
    """停止信号在流式循环里被检查到时抛出，用于优雅收尾（不是错误）。"""


class ResumeGenerateRunner:
    """单例运行器：同一时刻只跑一个生成任务。"""

    def __init__(self, *, session_factory: Callable[[], Any] = SessionLocal) -> None:
        self._session_factory = session_factory
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._current_task_id: int | None = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def current_task_id(self) -> int | None:
        return self._current_task_id

    def start(self, task_id: int) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise ResumeGenerateRunnerError("已有简历生成任务正在进行中，请等待其完成")
            self._stop.clear()
            self._current_task_id = task_id
            self._thread = threading.Thread(
                target=self._run, args=(task_id,), name=f"rf-generate-{task_id}", daemon=True
            )
            self._thread.start()

    def cancel(self, task_id: int) -> None:
        # 先落"取消"信号，再与工作线程竞争：若工作线程已跑完并提交终态，终态守卫会拒绝
        # 把 completed/failed 改回 cancelled（照抄 apply 运行器的"终态只读"纪律）。
        self._require_current(task_id)
        self._stop.set()
        self._set_cancelled(task_id)

    def shutdown(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)

    def _require_current(self, task_id: int) -> None:
        if self._current_task_id != task_id or not self.is_running():
            raise ResumeGenerateRunnerError("该任务当前未在运行，无法执行该操作")

    # ===== 工作线程 =====

    def _run(self, task_id: int) -> None:
        session = self._session_factory()
        try:
            task = session.get(ResumeGenerateTask, task_id)
            if task is None:
                return
            # 停止信号早于工作线程读取任务（刚 start 就取消）：与运行中取消同样收尾。
            if self._stop.is_set():
                self._finalize(session, task, GENERATE_STATUS_CANCELLED, error="已取消")
                return

            try:
                job_out, profile_out, baseline, provider = self._snapshot(session, task)
            except Exception as exc:  # noqa: BLE001 - 快照失败转为可读的失败状态
                logger.warning("简历生成任务快照失败 task_id=%s：%s", task_id, exc)
                self._finalize(
                    session,
                    task,
                    GENERATE_STATUS_FAILED,
                    error=str(exc) or "生成准备失败，请查看后端日志",
                )
                return

            task.status = GENERATE_STATUS_RUNNING
            task.started_at = utcnow()
            session.commit()

            options = GenerateOptions.model_validate(task.options or {})
            generator = ResumeGenerator(provider)
            resume: dict | None = None
            warnings: list[str] = []
            raw_parts: list[str] = []
            last_char_commit = 0

            try:
                async def consume() -> None:
                    nonlocal resume, warnings, last_char_commit
                    async for event in generator.generate(
                        profile_out, job_out, options, baseline=baseline
                    ):
                        # 每一块事件之后检查停止信号：取消要在下一次模型输出前生效。
                        if self._stop.is_set():
                            raise _GenerationCancelled()
                        if event["type"] == "progress":
                            task.message = event["message"]
                            session.commit()
                        elif event["type"] == "delta":
                            raw_parts.append(event["text"])
                            received = len("".join(raw_parts))
                            task.received_chars = received
                            # 按字符粒度节流写库：全量进度不需要每块都落一次。
                            if received - last_char_commit >= _CHAR_COMMIT_STEP:
                                last_char_commit = received
                                session.commit()
                        elif event["type"] == "done":
                            resume = event["resume"]
                            warnings = event["warnings"]

                asyncio.run(consume())
            except _GenerationCancelled:
                self._finalize(session, task, GENERATE_STATUS_CANCELLED, error="已取消")
                return
            except asyncio.CancelledError:
                # 防御性：外部取消 async 上下文时同样标 cancelled（照抄 assistant_stream 的中断范式）。
                self._finalize(session, task, GENERATE_STATUS_CANCELLED, error="已取消")
                return
            except LLMError as exc:
                logger.warning("简历生成任务模型调用失败 task_id=%s：%s", task_id, exc)
                self._finalize(session, task, GENERATE_STATUS_FAILED, error=str(exc))
                return
            except Exception:  # noqa: BLE001 - 工作线程异常必须兜底，绝不能静默丢失
                logger.exception("简历生成任务执行发生内部错误 task_id=%s", task_id)
                self._finalize(
                    session,
                    task,
                    GENERATE_STATUS_FAILED,
                    error="生成过程中发生内部错误，请查看后端日志",
                )
                return

            # consume() 正常返回（已拿到 done + 解析出简历）后、写库之前**必须**再复查一次
            # 停止信号：用户可能在 "done 已收到、completed 尚未提交" 这一窗口点取消。不查
            # 这里，取消会被下面无条件写简历的路径吞掉，造成"前端已取消、后端却悄悄落库"。
            if self._stop.is_set():
                self._finalize(session, task, GENERATE_STATUS_CANCELLED, error="已取消")
                return

            if resume is None:
                self._finalize(
                    session, task, GENERATE_STATUS_FAILED, error="模型输出未能解析为有效 JSON"
                )
                return

            # 完成才落库：先原子认领 completed（与 cancel 的 running→cancelled 互斥仲裁），
            # 认领失败说明 cancel 已抢先，直接按 cancelled 收尾、不落简历。认领成功后，把
            # 结果整体写成一条 ResumeRecord，并与任务的 completed 终态在**同一个事务**里
            # 提交。旧实现把"认领 completed"单独 commit、之后再在另一个事务里回填
            # resume_id，中间会暴露"completed 已可见、resume_id 仍为空"的窗口（轮询恰好
            # 落进去就会读到空指针）。这里把仲裁 UPDATE 提前、且不提交：任何观察者要么
            # 看到"未完成"，要么看到"completed + resume_id"；cancel 抢先时更不会留下
            # 孤儿简历记录。仲裁先于 INSERT，也让取消路径不必等待简历写入持有的写锁。
            if not self._claim_completed(session, task.id):
                # cancel 已抢先（running→cancelled）：尚未建简历，按 cancelled 收尾即可。
                self._finalize(session, task, GENERATE_STATUS_CANCELLED, error="已取消")
                return

            try:
                # 迟导入避免 services -> api 的模块级循环依赖（api.resumes 会 import 本模块）。
                from ..api.resumes import _save_record

                raw = "".join(raw_parts)
                # commit=False：只 flush 拿主键，不提交；记录与任务终态同事务落库。
                record = _save_record(
                    session,
                    resume,
                    warnings,
                    job_out,
                    raw,
                    generator.provider.config.model,
                    options.enhance,
                    options.enhancement_level,
                    requested_title=task.title,
                    template=options.template,
                    format_name=options.format_name,
                    page_limit=options.page_limit,
                    font_scale=options.font_scale,
                    custom_instruction=options.custom_instruction,
                    commit=False,
                )
            except Exception:  # noqa: BLE001 - 落库失败不能让任务停在 running
                logger.exception("简历生成结果落库失败 task_id=%s", task_id)
                # 回滚丢弃已执行的认领 UPDATE（running→completed）与半成品记录，再按
                # failed 收尾，避免把"completed 却没有简历"的脏终态提交出去。
                session.rollback()
                self._finalize(
                    session, task, GENERATE_STATUS_FAILED, error="生成结果保存失败，请查看后端日志"
                )
                return

            # 终态字段写进任务对象（未提交）；下面这一次 commit 会把 resume_id 与
            # status=completed 一起提交。
            task.resume_id = record.id
            task.received_chars = len(raw)
            task.message = "简历已生成"
            task.finished_at = utcnow()

            # 原子提交：简历记录 + 任务的 completed 终态在同一事务内对观察者可见。
            session.commit()
        finally:
            session.close()
            with self._lock:
                self._current_task_id = None
                self._thread = None
            self._stop.clear()

    def _snapshot(
        self, session: Any, task: ResumeGenerateTask
    ) -> tuple[JobOut | None, Any, Any, Any]:
        """在后台线程里重建生成所需的只读快照，返回 ``(job_out, profile_out, baseline, provider)``。

        快照在流开始前一次性取齐，随后立即释放请求会话——生成本身是纯计算 + 模型调用，
        不持有数据库连接（与 SSE 路径 ``db.close()`` 的做法一致）。
        """
        job = session.get(Job, task.job_id) if task.job_id is not None else None
        if task.job_id is not None and (job is None or trash.is_deleted(job)):
            raise ResumeGenerateRunnerError("岗位不存在或已被删除")
        job_out = JobOut.model_validate(job) if job is not None else None
        profile = get_profile_detail(session)
        profile_out = to_profile_out(profile)
        baseline = build_baseline(session)
        config = get_llm_config(session)
        if not config.base_url or not config.model:
            raise ResumeGenerateRunnerError("请先在「设置」页配置大模型 API")
        provider = create_provider(config)
        return job_out, profile_out, baseline, provider

    # ===== 状态写入 =====

    def _finalize(
        self, session: Any, task: ResumeGenerateTask, status: str, error: str = ""
    ) -> None:
        task.status = status
        task.finished_at = utcnow()
        if error:
            task.error = error
        session.commit()

    def _claim_completed(self, session: Any, task_id: int) -> bool:
        """原子地把任务从 running 认领为 completed，返回是否认领成功（**不提交**）。

        这是"取消 vs 完成"的**唯一仲裁点**：与 cancel 的 running→cancelled 是两个互斥的
        UPDATE，SQLite 串行化写入下只会有一个成功。认领成功（影响 1 行）后，调用方才在
        **同一事务**里写入简历记录、回填 resume_id 并一次 commit；影响 0 行说明 cancel 已
        先把任务翻成 cancelled，调用方按 cancelled 收尾（此时尚未建简历，无孤儿记录）。

        **提交权交给调用方**：这样 resume_id 与 status=completed 才能落在同一个事务里，
        观察者绝不会看到"completed 但 resume_id 为空"的中间态（旧实现在这里 commit，把
        终态拆成了两个事务）。``synchronize_session=False`` 让 ORM 不回写这条 raw UPDATE
        的结果——调用方此后不再通过 ORM 改 status，避免把原子守卫绕过去。
        """
        from sqlalchemy import update

        statement = (
            update(ResumeGenerateTask)
            .where(ResumeGenerateTask.id == task_id)
            .where(ResumeGenerateTask.status == GENERATE_STATUS_RUNNING)
            .values(status=GENERATE_STATUS_COMPLETED)
            .execution_options(synchronize_session=False)
        )
        result = session.execute(statement)
        return result.rowcount == 1

    def _set_cancelled(self, task_id: int) -> None:
        """取消接口即时落一次状态，让界面立刻看到"已取消"。

        与工作线程并发写同一行，因此用原子 UPDATE + 活动态守卫：只有当前仍是
        pending/running 时才改成 cancelled，绝不把已 completed/failed 的终态盖掉。
        """
        from sqlalchemy import update

        session = self._session_factory()
        try:
            statement = (
                update(ResumeGenerateTask)
                .where(ResumeGenerateTask.id == task_id)
                .where(
                    ResumeGenerateTask.status.in_(
                        (GENERATE_STATUS_RUNNING, GENERATE_STATUS_PENDING)
                    )
                )
                .values(
                    status=GENERATE_STATUS_CANCELLED, error="已取消", finished_at=utcnow()
                )
                .execution_options(synchronize_session=False)
            )
            session.execute(statement)
            session.commit()
        except Exception:  # noqa: BLE001 - 与工作线程并发写时可能短暂锁库，忽略即可
            logger.warning("更新生成任务取消状态失败 task_id=%s", task_id)
        finally:
            session.close()


_RUNNER: ResumeGenerateRunner | None = None
_RUNNER_LOCK = threading.Lock()


def get_resume_generate_runner() -> ResumeGenerateRunner:
    """进程内共享的生成运行器单例。"""
    global _RUNNER
    with _RUNNER_LOCK:
        if _RUNNER is None:
            _RUNNER = ResumeGenerateRunner()
        return _RUNNER


def reset_resume_generate_runner() -> None:
    """测试用：释放单例，避免用例之间共享线程状态。"""
    global _RUNNER
    with _RUNNER_LOCK:
        if _RUNNER is not None:
            _RUNNER.shutdown()
        _RUNNER = None


__all__ = [
    "ResumeGenerateRunner",
    "ResumeGenerateRunnerError",
    "get_resume_generate_runner",
    "reset_resume_generate_runner",
]
