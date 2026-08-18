"""个人资料接口：读取与整体更新。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas.profile import ProfileOut, ProfileTextParseRequest, ProfileTextParseResult, ProfileUpdate
from ..services.profile_text_parser import parse_profile_text
from ..services.profile_service import get_profile_detail, to_profile_out, update_profile

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("", response_model=ProfileOut)
def get_profile(db: Session = Depends(get_db)):
    return to_profile_out(get_profile_detail(db))


@router.put("", response_model=ProfileOut)
def save_profile(payload: ProfileUpdate, db: Session = Depends(get_db)):
    return to_profile_out(update_profile(db, payload))


@router.post("/parse-text", response_model=ProfileTextParseResult)
def parse_profile_text_draft(payload: ProfileTextParseRequest):
    """把用户粘贴的个人资料拆成可编辑草稿，不写入数据库。"""
    return parse_profile_text(payload.text)
