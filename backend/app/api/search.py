"""全局搜索：同时检索岗位、简历记录，以及内推/提醒/面经/台账/资料/技能。

旧的 ``jobs`` / ``resumes`` 字段保持不变；六个新数据域统一放进 ``more``（``SearchHit``），
旧调用方完全无感。扩展域只在 ``scope in ("all", "more")`` 时查询，``scope="jobs"`` 或
``"resumes"`` 时仍只查单一域，语义不变。
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import cast, or_, String
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.claim import ClaimRecord
from ..models.interview_experience import InterviewExperience
from ..models.job import Job
from ..models.material import Material
from ..models.profile import Skill
from ..models.referral import Referral
from ..models.reminder import Reminder
from ..models.resume import ResumeRecord
from ..schemas.job import JobOut
from ..schemas.resume import ResumeBrief
from ..schemas.search import SearchHit, SearchResult
from ..services import trash

router = APIRouter(prefix="/api/search", tags=["search"])


def _search_more(db: Session, like: str, limit: int) -> list[SearchHit]:
    """检索六个扩展数据域，返回按域分组的 ``SearchHit`` 列表。

    每域只取 ``limit`` 条、按创建时间倒序；技能表没有 ``deleted_at``（它是个人资料里的
    硬删子表），因此不套 ``live_only``，其余五类都过滤软删除。
    """
    hits: list[SearchHit] = []

    referral_rows = (
        db.query(Referral)
        .filter(trash.live_only(Referral))
        .filter(
            or_(
                Referral.job_title.like(like),
                Referral.company.like(like),
                Referral.referrer_name.like(like),
                Referral.position.like(like),
                Referral.note.like(like),
            )
        )
        .order_by(Referral.created_at.desc())
        .limit(limit)
        .all()
    )
    hits.extend(
        SearchHit(
            type="referral",
            id=row.id,
            title=row.job_title or row.position or "未命名内推",
            subtitle=row.company or row.referrer_name or "",
            path="/apply",
        )
        for row in referral_rows
    )

    reminder_rows = (
        db.query(Reminder)
        .filter(trash.live_only(Reminder))
        .filter(or_(Reminder.title.like(like), Reminder.note.like(like)))
        .order_by(Reminder.created_at.desc())
        .limit(limit)
        .all()
    )
    hits.extend(
        SearchHit(
            type="reminder",
            id=row.id,
            title=row.title or "未命名提醒",
            subtitle=(row.note or "")[:50],
            path="/tracker",
        )
        for row in reminder_rows
    )

    experience_rows = (
        db.query(InterviewExperience)
        .filter(trash.live_only(InterviewExperience))
        .filter(
            or_(
                InterviewExperience.title.like(like),
                InterviewExperience.company.like(like),
                InterviewExperience.position.like(like),
                InterviewExperience.content.like(like),
            )
        )
        .order_by(InterviewExperience.created_at.desc())
        .limit(limit)
        .all()
    )
    hits.extend(
        SearchHit(
            type="experience",
            id=row.id,
            title=row.title or row.position or "未命名面经",
            subtitle=row.company or "",
            path="/interview",
        )
        for row in experience_rows
    )

    claim_rows = (
        db.query(ClaimRecord)
        .filter(trash.live_only(ClaimRecord))
        .filter(
            or_(
                ClaimRecord.title.like(like),
                ClaimRecord.category.like(like),
                ClaimRecord.subject.like(like),
                ClaimRecord.source_fact.like(like),
                ClaimRecord.candidate_wording.like(like),
            )
        )
        .order_by(ClaimRecord.created_at.desc())
        .limit(limit)
        .all()
    )
    hits.extend(
        SearchHit(
            type="claim",
            id=row.id,
            title=row.title or row.subject or "未命名事实",
            subtitle=row.category or "",
            path="/claims",
        )
        for row in claim_rows
    )

    material_rows = (
        db.query(Material)
        .filter(trash.live_only(Material))
        .filter(
            or_(
                Material.title.like(like),
                Material.category.like(like),
                Material.content.like(like),
                Material.note.like(like),
                Material.url.like(like),
            )
        )
        .order_by(Material.created_at.desc())
        .limit(limit)
        .all()
    )
    hits.extend(
        SearchHit(
            type="material",
            id=row.id,
            title=row.title or "未命名资料",
            subtitle=row.category or "",
            path="/materials",
        )
        for row in material_rows
    )

    skill_rows = (
        db.query(Skill)
        .filter(or_(Skill.name.like(like), Skill.level.like(like)))
        .order_by(Skill.id.desc())
        .limit(limit)
        .all()
    )
    hits.extend(
        SearchHit(
            type="skill",
            id=row.id,
            title=row.name or "未命名技能",
            subtitle=row.level or "",
            path="/skills",
        )
        for row in skill_rows
    )

    return hits


@router.get("", response_model=SearchResult)
def search(
    q: str = Query(min_length=1, description="搜索关键词"),
    scope: str = Query(default="all", pattern="^(all|jobs|resumes|more)$"),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    like = f"%{q}%"
    jobs, resumes, more = [], [], []
    if scope in ("all", "jobs"):
        rows = (
            db.query(Job)
            .filter(trash.live_only(Job))
            .filter(
                or_(
                    Job.title.like(like),
                    Job.company.like(like),
                    Job.location.like(like),
                    Job.description.like(like),
                    Job.additional_info.like(like),
                    Job.note.like(like),
                )
            )
            .order_by(Job.created_at.desc())
            .limit(limit)
            .all()
        )
        jobs = [JobOut.model_validate(row) for row in rows]
    if scope in ("all", "resumes"):
        rows = (
            db.query(ResumeRecord)
            .filter(trash.live_only(ResumeRecord))
            .filter(
                or_(
                    ResumeRecord.title.like(like),
                    ResumeRecord.job_title.like(like),
                    ResumeRecord.company.like(like),
                    cast(ResumeRecord.content, String).like(like),
                )
            )
            .order_by(ResumeRecord.created_at.desc())
            .limit(limit)
            .all()
        )
        resumes = [ResumeBrief.model_validate(row) for row in rows]
    if scope in ("all", "more"):
        more = _search_more(db, like, limit)
    return SearchResult(jobs=jobs, resumes=resumes, more=more)
