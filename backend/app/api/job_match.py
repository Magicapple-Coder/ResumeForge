"""岗位匹配度分析接口（prefix ``/api/jobs``）。

薄路由：只做校验、调 service、返回 schema。匹配分析第一次把 JD 与**用户已确认的资料/
简历**对齐，所以它和「岗位需求解读」不同——这里会读取个人资料与简历。

未配置大模型时走**本地降级**并给出中文警告（不阻断流程）；资料为空时应先补资料再分析。
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..models.job import Job
from ..models.profile import UserProfile, utcnow
from ..models.resume import ResumeRecord
from ..schemas.job_match import JobMatchOut, JobMatchResult
from ..services.apply import apply_service
from ..services.job_match import analyze_match, job_payload, local_match_result
from ..services.llm import create_provider
from ..services.llm.base import LLMError
from ..services.profile_service import get_profile_detail, to_profile_out
from ..services.settings_service import get_llm_config

router = APIRouter(prefix="/api/jobs", tags=["job-match"])
logger = logging.getLogger(__name__)


def _profile_is_empty(profile: UserProfile) -> bool:
    return not any(
        [
            profile.name,
            profile.phone,
            profile.email,
            profile.summary,
            profile.job_intent,
            profile.educations,
            profile.experiences,
            profile.projects,
            profile.skills,
        ]
    )


def _source_texts(db: Session, job: Job) -> tuple[UserProfile, str, ResumeRecord | None, str]:
    profile = get_profile_detail(db)
    profile_text = json.dumps(
        to_profile_out(profile).model_dump(mode="json", exclude={"photo"}),
        ensure_ascii=False,
    )
    resume = apply_service.resolve_resume(db, job.id, None)
    resume_text = ""
    if resume is not None:
        resume_text = json.dumps(
            {"title": resume.title, "job_title": resume.job_title, "content": resume.content},
            ensure_ascii=False,
        )
    return profile, profile_text, resume, resume_text


@router.post("/{job_id}/match-analysis", response_model=JobMatchResult)
async def create_match_analysis(
    job_id: int,
    force: bool = Query(default=False, description="为真时忽略已有结论，强制重算"),
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="岗位不存在或已被删除")

    if not force:
        existing = apply_service.latest_match(db, job_id)
        if existing is not None and isinstance(existing.result, dict) and existing.result:
            return JobMatchResult.model_validate(existing.result)

    profile, profile_text, resume, resume_text = _source_texts(db, job)
    if _profile_is_empty(profile) and not resume_text.strip():
        raise HTTPException(
            status_code=400, detail="个人资料为空，请先在「我的资料」中填写后再做匹配分析"
        )

    payload = job_payload(job)
    config = get_llm_config(db)
    configured = bool(config.base_url.strip() and config.model.strip())
    # 释放数据库连接（await 期间不要占着连接池）。
    db.close()

    if not configured:
        result = local_match_result(payload)
        model_name = ""
    else:
        provider = create_provider(config)
        try:
            result = await analyze_match(provider, payload, profile_text, resume_text)
        except LLMError as exc:
            logger.warning("岗位匹配分析失败：%s", exc)
            raise HTTPException(status_code=502, detail=f"生成匹配分析失败：{exc}") from exc
        except Exception as exc:  # noqa: BLE001 - 外部模型异常统一转为可理解的错误
            logger.exception("岗位匹配分析发生内部错误")
            raise HTTPException(status_code=502, detail="生成匹配分析失败，请稍后重试") from exc
        model_name = config.model

    session = SessionLocal()
    try:
        stored_job = session.get(Job, job_id)
        if stored_job is not None:
            apply_service.persist_match(session, stored_job, result, model=model_name)
    finally:
        session.close()
    return result


@router.get("/{job_id}/match-analysis", response_model=JobMatchOut)
def get_match_analysis(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="岗位不存在或已被删除")
    row = apply_service.latest_match(db, job_id)
    if row is None:
        # 尚未分析：返回一个空结果，前端据此显示「未分析」。
        now = utcnow()
        return JobMatchOut(
            id=0,
            job_id=job_id,
            job_title=job.title,
            company=job.company,
            result=JobMatchResult(),
            hard_gate="unknown",
            requires_confirm=False,
            model="",
            created_at=now,
            updated_at=now,
        )
    return JobMatchOut.model_validate(row)


@router.delete("/{job_id}/match-analysis", status_code=204)
def delete_match_analysis(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="岗位不存在或已被删除")
    apply_service.delete_match(db, job_id)
    return None


__all__ = ["router"]
