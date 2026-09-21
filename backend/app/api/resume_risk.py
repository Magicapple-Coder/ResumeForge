"""简历风险扫描接口（prefix ``/api/resumes``）。

薄路由：加载简历与事实台账，调 ``services/resume/resume_risk``，返回 schema。风险扫描
**只提示不改写**；本地规则不依赖模型，未配置 LLM 时照常返回，配置了 LLM 时做可选增强
（增强失败由 service 自动降级，不阻断）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.claim import ClaimRecord
from ..models.resume import ResumeRecord
from ..schemas.resume import ResumeContent
from ..schemas.resume_risk import RiskScanOut
from ..services import trash
from ..services.llm import create_provider
from ..services.resume.resume_risk import scan_resume_risks
from ..services.settings_service import get_llm_config

router = APIRouter(prefix="/api/resumes", tags=["resume-risk"])


def _load_record(db: Session, resume_id: int) -> ResumeRecord:
    record = db.get(ResumeRecord, resume_id)
    if record is None or trash.is_deleted(record):
        raise HTTPException(status_code=404, detail="简历记录不存在或已被删除")
    return record


def _to_content(record: ResumeRecord) -> ResumeContent:
    """把落库的 JSON 转回结构体；排除 photo 避免照片校验干扰旧数据的体检。"""
    content_data = dict(record.content or {})
    content_data["photo"] = ""
    return ResumeContent.model_validate(content_data)


@router.post("/{resume_id}/risk-scan", response_model=RiskScanOut)
async def risk_scan(resume_id: int, db: Session = Depends(get_db)):
    record = _load_record(db, resume_id)
    content = _to_content(record)
    claims = db.query(ClaimRecord).filter(trash.live_only(ClaimRecord)).all()
    config = get_llm_config(db)
    configured = bool(config.base_url.strip() and config.model.strip())
    provider = create_provider(config) if configured else None
    db.close()
    return await scan_resume_risks(content, claims, provider=provider, resume_id=resume_id)


__all__ = ["router"]
