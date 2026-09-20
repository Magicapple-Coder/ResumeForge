"""D5 题库历史 / 面试复盘历史的持久化。

题库与复盘本体是「即时生成、不落库」的（``services/interview_questions``），本模块只负责把用户
主动「保存」的那一份落成历史，供回看与删除。与本体解耦：生成不自动存，点「保存」才存。

- **岗位/简历被删不连坐**：``job_id``/``resume_id`` 外键 ``SET NULL``，快照字段仍保留。
- **列表查询一律用 ``trash.live_only``**，回收站里的记录不出现。
- **删除走 ``trash.soft_delete``**，彻底删除在「回收站」里单独提供。
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from . import trash
from ..models.interview_review_record import InterviewReviewRecord
from ..models.job import Job
from ..models.question_bank_record import QuestionBankRecord
from ..models.resume import ResumeRecord
from ..schemas.interview_history import (
    InterviewReviewRecordCreate,
    InterviewReviewRecordUpdate,
    QuestionBankRecordCreate,
    QuestionBankRecordUpdate,
)

logger = logging.getLogger(__name__)

MAX_HISTORY_LIST = 200


def _job_snapshot(
    db: Session, job_id: int | None, job_title: str, company: str
) -> tuple[int | None, str, str]:
    """解析岗位关联：岗位不存在则置空关联（外键 SET NULL），否则回填空快照。"""
    if job_id is None:
        return None, job_title, company
    job = db.get(Job, job_id)
    if job is None:
        return None, job_title, company
    return job.id, job_title or job.title, company or job.company


def _resume_snapshot(
    db: Session, resume_id: int | None, resume_title: str
) -> tuple[int | None, str]:
    """解析简历关联：简历不存在则置空关联，否则回填空快照。"""
    if resume_id is None:
        return None, resume_title
    resume = db.get(ResumeRecord, resume_id)
    if resume is None:
        return None, resume_title
    return resume.id, resume_title or resume.title


# ===== 题库历史 =====


def list_question_banks(db: Session, *, limit: int = 100) -> list[QuestionBankRecord]:
    """只取未软删除的题库历史，最近更新的在前。"""
    return (
        db.query(QuestionBankRecord)
        .filter(trash.live_only(QuestionBankRecord))
        .order_by(QuestionBankRecord.updated_at.desc(), QuestionBankRecord.id.desc())
        .limit(max(1, min(limit, MAX_HISTORY_LIST)))
        .all()
    )


def question_bank_or_none(db: Session, record_id: int) -> QuestionBankRecord | None:
    """取一条题库历史；已在回收站里的当作不存在。"""
    return trash.get_live(db, QuestionBankRecord, record_id)


def create_question_bank(db: Session, payload: QuestionBankRecordCreate) -> QuestionBankRecord:
    """保存一次生成的题库（不落库本体 → 落历史）。"""
    job_id, job_title, company = _job_snapshot(
        db, payload.job_id, payload.job_title, payload.company
    )
    resume_id, resume_title = _resume_snapshot(db, payload.resume_id, payload.resume_title)
    record = QuestionBankRecord(
        job_id=job_id,
        job_title=job_title,
        company=company,
        resume_id=resume_id,
        resume_title=resume_title,
        groups=[group.model_dump() for group in payload.groups],
        model=payload.model,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    logger.info("已保存题库历史 id=%s groups=%s", record.id, len(record.groups))
    return record


def delete_question_bank(db: Session, record_id: int) -> bool:
    """移入回收站（软删除）；彻底删除在「回收站」里单独提供。"""
    record = db.get(QuestionBankRecord, record_id)
    if record is None or trash.is_deleted(record):
        return False
    trash.soft_delete(db, "question_bank_record", record)
    db.commit()
    return True


def update_question_bank(
    db: Session, record_id: int, payload: QuestionBankRecordUpdate
) -> QuestionBankRecord | None:
    """局部更新题库历史（历史记录富还原：把新生成的参考答案写回同一条记录）。

    只更新请求里提供的字段，其余保持原值；记录不存在或在回收站里返回 ``None``。
    """
    record = trash.get_live(db, QuestionBankRecord, record_id)
    if record is None:
        return None
    if payload.groups is not None:
        record.groups = [group.model_dump() for group in payload.groups]
    if payload.job_title is not None:
        record.job_title = payload.job_title
    if payload.company is not None:
        record.company = payload.company
    if payload.resume_title is not None:
        record.resume_title = payload.resume_title
    db.commit()
    db.refresh(record)
    logger.info("已更新题库历史 id=%s 字段=%s", record.id, payload.model_dump(exclude_none=True))
    return record


# ===== 复盘历史 =====


def list_reviews(db: Session, *, limit: int = 100) -> list[InterviewReviewRecord]:
    """只取未软删除的复盘历史，最近更新的在前。"""
    return (
        db.query(InterviewReviewRecord)
        .filter(trash.live_only(InterviewReviewRecord))
        .order_by(InterviewReviewRecord.updated_at.desc(), InterviewReviewRecord.id.desc())
        .limit(max(1, min(limit, MAX_HISTORY_LIST)))
        .all()
    )


def review_or_none(db: Session, record_id: int) -> InterviewReviewRecord | None:
    """取一条复盘历史；已在回收站里的当作不存在。"""
    return trash.get_live(db, InterviewReviewRecord, record_id)


def create_review(db: Session, payload: InterviewReviewRecordCreate) -> InterviewReviewRecord:
    """保存一次面试复盘（问题清单 + 答题思路 + 反向优化建议）。"""
    job_id, job_title, company = _job_snapshot(
        db, payload.job_id, payload.job_title, payload.company
    )
    resume_id, resume_title = _resume_snapshot(db, payload.resume_id, payload.resume_title)
    record = InterviewReviewRecord(
        job_id=job_id,
        job_title=job_title,
        company=company,
        resume_id=resume_id,
        resume_title=resume_title,
        questions=[str(item).strip() for item in payload.questions if str(item).strip()],
        analysis=payload.analysis,
        suggestions=payload.suggestions,
        model=payload.model,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    logger.info("已保存复盘历史 id=%s questions=%s", record.id, len(record.questions))
    return record


def delete_review(db: Session, record_id: int) -> bool:
    """移入回收站（软删除）；彻底删除在「回收站」里单独提供。"""
    record = db.get(InterviewReviewRecord, record_id)
    if record is None or trash.is_deleted(record):
        return False
    trash.soft_delete(db, "interview_review_record", record)
    db.commit()
    return True


def update_review(
    db: Session, record_id: int, payload: InterviewReviewRecordUpdate
) -> InterviewReviewRecord | None:
    """局部更新复盘历史（历史记录富还原：把新复盘/反向优化结果写回同一条记录）。

    只更新请求里提供的字段，其余保持原值；记录不存在或在回收站里返回 ``None``。
    """
    record = trash.get_live(db, InterviewReviewRecord, record_id)
    if record is None:
        return None
    if payload.questions is not None:
        record.questions = [str(item).strip() for item in payload.questions if str(item).strip()]
    if payload.analysis is not None:
        record.analysis = payload.analysis
    if payload.suggestions is not None:
        record.suggestions = payload.suggestions
    if payload.job_title is not None:
        record.job_title = payload.job_title
    if payload.company is not None:
        record.company = payload.company
    if payload.resume_title is not None:
        record.resume_title = payload.resume_title
    db.commit()
    db.refresh(record)
    logger.info("已更新复盘历史 id=%s 字段=%s", record.id, payload.model_dump(exclude_none=True))
    return record


__all__ = [
    "MAX_HISTORY_LIST",
    "create_question_bank",
    "create_review",
    "delete_question_bank",
    "delete_review",
    "list_question_banks",
    "list_reviews",
    "question_bank_or_none",
    "review_or_none",
    "update_question_bank",
    "update_review",
]
