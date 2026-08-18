"""全局搜索：同时检索岗位与简历记录。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import cast, or_, String
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.job import Job
from ..models.resume import ResumeRecord
from ..schemas.job import JobOut
from ..schemas.resume import ResumeBrief
from ..schemas.search import SearchResult

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=SearchResult)
def search(
    q: str = Query(min_length=1, description="搜索关键词"),
    scope: str = Query(default="all", pattern="^(all|jobs|resumes)$"),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    like = f"%{q}%"
    jobs, resumes = [], []
    if scope in ("all", "jobs"):
        rows = (
            db.query(Job)
            .filter(
                or_(
                    Job.title.like(like),
                    Job.company.like(like),
                    Job.location.like(like),
                    Job.description.like(like),
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
    return SearchResult(jobs=jobs, resumes=resumes)
