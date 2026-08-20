"""岗位接口：列表、新增、文本解析、AI 解读、编辑与删除。"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.job import JOB_STATUSES, Job
from ..schemas.common import Page
from ..schemas.job import (
    JobBatchDeleteResult,
    JobBatchRequest,
    JobBatchStatusRequest,
    JobBatchStatusResult,
    JobCreate,
    JobOut,
    JobTextParseRequest,
    JobTextParseResult,
    JobUpdate,
)
from ..schemas.job_analysis import JobAnalysisResult
from ..services.jd_parser import parse_jd
from ..services.job_analysis import generate_job_analysis
from ..services.job_text_parser import parse_job_text
from ..services.llm import create_provider
from ..services.llm.base import LLMError
from ..services.settings_service import get_llm_config

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
logger = logging.getLogger(__name__)


def _to_out(job: Job) -> JobOut:
    return JobOut.model_validate(job)


def _get_jobs_or_404(db: Session, job_ids: list[int]) -> list[Job]:
    jobs = db.query(Job).filter(Job.id.in_(job_ids)).all()
    found_ids = {job.id for job in jobs}
    missing_ids = [job_id for job_id in job_ids if job_id not in found_ids]
    if missing_ids:
        missing = "、".join(str(job_id) for job_id in missing_ids)
        raise HTTPException(status_code=404, detail=f"以下岗位不存在或已被删除：{missing}")
    return jobs


def _commit_batch(db: Session) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


@router.get("", response_model=Page[JobOut])
def list_jobs(
    db: Session = Depends(get_db),
    keyword: str = Query(default="", description="按标题/公司/城市/描述/其他信息/备注模糊匹配"),
    job_type: str = Query(default=""),
    status: str = Query(default=""),
    favorite: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    query = db.query(Job)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(
                Job.title.like(like),
                Job.company.like(like),
                Job.location.like(like),
                Job.description.like(like),
                Job.additional_info.like(like),
                Job.note.like(like),
            )
        )
    if job_type:
        query = query.filter(Job.job_type == job_type)
    if status:
        query = query.filter(Job.status == status)
    if favorite is not None:
        query = query.filter(Job.favorite == favorite)
    total = query.count()
    jobs = query.order_by(Job.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return Page(items=[_to_out(job) for job in jobs], total=total)


@router.post("", response_model=JobOut, status_code=201)
def create_job(payload: JobCreate, db: Session = Depends(get_db)):
    job = Job(**payload.model_dump())
    # 入库时解析一次技能标签，列表页/详情页直接读取
    job.keywords = [
        tag.model_dump()
        for tag in parse_jd(
            f"{job.description}\n{job.requirements}\n{job.additional_info}"
        )["skills"]
    ]
    db.add(job)
    db.commit()
    db.refresh(job)
    return _to_out(job)


@router.post("/parse-text", response_model=JobTextParseResult)
def parse_job_text_draft(payload: JobTextParseRequest):
    """把用户粘贴的招聘信息解析为草稿；确认后仍由新增岗位接口入库。"""
    return parse_job_text(payload.text)


@router.post("/batch-status", response_model=JobBatchStatusResult)
def batch_update_job_status(payload: JobBatchStatusRequest, db: Session = Depends(get_db)):
    if payload.status not in JOB_STATUSES:
        allowed = "、".join(JOB_STATUSES)
        raise HTTPException(status_code=400, detail=f"无效的岗位状态，可选值：{allowed}")

    jobs = _get_jobs_or_404(db, payload.job_ids)
    for job in jobs:
        job.status = payload.status
    _commit_batch(db)
    return JobBatchStatusResult(updated=len(jobs))


@router.post("/batch-delete", response_model=JobBatchDeleteResult)
def batch_delete_jobs(payload: JobBatchRequest, db: Session = Depends(get_db)):
    jobs = _get_jobs_or_404(db, payload.job_ids)
    for job in jobs:
        db.delete(job)
    _commit_batch(db)
    return JobBatchDeleteResult(deleted=len(jobs))


@router.post("/{job_id}/analysis", response_model=JobAnalysisResult)
async def analyze_job(job_id: int, db: Session = Depends(get_db)):
    """按需生成岗位需求总结和通用求职建议，不修改岗位或个人资料。"""
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="岗位不存在或已被删除")
    config = get_llm_config(db)
    if not config.base_url or not config.model:
        raise HTTPException(status_code=400, detail="请先在「设置」页配置大模型 API")
    provider = create_provider(config)
    job_out = JobOut.model_validate(job)
    db.close()
    try:
        return await generate_job_analysis(provider, job_out)
    except LLMError as exc:
        logger.warning("岗位需求解读失败：%s", exc)
        raise HTTPException(status_code=502, detail=f"生成岗位解读失败：{exc}") from exc
    except Exception as exc:  # noqa: BLE001 - 外部模型异常统一转为用户可理解的错误
        logger.exception("岗位需求解读发生内部错误")
        raise HTTPException(status_code=502, detail="生成岗位解读失败，请稍后重试") from exc


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="岗位不存在或已被删除")
    return _to_out(job)


@router.put("/{job_id}", response_model=JobOut)
def update_job(job_id: int, payload: JobUpdate, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="岗位不存在或已被删除")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(job, field, value)
    # JD 内容变化时重新解析技能标签
    if {"description", "requirements", "additional_info"}.intersection(data):
        job.keywords = [
            tag.model_dump()
            for tag in parse_jd(
                f"{job.description}\n{job.requirements}\n{job.additional_info}"
            )["skills"]
        ]
    db.commit()
    db.refresh(job)
    return _to_out(job)


@router.delete("/{job_id}", status_code=204)
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="岗位不存在或已被删除")
    db.delete(job)
    db.commit()
