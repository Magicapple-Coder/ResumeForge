"""题库历史 / 面试复盘历史接口（prefix ``/api/interview``，挂在面试模块下）。

题库与复盘本体「即时生成、不落库」，这里提供「保存成历史 → 列表回看 → 单条查看 → 删除（软删）」
的薄路由。删除走 ``trash.soft_delete``，彻底删除在「回收站」里另做。

注意：这些路由用 ``/question-banks``、``/reviews`` 这样的**字面量段**，必须注册在
``interview.router``（含 ``/{session_id}`` 这种参数段）之前，否则会被 ``session_id`` 抢走。
``application.py`` 里已按此顺序装配。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas.interview_history import (
    InterviewReviewRecordCreate,
    InterviewReviewRecordOut,
    InterviewReviewRecordUpdate,
    QuestionBankRecordCreate,
    QuestionBankRecordOut,
    QuestionBankRecordUpdate,
)
from ..services.interview import interview_history

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/interview", tags=["interview-history"])


@router.get("/question-banks", response_model=list[QuestionBankRecordOut])
def read_question_banks(
    limit: int = Query(default=100, ge=1, le=200), db: Session = Depends(get_db)
):
    """题库历史列表（只含未删除的，最近更新的在前）。"""
    return interview_history.list_question_banks(db, limit=limit)


@router.post("/question-banks", response_model=QuestionBankRecordOut, status_code=201)
def create_question_bank_entry(payload: QuestionBankRecordCreate, db: Session = Depends(get_db)):
    """保存一次生成的题库为历史。"""
    return interview_history.create_question_bank(db, payload)


@router.get("/question-banks/{record_id}", response_model=QuestionBankRecordOut)
def read_question_bank(record_id: int, db: Session = Depends(get_db)):
    record = interview_history.question_bank_or_none(db, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="题库历史不存在或已被删除")
    return record


@router.delete("/question-banks/{record_id}", status_code=204)
def remove_question_bank(record_id: int, db: Session = Depends(get_db)):
    if not interview_history.delete_question_bank(db, record_id):
        raise HTTPException(status_code=404, detail="题库历史不存在或已被删除")


@router.patch("/question-banks/{record_id}", response_model=QuestionBankRecordOut)
def update_question_bank_entry(
    record_id: int, payload: QuestionBankRecordUpdate, db: Session = Depends(get_db)
):
    """局部更新题库历史（历史记录富还原：把新生成的参考答案写回同一条记录）。"""
    record = interview_history.update_question_bank(db, record_id, payload)
    if record is None:
        raise HTTPException(status_code=404, detail="题库历史不存在或已被删除")
    return record


@router.get("/reviews", response_model=list[InterviewReviewRecordOut])
def read_reviews(
    limit: int = Query(default=100, ge=1, le=200), db: Session = Depends(get_db)
):
    """复盘历史列表（只含未删除的，最近更新的在前）。"""
    return interview_history.list_reviews(db, limit=limit)


@router.post("/reviews", response_model=InterviewReviewRecordOut, status_code=201)
def create_review_entry(payload: InterviewReviewRecordCreate, db: Session = Depends(get_db)):
    """保存一次面试复盘为历史。"""
    return interview_history.create_review(db, payload)


@router.get("/reviews/{record_id}", response_model=InterviewReviewRecordOut)
def read_review(record_id: int, db: Session = Depends(get_db)):
    record = interview_history.review_or_none(db, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="复盘历史不存在或已被删除")
    return record


@router.delete("/reviews/{record_id}", status_code=204)
def remove_review(record_id: int, db: Session = Depends(get_db)):
    if not interview_history.delete_review(db, record_id):
        raise HTTPException(status_code=404, detail="复盘历史不存在或已被删除")


@router.patch("/reviews/{record_id}", response_model=InterviewReviewRecordOut)
def update_review_entry(
    record_id: int, payload: InterviewReviewRecordUpdate, db: Session = Depends(get_db)
):
    """局部更新复盘历史（历史记录富还原：把新复盘/反向优化结果写回同一条记录）。"""
    record = interview_history.update_review(db, record_id, payload)
    if record is None:
        raise HTTPException(status_code=404, detail="复盘历史不存在或已被删除")
