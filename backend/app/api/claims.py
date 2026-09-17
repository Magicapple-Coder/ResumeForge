"""事实台账接口。

路由顺序有讲究：``/baseline`` 与 ``/draft`` 必须注册在 ``/{claim_id}`` **之前**，
否则 FastAPI 会先匹配到带路径参数的那条，把 ``baseline`` 当成 claim_id 去解析成整数，
返回一个和"路由不存在"很像的 422。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.claim import CLAIM_CATEGORIES, VERIFICATION_STATUSES
from ..schemas.claim import (
    ClaimCreate,
    ClaimDigestOut,
    ClaimDraftOut,
    ClaimDraftRequest,
    ClaimListOut,
    ClaimOut,
    ClaimUpdate,
)
from ..services.claim_draft import draft_from_text
from ..services.claims import (
    build_baseline,
    claim_or_none,
    claim_out,
    create_claim,
    delete_claim,
    list_claims,
    summarize,
    update_claim,
)
from ..services.llm.base import LLMError

router = APIRouter(prefix="/api/claims", tags=["claims"])
logger = logging.getLogger(__name__)


@router.get("", response_model=ClaimListOut)
def read_claims(
    category: str = Query(default=""),
    status: str = Query(default=""),
    keyword: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """列出事实台账条目；可按分类、核实状态与关键词过滤。"""
    if category and category not in CLAIM_CATEGORIES:
        raise HTTPException(status_code=422, detail="未知的台账分类")
    if status and status not in VERIFICATION_STATUSES:
        raise HTTPException(status_code=422, detail="未知的核实状态")
    records = list_claims(db, category=category, status=status, keyword=keyword)
    return ClaimListOut(
        items=[claim_out(record) for record in records],
        **summarize(records),
    )


@router.post("", response_model=ClaimOut, status_code=201)
def create_claim_entry(payload: ClaimCreate, db: Session = Depends(get_db)):
    return claim_out(create_claim(db, payload))


@router.get("/baseline", response_model=ClaimDigestOut)
def read_baseline(db: Session = Depends(get_db)):
    """当前可用于生成的事实基线（已确认事实 + 必须避开的未确认说法）。"""
    return build_baseline(db)


@router.post("/draft", response_model=ClaimDraftOut)
async def draft_claims(payload: ClaimDraftRequest, db: Session = Depends(get_db)):
    """按一段资料草拟台账条目；只返回草稿，不落库，等用户确认后再保存。"""
    try:
        return await draft_from_text(db, payload)
    except LLMError as exc:
        logger.warning("草拟台账条目失败：%s", exc)
        raise HTTPException(status_code=502, detail=f"提取台账草稿失败：{exc}") from exc


@router.get("/{claim_id}", response_model=ClaimOut)
def read_claim(claim_id: int, db: Session = Depends(get_db)):
    record = claim_or_none(db, claim_id)
    if record is None:
        raise HTTPException(status_code=404, detail="台账条目不存在或已被删除")
    return claim_out(record)


@router.put("/{claim_id}", response_model=ClaimOut)
def save_claim(claim_id: int, payload: ClaimUpdate, db: Session = Depends(get_db)):
    record = claim_or_none(db, claim_id)
    if record is None:
        raise HTTPException(status_code=404, detail="台账条目不存在或已被删除")
    return claim_out(update_claim(db, record, payload))


@router.delete("/{claim_id}", status_code=204)
def remove_claim(claim_id: int, db: Session = Depends(get_db)):
    if not delete_claim(db, claim_id):
        raise HTTPException(status_code=404, detail="台账条目不存在或已被删除")
