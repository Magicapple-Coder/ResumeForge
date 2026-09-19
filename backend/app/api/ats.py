"""ATS 本地检测接口（prefix ``/api/resumes``）。

纯本地计算，不调用模型：加载简历 → 调 ``services/ats_check`` → 返回带免责声明的结论。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.resume import ResumeRecord
from ..schemas.ats import AtsCheckOut, AtsCheckRequest
from ..schemas.resume import ResumeContent
from ..services import trash
from ..services.ats_check import check_ats

router = APIRouter(prefix="/api/resumes", tags=["ats"])


def _load_record(db: Session, resume_id: int) -> ResumeRecord:
    record = db.get(ResumeRecord, resume_id)
    if record is None or trash.is_deleted(record):
        raise HTTPException(status_code=404, detail="简历记录不存在或已被删除")
    return record


@router.post("/{resume_id}/ats-check", response_model=AtsCheckOut)
def ats_check(resume_id: int, payload: AtsCheckRequest, db: Session = Depends(get_db)):
    record = _load_record(db, resume_id)
    content_data = dict(record.content or {})
    content_data["photo"] = ""
    content = ResumeContent.model_validate(content_data)
    return check_ats(content, jd_text=payload.jd_text, resume_id=resume_id)


__all__ = ["router"]
