"""投递队列：准入、去重、排序，以及简历 / 招呼语解析。"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ...models.apply import (
    ADMISSION_BLOCK,
    HARD_GATES,
    QUEUE_STATUS_PENDING,
    ApplyQueueItem,
)
from ...models.job import Job
from ...models.profile import utcnow
from ...models.resume import ResumeRecord
from ...schemas.apply import ApplyConfigIn, ApplyQueueItemOut
from .. import trash
from ..profile.profile_service import get_profile_detail
from ..sites.base import SiteAdapter
from ..sites.registry import get_registry
from ._base import ApplyConflict, ApplyNotFound, ApplyServiceError, _clip_greeting
from ._config import get_apply_config
from ._match import _admission_of_match, _blocking_gaps, _match_requires_confirm, latest_match
def _resume_title(db: Session, resume_id: int | None) -> str:
    if resume_id is None:
        return ""
    resume = db.get(ResumeRecord, resume_id)
    return resume.title if resume is not None else ""


def job_apply_site(job: Job | None) -> SiteAdapter | None:
    """这个岗位能不能自动投递：能则返回对应站点适配器，不能则返回 ``None``。

    **唯一判据**：岗位的来源 / 投递链接必须能落到某个已注册站点上。纯手动录入、来源与链接
    都指不到站点的岗位，在投递时定位不到任何站点适配器，强行投只会得到一条「未知失败」的
    记录——所以"入队校验、开始投递前的拦截、列表上的能否投递标记"三处都走这一个函数，
    不各自判一遍。岗位已被删除（``None``）同样视为不可投递。
    """
    if job is None:
        return None
    return get_registry().resolve_for_job(job)


def unsupported_site_message(job: Job) -> str:
    """不可投递时的中文说明：入队被拒、开始投递被拦、单条失败诊断三处共用同一句。"""
    return (
        f"「{job.title or '该岗位'}」的来源不是投递台支持的招聘网站"
        f"（当前支持：{get_registry().supported_names()}），无法自动投递。"
        "请到对应的招聘网站里手动投递。"
    )


def _queue_out(db: Session, item: ApplyQueueItem, job: Job | None) -> ApplyQueueItemOut:
    match = latest_match(db, item.job_id)
    admission = _admission_of_match(match) if match is not None else None
    hard_gate = match.hard_gate if match is not None and match.hard_gate in HARD_GATES else None
    return ApplyQueueItemOut(
        id=item.id,
        job_id=item.job_id,
        job_title=item.job_title,
        company=item.company,
        resume_id=item.resume_id,
        resume_title=_resume_title(db, item.resume_id),
        greeting=item.greeting,
        sort_order=item.sort_order,
        status=item.status,
        admission=admission,
        hard_gate=hard_gate,
        requires_confirm=_match_requires_confirm(match) if match is not None else False,
        # 「能不能自动投」由来源决定，与匹配结论无关；界面上据此禁用勾选并说明原因。
        apply_supported=job_apply_site(job) is not None,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def list_queue(db: Session) -> list[ApplyQueueItemOut]:
    """按排序列出投递队列，每行带准入结论与能否投递标记。"""
    items = (
        db.query(ApplyQueueItem)
        .order_by(ApplyQueueItem.sort_order, ApplyQueueItem.id)
        .all()
    )
    # 岗位一次性取回，避免每行一次查询（队列条数不多，但这属于该顺手做对的事）。
    jobs = _jobs_by_id(db, [item.job_id for item in items])
    return [_queue_out(db, item, jobs.get(item.job_id)) for item in items]


def _jobs_by_id(db: Session, job_ids: Sequence[int | None]) -> dict[int, Job]:
    """按 id 批量取岗位；缺失（已删除）的不在返回里。"""
    ids = sorted({job_id for job_id in job_ids if job_id})
    if not ids:
        return {}
    return {job.id: job for job in db.query(Job).filter(Job.id.in_(ids)).all()}


def add_to_queue(db: Session, request: Any) -> list[ApplyQueueItemOut]:
    """加入队列；命中"来源不支持 / 已在队列 / 真实缺口 / 未分析"时抛 409 并回传原因。

    整批要么全部成功、要么全部回滚：任一岗位不满足准入就中断，避免"加了一半"。
    """
    config = get_apply_config(db)
    next_order = (
        db.query(func.coalesce(func.max(ApplyQueueItem.sort_order), 0)).scalar() or 0
    )
    created: list[ApplyQueueItem] = []
    created_jobs: list[Job] = []
    try:
        for entry in request.items:
            job = db.get(Job, entry.job_id)
            if job is None:
                raise ApplyNotFound(f"岗位不存在或已被删除：{entry.job_id}")
            # 来源闸门**放最前**：这是"这个岗位本来就走不到投递"的硬前提，不是用户确认一下
            # 就能放行的事（与下面的未分析 / 真实缺口不同，那两类可以由用户显式确认）。
            if job_apply_site(job) is None:
                raise ApplyConflict(
                    {
                        "message": unsupported_site_message(job),
                        "job_id": job.id,
                        "site_unsupported": True,
                    }
                )
            existing = (
                db.query(ApplyQueueItem)
                .filter(ApplyQueueItem.job_id == job.id)
                .one_or_none()
            )
            if existing is not None:
                raise ApplyConflict(
                    {"message": f"「{job.title or '该岗位'}」已在投递队列中", "job_id": job.id}
                )
            match = latest_match(db, job.id)
            if match is None:
                if not entry.confirm_unanalyzed:
                    raise ApplyConflict(
                        {
                            "message": f"「{job.title or '该岗位'}」尚未做过匹配分析，确认继续加入？",
                            "job_id": job.id,
                            "unanalyzed": True,
                        }
                    )
            else:
                admission = _admission_of_match(match)
                if admission == ADMISSION_BLOCK and not (
                    entry.confirm_real_gap or config.confirm_real_gap
                ):
                    raise ApplyConflict(
                        {
                            "message": f"「{job.title or '该岗位'}」存在真实缺口，需确认后再加入",
                            "job_id": job.id,
                            "gaps": _blocking_gaps(match.result),
                        }
                    )
                # 「需确认」（needs_confirm）与「读不出可用结论」（admission is None，即空结果 /
                # 未知取值 / hard_gate=unknown 且无标记）**同级处理**：都不阻断入队，但该条目被视为
                # 未获授权自动投递——`_match_requires_confirm` 会据此算出 requires_confirm=True，
                # 投递前仍要用户逐条确认。未知/空结论绝不默认放行。
            next_order += 1
            queue_item = ApplyQueueItem(
                job_id=job.id,
                job_title=job.title,
                company=job.company,
                resume_id=entry.resume_id,
                greeting=_clip_greeting(entry.greeting),
                sort_order=next_order,
                status=QUEUE_STATUS_PENDING,
            )
            db.add(queue_item)
            created.append(queue_item)
            created_jobs.append(job)
        db.commit()
    except ApplyServiceError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    return [_queue_out(db, item, job) for item, job in zip(created, created_jobs)]


def update_queue_item(db: Session, item_id: int, payload: Any) -> ApplyQueueItemOut:
    """更新队列条目的招呼语/简历，并回填准入结论与能否投递标记。"""
    item = db.get(ApplyQueueItem, item_id)
    if item is None:
        raise ApplyNotFound("投递队列条目不存在或已被移除")
    if payload.greeting is not None:
        item.greeting = _clip_greeting(payload.greeting)
    if payload.resume_id is not None:
        resume = db.get(ResumeRecord, payload.resume_id)
        if resume is None:
            raise ApplyNotFound("指定的简历不存在")
        item.resume_id = resume.id
    item.updated_at = utcnow()
    db.commit()
    db.refresh(item)
    return _queue_out(db, item, db.get(Job, item.job_id) if item.job_id else None)


def remove_queue_item(db: Session, item_id: int) -> None:
    item = db.get(ApplyQueueItem, item_id)
    if item is None:
        raise ApplyNotFound("投递队列条目不存在或已被移除")
    db.delete(item)
    db.commit()


def reorder_queue(db: Session, order: list[int]) -> list[ApplyQueueItemOut]:
    """按给定 id 顺序重排队列。"""
    for index, item_id in enumerate(order):
        item = db.get(ApplyQueueItem, item_id)
        if item is None:
            continue
        item.sort_order = index
        item.updated_at = utcnow()
    db.commit()
    return list_queue(db)


# ===== 简历与招呼语解析 =====


def resolve_resume(db: Session, job_id: int | None, resume_id: int | None) -> ResumeRecord | None:
    """确定本岗位用哪份简历：显式指定优先，否则取该岗位最近一份岗位版简历。"""
    if resume_id is not None:
        return db.get(ResumeRecord, resume_id)
    if job_id is None:
        return None
    return (
        db.query(ResumeRecord)
        .filter(trash.live_only(ResumeRecord), ResumeRecord.job_id == job_id)
        .order_by(ResumeRecord.created_at.desc(), ResumeRecord.id.desc())
        .first()
    )


def resolve_greeting(item: ApplyQueueItem | None, config: ApplyConfigIn) -> str:
    """本岗位招呼语：条目值优先，为空则退回默认招呼语。"""
    if item is not None and item.greeting.strip():
        return item.greeting.strip()
    return config.default_greeting.strip()


def build_apply_data(db: Session, resume: ResumeRecord | None) -> dict[str, Any]:
    """构造供通用表单引擎映射的字段数据（只取投递必需的展示字段，不含完整资料）。"""
    profile = get_profile_detail(db)
    data: dict[str, Any] = {
        "name": profile.name,
        "phone": profile.phone,
        "email": profile.email,
        "city": profile.target_city or profile.city,
        "job_intent": profile.job_intent,
        "summary": profile.summary,
    }
    if resume is not None and resume.title:
        data["job_intent"] = data.get("job_intent") or resume.job_title
    return {key: value for key, value in data.items() if value}

