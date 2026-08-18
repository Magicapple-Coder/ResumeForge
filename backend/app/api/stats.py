"""首页统计：数量概览与最近动态。"""
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.job import JOB_STATUS_OPEN, Job
from ..models.profile import utcnow
from ..models.resume import ResumeRecord
from ..schemas.job import JobOut
from ..schemas.resume import ResumeBrief
from ..schemas.search import Stats

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("", response_model=Stats)
def get_stats(db: Session = Depends(get_db)):
    week_ago = utcnow() - timedelta(days=7)
    latest_jobs = db.query(Job).order_by(Job.created_at.desc()).limit(5).all()
    latest_resumes = db.query(ResumeRecord).order_by(ResumeRecord.created_at.desc()).limit(5).all()
    return Stats(
        job_count=db.query(Job).count(),
        open_job_count=db.query(Job).filter(Job.status == JOB_STATUS_OPEN).count(),
        resume_count=db.query(ResumeRecord).count(),
        week_resume_count=db.query(ResumeRecord).filter(ResumeRecord.created_at >= week_ago).count(),
        latest_jobs=[JobOut.model_validate(row) for row in latest_jobs],
        latest_resumes=[ResumeBrief.model_validate(row) for row in latest_resumes],
    )
