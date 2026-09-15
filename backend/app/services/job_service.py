"""岗位的持久化操作，供 HTTP 路由与助手工具共用。

抽出来是为了让助手工具复用同一套写逻辑（尤其是技能标签的重算），避免两处各写
一份、日后行为漂移。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models.job import Job
from ..schemas.job import JobCreate, JobUpdate
from .jd_parser import parse_jd


def _keywords_for(job: Job) -> list[dict]:
    """按 JD 内容解析技能标签；列表页与详情页直接读这一列。"""
    return [
        tag.model_dump()
        for tag in parse_jd(f"{job.description}\n{job.requirements}\n{job.additional_info}")[
            "skills"
        ]
    ]


def create_job_record(db: Session, payload: JobCreate) -> Job:
    job = Job(**payload.model_dump())
    job.keywords = _keywords_for(job)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def update_job_record(db: Session, job: Job, payload: JobUpdate) -> Job:
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(job, field, value)
    # 只有 JD 内容变了才值得重算标签。
    if {"description", "requirements", "additional_info"}.intersection(data):
        job.keywords = _keywords_for(job)
    db.commit()
    db.refresh(job)
    return job
