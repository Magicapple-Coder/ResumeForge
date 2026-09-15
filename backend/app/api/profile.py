"""个人资料接口：读取、整体更新与文本识别草稿。"""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas.profile import ProfileOut, ProfileTextParseRequest, ProfileTextParseResult, ProfileUpdate
from ..services.profile_text_parser import parse_profile_text
from ..services.profile_service import get_profile_detail, to_profile_out, update_profile
from ..services.llm import create_provider
from ..services.llm.base import LLMError
from ..services.settings_service import get_llm_config
from ..services.text_extraction import (
    extract_profile_text,
    llm_is_configured,
    mark_local_fallback,
)

router = APIRouter(prefix="/api/profile", tags=["profile"])
logger = logging.getLogger(__name__)


@router.get("", response_model=ProfileOut)
def get_profile(db: Session = Depends(get_db)):
    return to_profile_out(get_profile_detail(db))


@router.put("", response_model=ProfileOut)
def save_profile(payload: ProfileUpdate, db: Session = Depends(get_db)):
    return to_profile_out(update_profile(db, payload))


@router.post("/parse-text", response_model=ProfileTextParseResult)
async def parse_profile_text_draft(payload: ProfileTextParseRequest, db: Session = Depends(get_db)):
    """把用户粘贴的个人资料拆成可编辑草稿，不写入数据库。"""
    local_draft = parse_profile_text(payload.text)
    config = get_llm_config(db)
    if not llm_is_configured(config):
        return mark_local_fallback(local_draft, "未配置大模型，已使用本地规则识别，请核对后保存。")
    provider = create_provider(config)
    db.close()
    try:
        return await extract_profile_text(provider, payload.text, local_draft)
    except LLMError as exc:
        logger.warning("个人资料 AI 识别失败，已回退本地解析：%s", exc)
        return mark_local_fallback(local_draft, "AI 识别暂不可用，已使用本地规则识别，请核对后保存。")
    except Exception:  # noqa: BLE001 - 外部模型异常不能阻断草稿解析
        logger.exception("个人资料 AI 识别发生内部错误，已回退本地解析")
        return mark_local_fallback(local_draft, "AI 识别暂不可用，已使用本地规则识别，请核对后保存。")
