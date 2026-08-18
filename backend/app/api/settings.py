"""设置接口：大模型配置的读取、保存与连通性测试。"""
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.setting import LLMConfigRecord
from ..schemas.setting import (
    LLMConfig,
    LLMConfigRecordCreate,
    LLMConfigRecordOut,
    LLMTestRequest,
    LLMTestResult,
)
from ..services.llm import create_provider
from ..services.llm.base import LLMError
from ..services.settings_service import (
    delete_llm_config_record,
    get_llm_config,
    list_llm_config_records,
    mask_llm_config,
    resolve_llm_config_api_key,
    save_llm_config,
    save_llm_config_record,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/llm/records", response_model=list[LLMConfigRecordOut])
def read_llm_config_records(db: Session = Depends(get_db)):
    return list_llm_config_records(db)


@router.post("/llm/records", response_model=LLMConfigRecordOut)
def write_llm_config_record(payload: LLMConfigRecordCreate, db: Session = Depends(get_db)):
    try:
        return save_llm_config_record(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/llm/records/{record_id}", status_code=204)
def remove_llm_config_record(record_id: int, db: Session = Depends(get_db)):
    record = db.get(LLMConfigRecord, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="配置记录不存在或已被删除")
    delete_llm_config_record(db, record_id)


@router.get("/llm", response_model=LLMConfig)
def read_llm_config(db: Session = Depends(get_db)):
    return mask_llm_config(db, get_llm_config(db))


@router.put("/llm", response_model=LLMConfig)
def write_llm_config(payload: LLMConfig, db: Session = Depends(get_db)):
    try:
        saved = save_llm_config(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return mask_llm_config(db, saved)


@router.post("/llm/test", response_model=LLMTestResult)
async def test_llm(payload: LLMTestRequest, db: Session = Depends(get_db)):
    """测试连通性：用表单当前值发起一次最小对话，不要求先保存。"""
    if not payload.base_url or not payload.model:
        return LLMTestResult(ok=False, message="请先填写 Base URL 与模型名称")
    try:
        resolved_payload = resolve_llm_config_api_key(db, payload)
    except ValueError as exc:
        return LLMTestResult(ok=False, message=str(exc))
    provider = create_provider(resolved_payload)
    started = time.perf_counter()
    try:
        reply = await provider.chat([{"role": "user", "content": "请只回复两个字：正常"}])
    except LLMError as exc:
        logger.warning("LLM 连接测试失败：%s", exc)
        return LLMTestResult(ok=False, message=str(exc))
    latency_ms = int((time.perf_counter() - started) * 1000)
    return LLMTestResult(
        ok=True,
        latency_ms=latency_ms,
        message=f"连接成功，模型回复「{reply.strip()[:30]}」",
    )
