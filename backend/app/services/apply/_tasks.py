"""任务查询与批次创建（投递 / 采集 / 补详情）。"""
from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy.orm import Session

from ...models.apply import (
    ADMISSION_BLOCK,
    QUEUE_STATUS_PENDING,
    STOP_REASON_ERROR,
    TASK_KIND_APPLY,
    TASK_KIND_COLLECT,
    TASK_STATUS_FAILED,
    TASK_STATUS_PENDING,
    ApplyQueueItem,
    ApplyTask,
    ApplyTaskItem,
)
from ...models.job import Job
from ...models.profile import utcnow
from ...schemas.apply import MAX_BACKFILL_JOBS, ApplyTaskCreate
from ..sites.registry import get_registry
from ._base import ACTIVE_TASK_STATUSES, ApplyBadRequest, ApplyConflict, ApplyNotFound, _clip_greeting
from ._config import get_apply_config, get_collect_config
from ._match import _admission_of_match, _blocking_gaps, latest_match
from ._queue import job_apply_site, resolve_resume
from ._records import daily_success_count

logger = logging.getLogger(__name__)
def current_task(db: Session, *, kind: str | None = None) -> ApplyTask | None:
    query = db.query(ApplyTask).filter(ApplyTask.status.in_(ACTIVE_TASK_STATUSES))
    if kind is not None:
        query = query.filter(ApplyTask.kind == kind)
    return query.order_by(ApplyTask.id.desc()).first()


def get_task_detail(db: Session, task_id: int) -> ApplyTask:
    task = db.get(ApplyTask, task_id)
    if task is None:
        raise ApplyNotFound("投递任务不存在或已被删除")
    return task


def _resolve_targets(db: Session, payload: ApplyTaskCreate) -> list[tuple[Job, ApplyQueueItem | None]]:
    targets: list[tuple[Job, ApplyQueueItem | None]] = []
    if payload.job_ids:
        for job_id in payload.job_ids:
            job = db.get(Job, job_id)
            if job is None:
                raise ApplyNotFound(f"岗位不存在或已被删除：{job_id}")
            queue_item = (
                db.query(ApplyQueueItem)
                .filter(ApplyQueueItem.job_id == job_id)
                .one_or_none()
            )
            if queue_item is None:
                # 直接指定（未走队列）的岗位仍须过准入：真实缺口必须先确认。
                # 读不出结论（admission is None）在这里与 needs_confirm 同级——两者都不在此阻断，
                # 真正的"未知不得默认放行"闸门在入队侧（add_to_queue / _match_requires_confirm）。
                match = latest_match(db, job_id)
                if match is not None and _admission_of_match(match) == ADMISSION_BLOCK:
                    raise ApplyConflict(
                        {
                            "message": f"「{job.title or '该岗位'}」存在真实缺口，请先在投递台加入队列并确认",
                            "job_id": job_id,
                            "gaps": _blocking_gaps(match.result),
                        }
                    )
            targets.append((job, queue_item))
    elif payload.use_queue:
        items = (
            db.query(ApplyQueueItem)
            .filter(ApplyQueueItem.status == QUEUE_STATUS_PENDING)
            .order_by(ApplyQueueItem.sort_order, ApplyQueueItem.id)
            .all()
        )
        for queue_item in items:
            job = db.get(Job, queue_item.job_id) if queue_item.job_id else None
            if job is None:
                continue  # 岗位已删除的队列条目直接跳过（快照仍在队列里可读）
            targets.append((job, queue_item))
    else:
        raise ApplyBadRequest("请先选择要投递的岗位（传入 job_ids 或 use_queue=true）")

    # 按岗位去重、保序。
    seen: set[int] = set()
    unique: list[tuple[Job, ApplyQueueItem | None]] = []
    for job, queue_item in targets:
        if job.id in seen:
            continue
        seen.add(job.id)
        unique.append((job, queue_item))

    # 来源闸门：不是从已注册招聘网站来的岗位，投递时定位不到站点适配器，只会得到一条
    # 「未知失败」记录。**在这里一次性拦住并说清是谁**，而不是让它逐条失败给用户看。
    # 队列里出现这类条目只可能是历史遗留（新入队已被 add_to_queue 挡住），所以文案指向"移出队列"。
    unsupported = [job for job, _ in unique if job_apply_site(job) is None]
    if unsupported:
        titles = "、".join(f"「{job.title or '未命名岗位'}」" for job in unsupported[:5])
        more = f" 等 {len(unsupported)} 个" if len(unsupported) > 5 else ""
        raise ApplyConflict(
            {
                "message": (
                    f"{titles}{more}不是从投递台支持的招聘网站采集或导入的岗位"
                    f"（当前支持：{get_registry().supported_names()}），无法自动投递。"
                    "请先把它们移出投递队列（行末「更多操作 → 移出队列」），或改到对应网站上手动投递。"
                ),
                "site_unsupported": True,
                "job_ids": [job.id for job in unsupported],
                "job_titles": [job.title for job in unsupported],
            }
        )
    return unique


