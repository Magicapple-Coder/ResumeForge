"""投递回写与记录（按批次分组）。"""
from __future__ import annotations

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ...models.apply import (
    FAILURE_CATEGORY_LABELS,
    QUEUE_STATUS_DONE,
    TASK_KIND_APPLY,
    ApplyQueueItem,
    ApplyTask,
    ApplyTaskItem,
)
from ...models.job import JOB_STATUS_APPLIED, JOB_STATUS_OPEN, Job
from ...models.profile import utcnow
from ...schemas.apply import ApplyRecordBatchOut, ApplyRecordOut
def write_back_job_status(db: Session, job_id: int | None) -> None:
    """投递成功 → 岗位状态置为「已投递」；只在岗位仍是「开放中」时回写，不覆盖用户手改。"""
    if job_id is None:
        return
    job = db.get(Job, job_id)
    if job is not None and job.status in (JOB_STATUS_OPEN, ""):
        job.status = JOB_STATUS_APPLIED
        job.updated_at = utcnow()


def mark_queue_done(db: Session, job_id: int | None) -> None:
    """投递成功后把队列条目标为已完成。"""
    if job_id is None:
        return
    item = db.query(ApplyQueueItem).filter(ApplyQueueItem.job_id == job_id).one_or_none()
    if item is not None:
        item.status = QUEUE_STATUS_DONE
        item.updated_at = utcnow()


def daily_success_count(db: Session) -> int:
    """今天（UTC 自然日）已成功的投递数——每日上限**只计成功投递**。"""
    start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        db.query(func.count(ApplyTaskItem.id))
        .filter(ApplyTaskItem.status == "success", ApplyTaskItem.finished_at >= start)
        .scalar()
        or 0
    )


def _record_out(item: ApplyTaskItem) -> ApplyRecordOut:
    return ApplyRecordOut(
        id=item.id,
        task_id=item.task_id,
        job_id=item.job_id,
        job_title=item.job_title,
        company=item.company,
        resume_title=item.resume_title,
        greeting=item.greeting,
        status=item.status,
        failure_category=item.failure_category,
        failure_label=FAILURE_CATEGORY_LABELS.get(item.failure_category, ""),
        failure_detail=item.failure_detail,
        attempt=item.attempt,
        created_at=item.created_at,
        finished_at=item.finished_at,
    )


def list_records(
    db: Session,
    *,
    keyword: str = "",
    result: str = "",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[ApplyRecordOut], int]:
    """分页列出投递记录（只含投递批次，按关键词/结果筛选），返回 (记录, 总数)。"""
    query = (
        db.query(ApplyTaskItem)
        .join(ApplyTask, ApplyTaskItem.task_id == ApplyTask.id)
        .filter(ApplyTask.kind == TASK_KIND_APPLY)
    )
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(ApplyTaskItem.job_title.like(like), ApplyTaskItem.company.like(like))
        )
    if result:
        query = query.filter(ApplyTaskItem.status == result)
    total = query.count()
    rows = (
        query.order_by(ApplyTaskItem.created_at.desc(), ApplyTaskItem.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return [_record_out(row) for row in rows], total


def list_record_batches(
    db: Session,
    *,
    keyword: str = "",
    result: str = "",
    page: int = 1,
    page_size: int = 5,
) -> tuple[list[ApplyRecordBatchOut], int]:
    """投递记录按**批次**分组：一页返回若干个批次，每个批次带自己的全部（匹配的）记录。

    为什么按批次而不是给扁平记录加 group-by：一次「开始投递」建一个批次（``ApplyTask``），
    用户一次性投 N 个岗位时这 N 条记录天然同属一个批次——分组键已经存在，界面要做的只是
    "折叠/展开"。筛选（关键词 / 结果）作用在**记录**上：只有命中的记录出现在组内，没有
    命中记录的批次整体不出现；分页按**批次**数（一页几个组，而不是一页几条）。
    """
    item_query = (
        db.query(ApplyTaskItem)
        .join(ApplyTask, ApplyTaskItem.task_id == ApplyTask.id)
        .filter(ApplyTask.kind == TASK_KIND_APPLY)
    )
    if keyword:
        like = f"%{keyword}%"
        item_query = item_query.filter(
            or_(ApplyTaskItem.job_title.like(like), ApplyTaskItem.company.like(like))
        )
    if result:
        item_query = item_query.filter(ApplyTaskItem.status == result)

    matched_items = item_query.subquery()
    # 只统计"至少有一条命中记录"的批次，分页与总数都以它为准。
    batch_ids = (
        db.query(matched_items.c.task_id).distinct().subquery()
    )
    total = db.query(func.count()).select_from(batch_ids).scalar() or 0
    batch_rows = (
        db.query(ApplyTask)
        .join(batch_ids, ApplyTask.id == batch_ids.c.task_id)
        .order_by(ApplyTask.created_at.desc(), ApplyTask.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    if not batch_rows:
        return [], total
    batch_id_list = [task.id for task in batch_rows]
    item_rows = (
        db.query(ApplyTaskItem)
        .join(
            matched_items,
            (ApplyTaskItem.id == matched_items.c.id)
            & (ApplyTaskItem.task_id == matched_items.c.task_id),
        )
        .filter(ApplyTaskItem.task_id.in_(batch_id_list))
        .order_by(ApplyTaskItem.sort_order, ApplyTaskItem.id)
        .all()
    )
    items_by_task: dict[int, list[ApplyRecordOut]] = {task_id: [] for task_id in batch_id_list}
    for item in item_rows:
        items_by_task.setdefault(item.task_id, []).append(_record_out(item))
    batches = [
        ApplyRecordBatchOut(
            id=task.id,
            status=task.status,
            total=task.total,
            processed=task.processed,
            succeeded=task.succeeded,
            failed=task.failed,
            skipped=task.skipped,
            message=task.message or "",
            created_at=task.created_at,
            finished_at=task.finished_at,
            items=items_by_task.get(task.id, []),
        )
        for task in batch_rows
    ]
    return batches, total

