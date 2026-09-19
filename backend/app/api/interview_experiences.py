"""面经知识库接口（prefix ``/api/interview-experiences``）。

真实面经的增删改查：正文 + 真实问题清单 + 标签，可绑定岗位。删除走软删除
（``trash.live_only`` 列表里不再出现），彻底删除在回收站里另做。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.interview_experience import EXPERIENCE_SOURCES
from ..schemas.interview_experience import (
    InterviewExperienceCreate,
    InterviewExperienceOut,
    InterviewExperienceUpdate,
)
from ..services.interview_experience_service import (
    create_experience,
    delete_experience,
    experience_or_none,
    list_experiences,
    update_experience,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/interview-experiences", tags=["interview-experiences"])


@router.get("", response_model=list[InterviewExperienceOut])
def read_experiences(
    keyword: str = Query(default=""),
    company: str = Query(default=""),
    source: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return list_experiences(db, keyword=keyword, company=company, source=source, limit=limit)


@router.get("/sources", response_model=list[str])
def read_sources():
    """来源白名单：前端下拉与筛选共用后端唯一取值。"""
    return list(EXPERIENCE_SOURCES)


@router.post("", response_model=InterviewExperienceOut, status_code=201)
def create_experience_entry(payload: InterviewExperienceCreate, db: Session = Depends(get_db)):
    return create_experience(db, payload)


@router.get("/{experience_id}", response_model=InterviewExperienceOut)
def read_experience(experience_id: int, db: Session = Depends(get_db)):
    experience = experience_or_none(db, experience_id)
    if experience is None:
        raise HTTPException(status_code=404, detail="面经不存在或已被删除")
    return experience


@router.put("/{experience_id}", response_model=InterviewExperienceOut)
def save_experience(
    experience_id: int, payload: InterviewExperienceUpdate, db: Session = Depends(get_db)
):
    experience = experience_or_none(db, experience_id)
    if experience is None:
        raise HTTPException(status_code=404, detail="面经不存在或已被删除")
    return update_experience(db, experience, payload)


@router.delete("/{experience_id}", status_code=204)
def remove_experience(experience_id: int, db: Session = Depends(get_db)):
    if not delete_experience(db, experience_id):
        raise HTTPException(status_code=404, detail="面经不存在或已被删除")
