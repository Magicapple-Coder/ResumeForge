"""R-15 面经知识库的持久化与检索。

面经是"真实被问过什么、怎么答"的沉淀，与模拟面试（对话式练习）互补。来源三类
（自己/同行/公开），只做分类不做断言，来源可信度由用户自己判断。

- **岗位被删不连坐**：``job_id`` 外键 ``SET NULL``；``company``/``position`` 是快照，
  删除岗位后面经仍可读、仍可按公司名检索。
- **列表查询一律用 ``trash.live_only``**，回收站里的面经不出现。
- 创建时若关联岗位且未填公司/岗位名，则从岗位快照回填，减少重复录入。
"""
from __future__ import annotations

import logging

from sqlalchemy import or_
from sqlalchemy.orm import Session

from . import trash
from ..models.interview_experience import InterviewExperience
from ..models.job import Job
from ..schemas.interview_experience import InterviewExperienceCreate, InterviewExperienceUpdate

logger = logging.getLogger(__name__)

MAX_EXPERIENCE_LIST = 500


def list_experiences(
    db: Session,
    *,
    keyword: str = "",
    company: str = "",
    source: str = "",
    limit: int = 100,
) -> list[InterviewExperience]:
    """按关键词/公司/来源过滤；只取未软删除的行，最近更新的在前。"""
    query = db.query(InterviewExperience).filter(trash.live_only(InterviewExperience))
    if company.strip():
        query = query.filter(InterviewExperience.company.like(f"%{company.strip()}%"))
    if source.strip():
        query = query.filter(InterviewExperience.source == source.strip())
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                InterviewExperience.title.like(like),
                InterviewExperience.position.like(like),
                InterviewExperience.content.like(like),
            )
        )
    return (
        query.order_by(InterviewExperience.updated_at.desc(), InterviewExperience.id.desc())
        .limit(max(1, min(limit, MAX_EXPERIENCE_LIST)))
        .all()
    )


def experience_or_none(db: Session, experience_id: int) -> InterviewExperience | None:
    """取一条面经；已在回收站里的当作不存在。"""
    return trash.get_live(db, InterviewExperience, experience_id)


def _apply_payload(
    db: Session, payload: InterviewExperienceCreate
) -> dict:
    """归一化写入值：绑定岗位时回填快照，岗位不存在则置空关联（外键 SET NULL）。"""
    values = payload.model_dump()
    job = db.get(Job, payload.job_id) if payload.job_id else None
    if job is None:
        values["job_id"] = None
    else:
        values["company"] = payload.company.strip() or job.company
        values["position"] = payload.position.strip() or job.title
    return values


def create_experience(
    db: Session, payload: InterviewExperienceCreate
) -> InterviewExperience:
    experience = InterviewExperience(**_apply_payload(db, payload))
    db.add(experience)
    db.commit()
    db.refresh(experience)
    logger.info("已新增面经 id=%s company=%s", experience.id, experience.company)
    return experience


def update_experience(
    db: Session, experience: InterviewExperience, payload: InterviewExperienceUpdate
) -> InterviewExperience:
    for field, value in _apply_payload(db, payload).items():
        setattr(experience, field, value)
    db.commit()
    db.refresh(experience)
    return experience


def delete_experience(db: Session, experience_id: int) -> bool:
    """移入回收站（软删除）；彻底删除在「回收站」里单独提供。"""
    experience = db.get(InterviewExperience, experience_id)
    if experience is None or trash.is_deleted(experience):
        return False
    trash.soft_delete(db, "interview_experience", experience)
    db.commit()
    return True


__all__ = [
    "MAX_EXPERIENCE_LIST",
    "create_experience",
    "delete_experience",
    "experience_or_none",
    "list_experiences",
    "update_experience",
]
