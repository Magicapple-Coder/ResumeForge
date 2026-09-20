"""投递批次执行：逐条投递、失败隔离、熔断与成功回写。"""
from __future__ import annotations

import logging
import random
from typing import Any, Callable

from ...models.apply import (
    FAILURE_CAPTCHA_REQUIRED,
    FAILURE_NETWORK_TIMEOUT,
    FAILURE_UNKNOWN,
    ITEM_STATUS_FAILED,
    ITEM_STATUS_RUNNING,
    ITEM_STATUS_SKIPPED,
    ITEM_STATUS_SUCCESS,
    STEP_FILLING,
    STEP_IDLE,
    STEP_OPENING,
    STEP_SUBMITTING,
    STEP_VERIFYING,
    STOP_REASON_BREAKER,
    STOP_REASON_DONE,
    STOP_REASON_ERROR,
    STOP_REASON_USER,
    TASK_STATUS_BREAKER_PAUSED,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_PAUSED,
    ApplyTask,
    ApplyTaskItem,
)
from ...models.job import Job
from ...models.profile import utcnow
from ...schemas.apply import ApplyConfigIn
from .. import tracker
from ..browser.cdp_client import CdpClient, CdpError
from ..sites.base import SiteFailure
from ..sites.registry import get_registry

logger = logging.getLogger(__name__)


class ItemSkip(Exception):
    """单个条目的软跳过，不计失败且不触发熔断。"""


def interruptible_sleep(runner: Any, interval: int, jitter: int) -> bool:
    """岗位间限速等待；暂停可恢复，停止可即时打断。"""
    total = max(0, interval)
    if jitter:
        total += random.uniform(0, jitter)
    if total <= 0:
        return True
    end = runner._clock() + total
    while True:
        if runner._stop.is_set():
            return False
        if not runner._resume.is_set() and not runner._wait_resume_or_stop():
            return False
        remaining = end - runner._clock()
        if remaining <= 0:
            return True
        runner._sleeper(min(0.2, remaining))


def mark_failed(
    session: Any, task: ApplyTask, item: ApplyTaskItem, category: str, detail: str
) -> None:
    item.status = ITEM_STATUS_FAILED
    item.failure_category = category
    item.failure_detail = detail
    item.finished_at = utcnow()
    task.processed += 1
    task.failed += 1
    session.commit()


def pause_with_message(runner: Any, session: Any, task: ApplyTask, message: str) -> None:
    runner._resume.clear()
    task.status = TASK_STATUS_PAUSED
    task.message = message
    session.commit()


def breaker_pause(runner: Any, session: Any, task: ApplyTask, count: int) -> None:
    runner._resume.clear()
    task.status = TASK_STATUS_BREAKER_PAUSED
    task.stop_reason = STOP_REASON_BREAKER
    task.message = f"已因连续 {count} 次失败自动暂停，请查看记录并处理后点击「继续」"
    session.commit()


