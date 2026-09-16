"""备选岗位：还没核对的招聘信息暂存与导入标记。

这里只做暂存；真正的岗位创建仍走 ``job_service``（同一套字段校验与技能标签解析），
避免两条写入路径行为漂移。
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ..models.material import (
    CANDIDATE_JOB_IMPORTED,
    CANDIDATE_JOB_PENDING,
    CANDIDATE_JOB_STATUSES,
    CandidateJob,
)
from ..schemas.material import CandidateJobCreate, CandidateJobUpdate

logger = logging.getLogger(__name__)

MAX_CANDIDATE_TOOL_CHARS = 6_000


def list_candidate_jobs(
    db: Session, *, status: str = "", keyword: str = ""
) -> list[CandidateJob]:
    query = db.query(CandidateJob)
    if status in CANDIDATE_JOB_STATUSES:
        query = query.filter(CandidateJob.status == status)
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        query = query.filter(
            CandidateJob.title.like(like)
            | CandidateJob.company.like(like)
            | CandidateJob.raw_text.like(like)
            | CandidateJob.note.like(like)
        )
    return query.order_by(CandidateJob.created_at.desc(), CandidateJob.id.desc()).all()


def candidate_or_none(db: Session, candidate_id: int) -> CandidateJob | None:
    return db.get(CandidateJob, candidate_id)


def create_candidate_job(db: Session, payload: CandidateJobCreate) -> CandidateJob:
    candidate = CandidateJob(**payload.model_dump(), status=CANDIDATE_JOB_PENDING)
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    logger.info("已新增备选岗位 id=%s", candidate.id)
    return candidate


def update_candidate_job(
    db: Session, candidate: CandidateJob, payload: CandidateJobUpdate
) -> CandidateJob:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(candidate, field, value)
    db.commit()
    db.refresh(candidate)
    return candidate


def mark_candidate_imported(db: Session, candidate: CandidateJob, job_id: int) -> CandidateJob:
    candidate.status = CANDIDATE_JOB_IMPORTED
    candidate.imported_job_id = job_id
    db.commit()
    db.refresh(candidate)
    logger.info("备选岗位已导入 id=%s job_id=%s", candidate.id, job_id)
    return candidate


def delete_candidate_job(db: Session, candidate_id: int) -> bool:
    candidate = db.get(CandidateJob, candidate_id)
    if candidate is None:
        return False
    db.delete(candidate)
    db.commit()
    return True


def candidate_brief(candidate: CandidateJob) -> dict:
    return {
        "id": candidate.id,
        "岗位": candidate.title,
        "公司": candidate.company,
        "状态": "已导入" if candidate.status == CANDIDATE_JOB_IMPORTED else "待处理",
        "导入的岗位 id": candidate.imported_job_id,
        "来源": candidate.source,
        "备注": candidate.note,
        "截图数量": len(candidate.images or []),
        "更新时间": candidate.updated_at.isoformat() if candidate.updated_at else None,
    }


def candidate_detail_text(candidate: CandidateJob, max_chars: int = MAX_CANDIDATE_TOOL_CHARS) -> str:
    parts = [
        f"岗位：{candidate.title or '（未填写）'}",
        f"公司：{candidate.company or '（未填写）'}",
        f"状态：{'已导入' if candidate.status == CANDIDATE_JOB_IMPORTED else '待处理'}",
    ]
    if candidate.note:
        parts.append(f"备注：{candidate.note}")
    if candidate.raw_text:
        parts.append(f"招聘原文：\n{candidate.raw_text}")
    if candidate.images:
        parts.append(f"附有 {len(candidate.images)} 张招聘截图（图片内容未提取）")
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        text = f"{text[:max_chars].rstrip()}…"
    return text


__all__ = [
    "MAX_CANDIDATE_TOOL_CHARS",
    "candidate_brief",
    "candidate_detail_text",
    "candidate_or_none",
    "create_candidate_job",
    "delete_candidate_job",
    "list_candidate_jobs",
    "mark_candidate_imported",
    "update_candidate_job",
]
