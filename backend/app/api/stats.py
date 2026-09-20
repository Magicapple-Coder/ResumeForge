"""首页统计：数量概览、最近动态与"接下来做什么"。"""
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.apply import (
    ITEM_STATUS_SUCCESS,
    QUEUE_STATUS_PENDING,
    ApplyQueueItem,
    ApplyTaskItem,
)
from ..models.claim import VERIFICATION_PENDING, ClaimRecord
from ..models.job import JOB_STATUS_OPEN, Job
from ..models.profile import utcnow
from ..models.resume import ResumeRecord
from ..models.tracker import ACTIVE_STATUSES, STALLED_DAYS, ApplicationTrack
from ..schemas.job import JobOut
from ..schemas.resume import ResumeBrief
from ..schemas.search import PendingClaimBrief, Stats
from ..services import trash

router = APIRouter(prefix="/api/stats", tags=["stats"])

# 首页各列表的条数。够看清"最近发生了什么"即可，看全在各自的页面里。
_LATEST_LIMIT = 5


@router.get("", response_model=Stats)
def get_stats(db: Session = Depends(get_db)):
    week_ago = utcnow() - timedelta(days=7)
    latest_jobs = (
        db.query(Job)
        .filter(trash.live_only(Job))
        .order_by(Job.created_at.desc())
        .limit(_LATEST_LIMIT)
        .all()
    )
    latest_resumes = (
        db.query(ResumeRecord)
        .filter(trash.live_only(ResumeRecord))
        .order_by(ResumeRecord.created_at.desc())
        .limit(_LATEST_LIMIT)
        .all()
    )

    # 待确认的台账条目：首页点名它们，因为"这条还没核实"是用户自己能推进的事。
    pending_claims = (
        db.query(ClaimRecord)
        .filter(trash.live_only(ClaimRecord))
        .filter(ClaimRecord.verification_status == VERIFICATION_PENDING)
        .order_by(ClaimRecord.updated_at.desc())
        .limit(_LATEST_LIMIT)
        .all()
    )
    pending_claim_count = (
        db.query(ClaimRecord)
        .filter(trash.live_only(ClaimRecord))
        .filter(ClaimRecord.verification_status == VERIFICATION_PENDING)
        .count()
    )

    # 进行中的投递：ACTIVE_STATUSES 是"还没走到终态"的那几个；其中久未更新的单独计数，
    # 因为"卡住了"比"在推进"更需要用户去看一眼。
    # 阈值与判定口径来自 ``models/tracker``，求职看板的 ``stalled_count`` 读的是同一份
    # （两处结论由 ``test_stalled_count_matches_stats_endpoint`` 钉住一致）。这里仍走 SQL
    # 过滤而不是取回全表再用 ``is_stalled`` 筛——首页是热路径，而 ``updated_at < cutoff``
    # 与 ``is_stalled`` 的 ``(now - updated_at) > 7d`` 严格等价。
    stalled_cutoff = utcnow() - timedelta(days=STALLED_DAYS)
    stalled_application_count = (
        db.query(ApplicationTrack)
        .filter(
            trash.live_only(ApplicationTrack),
            ApplicationTrack.status.in_(tuple(ACTIVE_STATUSES)),
            ApplicationTrack.updated_at < stalled_cutoff,
        )
        .count()
    )

    # 最近投递结果：只取成功条目，失败在看板上有专门的地方看。
    # 按 finished_at 排序——"最近投出去的那个"是投递**结束**的时刻，不是入队的时刻。
    latest_application_rows = (
        db.query(ApplyTaskItem)
        .filter(ApplyTaskItem.status == ITEM_STATUS_SUCCESS)
        .order_by(ApplyTaskItem.finished_at.desc())
        .limit(_LATEST_LIMIT)
        .all()
    )

    return Stats(
        job_count=db.query(Job).filter(trash.live_only(Job)).count(),
        open_job_count=db.query(Job)
        .filter(trash.live_only(Job), Job.status == JOB_STATUS_OPEN)
        .count(),
        resume_count=db.query(ResumeRecord).filter(trash.live_only(ResumeRecord)).count(),
        week_resume_count=db.query(ResumeRecord)
        .filter(trash.live_only(ResumeRecord), ResumeRecord.created_at >= week_ago)
        .count(),
        latest_jobs=[JobOut.model_validate(row) for row in latest_jobs],
        latest_resumes=[ResumeBrief.model_validate(row) for row in latest_resumes],
        favorite_job_count=db.query(Job)
        .filter(trash.live_only(Job), Job.favorite.is_(True))
        .count(),
        pending_claim_count=pending_claim_count,
        pending_claims=[
            PendingClaimBrief(id=row.id, title=row.title or row.subject or "未命名主张")
            for row in pending_claims
        ],
        stalled_application_count=stalled_application_count,
        apply_queue_count=db.query(ApplyQueueItem)
        .filter(ApplyQueueItem.status == QUEUE_STATUS_PENDING)
        .count(),
        latest_applications=[
            {
                "id": row.id,
                "job_title": row.job_title,
                "company": row.company,
                # 状态与快照字段二选一：条目可能来自已被删除的岗位。
                "status": row.status,
                "updated_at": (
                    (row.finished_at or row.created_at).isoformat()
                    if (row.finished_at or row.created_at)
                    else ""
                ),
            }
            for row in latest_application_rows
        ],
    )