def run_apply(
    runner: Any,
    session: Any,
    task: ApplyTask,
    *,
    stopped_error: type[Exception],
    wrap_client: Callable[[CdpClient], CdpClient],
    log: logging.Logger = logger,
) -> None:
    """执行一个投递批次；生命周期与控制信号由 ``runner`` 提供。"""
    from . import apply_service

    config = runner._load_config(task, ApplyConfigIn)
    items = (
        session.query(ApplyTaskItem)
        .filter(ApplyTaskItem.task_id == task.id)
        .order_by(ApplyTaskItem.sort_order, ApplyTaskItem.id)
        .all()
    )
    try:
        client = runner._make_client(config)
    except Exception as exc:  # noqa: BLE001 - 连不上浏览器是可直接展示的失败
        runner._finalize(
            session,
            task,
            TASK_STATUS_FAILED,
            STOP_REASON_ERROR,
            message=str(exc) or "无法连接投递专用浏览器，请先在投递台启动浏览器",
        )
        return

    wrapped = wrap_client(client)
    registry = runner._registry or get_registry()
    consecutive = 0
    try:
        for index, item in enumerate(items):
            try:
                runner._checkpoint()
                if apply_service.daily_success_count(session) >= config.daily_limit:
                    runner._stop_remaining(
                        session,
                        task,
                        items,
                        index,
                        reason=STOP_REASON_DONE,
                        message=f"今日投递已达上限（{config.daily_limit}），剩余岗位已跳过",
                    )
                    return
                item.status = ITEM_STATUS_RUNNING
                item.attempt += 1
                item.started_at = utcnow()
                task.current_step = STEP_OPENING
                session.commit()
                runner._execute_item(session, task, item, config, wrapped, registry, apply_service)
            except stopped_error:
                item.status = ITEM_STATUS_SKIPPED
                item.failure_detail = "用户停止了任务，当前岗位未完成"
                item.finished_at = utcnow()
                task.skipped += 1
                session.commit()
                runner._stop_remaining(
                    session, task, items, index + 1, reason=STOP_REASON_USER, message=""
                )
                return
            except ItemSkip as exc:
                item.status = ITEM_STATUS_SKIPPED
                item.failure_detail = str(exc)
                item.finished_at = utcnow()
                task.processed += 1
                task.skipped += 1
                session.commit()
            except SiteFailure as exc:
                runner._mark_failed(session, task, item, exc.category, exc.detail)
                consecutive += 1
            except CdpError as exc:
                runner._mark_failed(session, task, item, FAILURE_NETWORK_TIMEOUT, str(exc))
                consecutive += 1
            except Exception:  # noqa: BLE001 - 单岗位异常不能打死整个批次
                log.exception("投递单个岗位失败 task_id=%s item_id=%s", task.id, item.id)
                runner._mark_failed(
                    session, task, item, FAILURE_UNKNOWN, "投递时发生内部错误，请查看后端日志"
                )
                consecutive += 1
            else:
                item.status = ITEM_STATUS_SUCCESS
                item.finished_at = utcnow()
                task.processed += 1
                task.succeeded += 1
                session.commit()
                consecutive = 0
                apply_service.write_back_job_status(session, item.job_id)
                apply_service.mark_queue_done(session, item.job_id)
                tracker.record_applied(
                    session,
                    company=item.company,
                    title=item.job_title,
                    job_id=item.job_id,
                )
                session.commit()

            if item.status == ITEM_STATUS_FAILED:
                if item.failure_category == FAILURE_CAPTCHA_REQUIRED:
                    runner._pause_with_message(
                        session,
                        task,
                        "站点出现验证码或安全验证：请在浏览器窗口里完成验证后点击「继续」",
                    )
                    if not runner._wait_resume_or_stop():
                        raise stopped_error()
                    consecutive = 0
                elif consecutive >= config.breaker_threshold:
                    runner._breaker_pause(session, task, consecutive)
                    if not runner._wait_resume_or_stop():
                        raise stopped_error()
                    consecutive = 0

            if index < len(items) - 1 and not runner._interruptible_sleep(
                config.interval_seconds, config.interval_jitter_seconds
            ):
                raise stopped_error()

        task.current_step = STEP_IDLE
        task.status = TASK_STATUS_COMPLETED
        task.stop_reason = STOP_REASON_DONE
        task.finished_at = utcnow()
        task.message = task.message or "投递任务已完成"
        session.commit()
    except stopped_error:
        runner._stop_remaining(session, task, items, 0, reason=STOP_REASON_USER, message="")
    finally:
        client.close()


def execute_item(
    session: Any,
    task: ApplyTask,
    item: ApplyTaskItem,
    config: ApplyConfigIn,
    client: CdpClient,
    registry: Any,
    apply_service: Any,
) -> None:
    """执行单个岗位投递；保持站点适配器之外的流程站点无关。"""
    job = session.get(Job, item.job_id) if item.job_id else None
    if job is None:
        raise ItemSkip("岗位已被删除，跳过该条目")
    adapter = registry.for_job(job)
    resume = apply_service.resolve_resume(session, job.id, item.resume_id)
    if resume is None and adapter.requires_resume:
        raise ItemSkip("未找到可用简历：请先在简历中心为该岗位生成简历后再投递")
    data = apply_service.build_apply_data(session, resume)
    greeting = (item.greeting or "").strip() or config.default_greeting

    task.current_step = STEP_FILLING
    session.commit()
    adapter.open_apply(client, job)
    task.current_step = STEP_SUBMITTING
    session.commit()
    outcome = adapter.fill_and_submit(client, data, greeting)
    task.current_step = STEP_VERIFYING
    session.commit()
    if not outcome.success:
        raise SiteFailure(FAILURE_UNKNOWN, "未能确认投递成功，请在浏览器中核对")
    if outcome.greeting_sent:
        item.greeting = outcome.greeting_sent


__all__ = [
    "ItemSkip",
    "breaker_pause",
    "execute_item",
    "interruptible_sleep",
    "mark_failed",
    "pause_with_message",
    "run_apply",
]
