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
    JobMultiTextParseResult,
    JobOut,
    JobTextParseRequest,
    JobTextParseResult,
    JobUpdate,
)
from ..schemas.job_analysis import JobAnalysisResult
from ..services.job_analysis import generate_job_analysis
from ..services.job_service import create_job_record, update_job_record
from ..services.job_multi_parser import extract_multiple_jobs, local_multi_drafts
from ..services.job_text_parser import parse_job_text
from ..services.llm import create_provider
from ..services.llm.base import LLMError
from ..services.settings_service import get_llm_config
from ..services.attachments import (
    assert_attachment_budget,
    image_data_urls,
    normalize_extraction_images,
    total_attachment_bytes,
)
from ..services.document_text import extract_documents_text
from ..services.text_extraction import (
    ai_failed_warning,
    extract_job_text,
    finalize_recognition_result,
    llm_is_configured,
    mark_local_fallback,
    no_model_warning,
)

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
    return _to_out(create_job_record(db, payload))


@router.post("/parse-text", response_model=JobTextParseResult)
async def parse_job_text_draft(payload: JobTextParseRequest, db: Session = Depends(get_db)):
    """把用户粘贴的招聘信息（或截图、文档）解析为草稿；确认后仍由新增岗位接口入库。"""
    try:
        images = normalize_extraction_images(payload.images)
        documents = extract_documents_text(payload.documents)
        assert_attachment_budget(
            count=len(payload.images) + len(payload.documents),
            total_bytes=total_attachment_bytes(images) + documents.size_bytes,
        )
    except ValueError as exc:
        # 在路由层抛：只有 HTTPException 的 detail 会被前端原样展示。
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    image_urls = image_data_urls(images)
    has_images = bool(image_urls)
    has_documents = bool(payload.documents)

    # 文档文字与粘贴文本合并成同一份 source_text：本地规则与模型看到的材料一致，
    # 字段锚定也仍然对着原文，比图片那条"让模型自己抄录再核对"的路子强。
    source_text = "\n\n".join(part for part in (payload.text, documents.text) if part.strip())
    local_draft = parse_job_text(source_text)
    config = get_llm_config(db)
    if not llm_is_configured(config):
        return finalize_recognition_result(
            mark_local_fallback(local_draft, no_model_warning(has_images, has_documents)),
            has_images=has_images,
            document_warnings=documents.warnings,
        )
    provider = create_provider(config)
    db.close()
    try:
        result = await extract_job_text(provider, source_text, local_draft, image_urls)
    except LLMError as exc:
        logger.warning("岗位文本 AI 识别失败，已回退本地解析：%s", exc)
        result = mark_local_fallback(
            local_draft, ai_failed_warning(has_images, str(exc), has_documents)
        )
    except Exception:  # noqa: BLE001 - 外部模型异常不能阻断草稿解析
        logger.exception("岗位文本 AI 识别发生内部错误，已回退本地解析")
        result = mark_local_fallback(local_draft, ai_failed_warning(has_images, has_documents=has_documents))
    return finalize_recognition_result(
        result, has_images=has_images, document_warnings=documents.warnings
    )


@router.post("/parse-multiple", response_model=JobMultiTextParseResult)
async def parse_job_text_multiple(payload: JobTextParseRequest, db: Session = Depends(get_db)):
    """一次粘贴多份招聘信息：拆成多份草稿，用户逐条或全部保存。

    与单份 ``/parse-text`` 共用输入校验与兜底策略：没有可用模型、或模型切不出来时，
    退回本地按显式分隔切分，绝不返回一份"吞掉了其它几份"的草稿。
    """
    try:
        images = normalize_extraction_images(payload.images)
        documents = extract_documents_text(payload.documents)
        assert_attachment_budget(
            count=len(payload.images) + len(payload.documents),
            total_bytes=total_attachment_bytes(images) + documents.size_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    image_urls = image_data_urls(images)
    has_images = bool(image_urls)
    has_documents = bool(payload.documents)
    source_text = "\n\n".join(part for part in (payload.text, documents.text) if part.strip())
    if not source_text.strip() and not image_urls:
        raise HTTPException(status_code=422, detail="请先粘贴招聘信息或上传截图、文档")

    def _local_items(reason: str) -> list[JobTextParseResult]:
        drafts = local_multi_drafts(source_text)
        return [mark_local_fallback(draft, reason) for draft in drafts]

    config = get_llm_config(db)
    if not llm_is_configured(config):
        items = _local_items(no_model_warning(has_images, has_documents))
        return JobMultiTextParseResult(
            items=[
                finalize_recognition_result(
                    item, has_images=has_images, document_warnings=documents.warnings
                )
                for item in items
            ],
            parse_engine="local",
        )

    provider = create_provider(config)
    db.close()
    try:
        results = await extract_multiple_jobs(provider, source_text, image_urls)
        engine = "ai"
    except LLMError as exc:
        logger.warning("多份岗位 AI 识别失败，已回退本地切分：%s", exc)
        results = _local_items(ai_failed_warning(has_images, str(exc), has_documents))
        engine = "local"
    except Exception:  # noqa: BLE001 - 外部模型异常不能阻断草稿解析
        logger.exception("多份岗位 AI 识别发生内部错误，已回退本地切分")
        results = _local_items(ai_failed_warning(has_images, "", has_documents))
        engine = "local"

    items = [
        finalize_recognition_result(
            item, has_images=has_images, document_warnings=documents.warnings
        )
        for item in results
    ]
    return JobMultiTextParseResult(items=items, parse_engine=engine)


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
    return _to_out(update_job_record(db, job, payload))


@router.delete("/{job_id}", status_code=204)
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="岗位不存在或已被删除")
    db.delete(job)
    db.commit()