def create_apply_task(db: Session, payload: ApplyTaskCreate) -> ApplyTask:
    """显式开始投递：建批次 + 逐条记录，再把批次交给单例运行器。"""
    from . import task_runner

    runner = task_runner.get_task_runner()
    if runner.is_running():
        raise ApplyConflict("已有任务正在进行中，请先停止或等待其完成")

    config = get_apply_config(db)
    targets = _resolve_targets(db, payload)
    if not targets:
        raise ApplyBadRequest("队列为空或所选岗位无效，没有可投递的岗位")
    if daily_success_count(db) >= config.daily_limit:
        raise ApplyConflict(f"今日投递已达上限（{config.daily_limit}），请明天再试或调高上限")

    targets = targets[: config.per_task_limit]
    task = ApplyTask(
        kind=TASK_KIND_APPLY,
        status=TASK_STATUS_PENDING,
        total=len(targets),
        config=config.model_dump(),
    )
    db.add(task)
    db.flush()
    for index, (job, queue_item) in enumerate(targets):
        resume = resolve_resume(
            db, job.id, queue_item.resume_id if queue_item is not None else None
        )
        db.add(
            ApplyTaskItem(
                task_id=task.id,
                job_id=job.id,
                job_title=job.title,
                company=job.company,
                resume_id=resume.id if resume is not None else None,
                resume_title=resume.title if resume is not None else "",
                greeting=_clip_greeting(queue_item.greeting) if queue_item is not None else "",
                sort_order=index,
            )
        )
    db.commit()
    db.refresh(task)
    runner.start(task.id)
    return task


def create_collect_task(db: Session, *, save_site_samples: bool = False) -> ApplyTask:
    """显式开始采集：用已保存的采集配置建一个 kind=collect 批次。

    ``save_site_samples`` 是**每次采集一次性**的开关（是否保存本次抓到的站点原文）。
    它不属于采集配置，所以刻意**不放进** ``CollectConfigIn``（那是 ``extra="forbid"`` 的公开
    配置模型）；只有为真时才写进 ``task.config``，为假就不放这个键——保持旧任务的 config 形状
    不变（与 ``backfill_job_ids`` 同一套做法，见 ``task_runner._load_config`` 的 ``ignore``）。
    """
    from . import task_runner

    runner = task_runner.get_task_runner()
    if runner.is_running():
        raise ApplyConflict("已有任务正在进行中，请先停止或等待其完成")

    config = get_collect_config(db)
    if not config.keywords and not config.city.strip():
        raise ApplyBadRequest("请先设置采集关键词或城市后再开始采集")

    task_config = config.model_dump()
    if save_site_samples:
        task_config["save_site_samples"] = True

    task = ApplyTask(
        kind=TASK_KIND_COLLECT,
        status=TASK_STATUS_PENDING,
        total=config.per_task_limit,
        config=task_config,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    runner.start(task.id)
    return task


def create_backfill_task(db: Session, job_ids: Sequence[int]) -> ApplyTask:
    """按岗位 id 只补抓详情，修"当年采集时详情没抓到、JD 为空"的历史数据。

    复用采集任务的一整套机制（浏览器会话、详情抓取、限速、暂停/停止、进度显示），所以它仍然是一个
    ``kind=collect`` 批次，只是把"这一批岗位从哪儿来"从关键词翻页换成用户点名，写进
    ``config['backfill_job_ids']``。
    """
    from . import task_runner

    runner = task_runner.get_task_runner()
    if runner.is_running():
        raise ApplyConflict("已有任务正在进行中，请先停止或等待其完成")

    # 去重并保序：用户可能重复勾选，前端分批提交时也可能出现重复 id。
    ids = list(dict.fromkeys(int(job_id) for job_id in job_ids))
    if not ids:
        raise ApplyBadRequest("请先选择要补齐详情的岗位")
    if len(ids) > MAX_BACKFILL_JOBS:
        raise ApplyBadRequest(
            f"一次最多补齐 {MAX_BACKFILL_JOBS} 个岗位的详情（当前选了 {len(ids)} 个）："
            "补详情要逐个打开岗位页面，很慢，请分批操作。"
        )

    # 这里**不**预先过滤"描述为空的岗位"——是否真的需要补由采集器的 ``_backfill`` 统一判断
    # （已有描述 / 没有投递链接 / 在回收站里都会跳过）。两处各判一次必然漂移。
    config = get_collect_config(db)
    task = ApplyTask(
        kind=TASK_KIND_COLLECT,
        status=TASK_STATUS_PENDING,
        total=len(ids),
        config={**config.model_dump(), "backfill_job_ids": ids},
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    runner.start(task.id)
    return task


def fail_orphaned_tasks(db: Session) -> int:
    """应用重启后，把仍停留在"进行中"的任务标记为失败，避免出现"幽灵进度"。"""
    orphans = db.query(ApplyTask).filter(ApplyTask.status.in_(ACTIVE_TASK_STATUSES)).all()
    for task in orphans:
        task.status = TASK_STATUS_FAILED
        task.stop_reason = STOP_REASON_ERROR
        task.message = "应用重启，任务已中断，请重新开始"
        task.finished_at = utcnow()
        task.current_step = "idle"
    if orphans:
        db.commit()
        logger.warning("清理了 %s 个中断的投递/采集任务", len(orphans))
    return len(orphans)
