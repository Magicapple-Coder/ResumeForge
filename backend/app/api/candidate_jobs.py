"""备选岗位接口：暂存招聘信息、编辑与导入标记。"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.material import CANDIDATE_JOB_STATUSES
from ..schemas.material import (
    CandidateJobCreate,
    CandidateJobImportRequest,
    CandidateJobOut,
    CandidateJobUpdate,
)
from ..services.candidate_jobs import (
    candidate_or_none,
    create_candidate_job,
    delete_candidate_job,
    list_candidate_jobs,
    mark_candidate_imported,
    update_candidate_job,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/candidate-jobs", tags=["candidate-jobs"])


@router.get("", response_model=list[CandidateJobOut])
def read_candidate_jobs(
    status: str = Query(default=""),
    keyword: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """列出备选岗位；``status`` 可选 pending / imported。"""
    if status and status not in CANDIDATE_JOB_STATUSES:
        raise HTTPException(status_code=422, detail="无效的备选岗位状态")
    return list_candidate_jobs(db, status=status, keyword=keyword)


@router.post("", response_model=CandidateJobOut, status_code=201)
def create_candidate_job_entry(payload: CandidateJobCreate, db: Session = Depends(get_db)):
    return create_candidate_job(db, payload)


@router.get("/{candidate_id}", response_model=CandidateJobOut)
def read_candidate_job(candidate_id: int, db: Session = Depends(get_db)):
    candidate = candidate_or_none(db, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="备选岗位不存在或已被删除")
    return candidate


@router.put("/{candidate_id}", response_model=CandidateJobOut)
def save_candidate_job(
    candidate_id: int, payload: CandidateJobUpdate, db: Session = Depends(get_db)
):
    candidate = candidate_or_none(db, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="备选岗位不存在或已被删除")
    return update_candidate_job(db, candidate, payload)


@router.post("/{candidate_id}/imported", response_model=CandidateJobOut)
def mark_imported(
    candidate_id: int, payload: CandidateJobImportRequest, db: Session = Depends(get_db)
):
    """标记为已导入正式岗位（岗位由用户在前端确认保存后传入 id）。"""
    candidate = candidate_or_none(db, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="备选岗位不存在或已被删除")
    return mark_candidate_imported(db, candidate, payload.job_id)


@router.delete("/{candidate_id}", status_code=204)
def remove_candidate_job(candidate_id: int, db: Session = Depends(get_db)):
    if not delete_candidate_job(db, candidate_id):
        raise HTTPException(status_code=404, detail="备选岗位不存在或已被删除")
