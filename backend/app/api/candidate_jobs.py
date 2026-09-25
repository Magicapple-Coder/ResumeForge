"""备选岗位接口：暂存招聘信息、编辑与导入标记。"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.material import CANDIDATE_JOB_STATUSES
from ..schemas.material import (
    CandidateJobBulkImportOut,
    CandidateJobBulkImportRequest,
    CandidateJobCreate,
    CandidateJobDetailOut,
    CandidateJobImportRequest,
    CandidateJobOut,
    CandidateJobUpdate,
)
from ..services.candidate_jobs import (
    MAX_CANDIDATE_LIST,
    candidate_or_none,
    create_candidate_job,
    delete_candidate_job,
    import_candidates,
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
    collect_task_id: int | None = Query(default=None, ge=1),
    collect_task_ids: str = Query(default=""),
    limit: int = Query(default=MAX_CANDIDATE_LIST, ge=1, le=MAX_CANDIDATE_LIST),
    db: Session = Depends(get_db),
):
    """列出备选岗位；``status`` 可选 pending / imported。

    ``collect_task_id`` 用于「本次采集结果」——按批次看这次采到了什么。
    """
    if status and status not in CANDIDATE_JOB_STATUSES:
        raise HTTPException(status_code=422, detail="无效的备选岗位状态")
    parsed_ids: list[int] = []
    if collect_task_ids.strip():
        try:
            parsed_ids = [int(value) for value in collect_task_ids.split(",") if value.strip()]
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="采集批次编号无效") from exc
        if any(value < 1 for value in parsed_ids):
            raise HTTPException(status_code=422, detail="采集批次编号无效")
    return list_candidate_jobs(
        db,
        status=status,
        keyword=keyword,
        collect_task_id=collect_task_id,
        collect_task_ids=list(dict.fromkeys(parsed_ids)),
        limit=limit,
    )


@router.post("", response_model=CandidateJobOut, status_code=201)
def create_candidate_job_entry(payload: CandidateJobCreate, db: Session = Depends(get_db)):
    return create_candidate_job(db, payload)


@router.post("/import", response_model=CandidateJobBulkImportOut)
def import_candidate_jobs(payload: CandidateJobBulkImportRequest, db: Session = Depends(get_db)):
    """把选中的候选岗位批量导入岗位广场（服务端建岗位并回填关联）。

    **声明在 ``/{candidate_id}`` 之前**：FastAPI 按声明顺序匹配，把具名路径放在参数路径
    后面，``/import`` 就会先被当成 ``candidate_id`` 去解析（今天靠"方法不同"侥幸不冲突，
    但以后给 ``/{candidate_id}`` 加一个 POST 就会立刻踩中），返回的 422 看起来像前端传错、
    实际是路由顺序问题。
    """
    return import_candidates(db, payload.candidate_ids)


@router.get("/{candidate_id}", response_model=CandidateJobDetailOut)
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
