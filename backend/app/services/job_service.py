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


MAX_JOB_NOTE_CHARS = 2000


def note_with_source(note: str, recognition_source: str) -> str:
    """在备注末尾补一行来源标注，方便用户回溯这条招聘信息是怎么来的。

    已经标过就不再重复追加：用户来回编辑同一条岗位时不该积累出一串"来源："。
    """
    source = (recognition_source or "").strip()
    note = (note or "").strip()
    if not source:
        return note[:MAX_JOB_NOTE_CHARS]
    marker = f"来源：{source}"
    if marker in note:
        return note[:MAX_JOB_NOTE_CHARS]
    merged = f"{note}\n{marker}" if note else marker
    return merged[:MAX_JOB_NOTE_CHARS]


def create_job_record(db: Session, payload: JobCreate) -> Job:
    data = payload.model_dump()
    data["note"] = note_with_source(data.get("note", ""), data.get("recognition_source", ""))
    job = Job(**data)
    job.keywords = _keywords_for(job)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def update_job_record(db: Session, job: Job, payload: JobUpdate) -> Job:
    data = payload.model_dump(exclude_unset=True)
    if "recognition_source" in data or ("note" in data and job.recognition_source):
        # 修改备注时保持来源标注仍在（用户在表单里改掉整段备注也不丢溯源信息）。
        data["note"] = note_with_source(
            data.get("note", job.note),
            data.get("recognition_source", job.recognition_source),
        )
    for field, value in data.items():
        setattr(job, field, value)
    # 只有 JD 内容变了才值得重算标签。
    if {"description", "requirements", "additional_info"}.intersection(data):
        job.keywords = _keywords_for(job)
    db.commit()
    db.refresh(job)
    return job
