"""简历写作增强接口（prefix ``/api/resumes``）。

薄路由：只做校验、调 service、返回 schema。写作/润色/翻译依赖模型，未配置时返回清晰
中文错误（不做本地降级、不伪造结果）；版本对比是纯本地 difflib，不依赖模型。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.claim import ClaimRecord
from ..models.resume import ResumeRecord
from ..schemas.resume_writing import (
    PhrasesOut,
    PhrasesRequest,
    PolishOut,
    PolishRequest,
    ResumeDiffOut,
    ResumeDiffRequest,
    StarRewriteOut,
    StarRewriteRequest,
    TranslateOut,
    TranslateRequest,
)
from ..services import trash
from ..services.llm import create_provider
from ..services.llm.base import LLMError
from ..services.resume_diff import build_resume_diff
from ..services.resume_writing import generate_phrases, polish, rewrite_star, translate
from ..services.settings_service import get_llm_config

router = APIRouter(prefix="/api/resumes", tags=["resume-writing"])
logger = logging.getLogger(__name__)


def _load_record(db: Session, resume_id: int) -> ResumeRecord:
    record = db.get(ResumeRecord, resume_id)
    if record is None or trash.is_deleted(record):
        raise HTTPException(status_code=404, detail="简历记录不存在或已被删除")
    return record


def _require_provider(db: Session):
    config = get_llm_config(db)
    if not config.base_url or not config.model:
        raise HTTPException(status_code=400, detail="请先在「设置」页配置大模型 API")
    return create_provider(config)


@router.post("/{resume_id}/writing/star", response_model=StarRewriteOut)
async def star_rewrite(
    resume_id: int, payload: StarRewriteRequest, db: Session = Depends(get_db)
):
    _load_record(db, resume_id)
    claim = None
    if payload.claim_id is not None:
        candidate = db.get(ClaimRecord, payload.claim_id)
        if candidate is not None and not trash.is_deleted(candidate):
            claim = candidate
    provider = _require_provider(db)
    db.close()
    try:
        result = await rewrite_star(provider, payload.text, claim)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"STAR 改写失败：{exc}") from exc
    except Exception as exc:  # noqa: BLE001 - 为用户提供可理解的失败提示
        logger.exception("STAR 改写发生内部错误")
        raise HTTPException(status_code=502, detail="STAR 改写失败，请稍后重试") from exc
    return StarRewriteOut(result=result)


@router.post("/{resume_id}/writing/phrases", response_model=PhrasesOut)
async def phrases(resume_id: int, payload: PhrasesRequest, db: Session = Depends(get_db)):
    _load_record(db, resume_id)
    provider = _require_provider(db)
    db.close()
    try:
        result = await generate_phrases(provider, payload.text, list(payload.modes))
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"生成话术失败：{exc}") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("生成话术发生内部错误")
        raise HTTPException(status_code=502, detail="生成话术失败，请稍后重试") from exc
    return PhrasesOut(**result)


@router.post("/{resume_id}/writing/polish", response_model=PolishOut)
async def polish_resume(
    resume_id: int, payload: PolishRequest, db: Session = Depends(get_db)
):
    _load_record(db, resume_id)
    provider = _require_provider(db)
    db.close()
    try:
        result = await polish(provider, payload.text, payload.style)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"润色失败：{exc}") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("润色发生内部错误")
        raise HTTPException(status_code=502, detail="润色失败，请稍后重试") from exc
    return PolishOut(result=result)


@router.post("/{resume_id}/writing/translate", response_model=TranslateOut)
async def translate_resume(
    resume_id: int, payload: TranslateRequest, db: Session = Depends(get_db)
):
    _load_record(db, resume_id)
    provider = _require_provider(db)
    db.close()
    try:
        result = await translate(provider, payload.text, payload.direction)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"翻译失败：{exc}") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("翻译发生内部错误")
        raise HTTPException(status_code=502, detail="翻译失败，请稍后重试") from exc
    return TranslateOut(result=result)


@router.post("/{resume_id}/diff", response_model=ResumeDiffOut)
def diff_resume(resume_id: int, payload: ResumeDiffRequest, db: Session = Depends(get_db)):
    """两份简历的三态差异；纯本地计算，不调用模型。"""
    base = _load_record(db, resume_id)
    against = db.get(ResumeRecord, payload.against_id)
    if against is None or trash.is_deleted(against):
        raise HTTPException(status_code=404, detail="对比的简历记录不存在或已被删除")
    if against.id == base.id:
        raise HTTPException(status_code=400, detail="不能与同一份简历对比")
    return build_resume_diff(
        base.id,
        base.title,
        base.content or {},
        against.id,
        against.title,
        against.content or {},
    )


__all__ = ["router"]
