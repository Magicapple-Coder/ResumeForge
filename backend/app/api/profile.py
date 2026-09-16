"""个人资料接口：读取、整体更新与文本识别草稿。"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas.photo import ProfilePhotoCreate, ProfilePhotoOut, ProfilePhotoUpdate
from ..schemas.profile import ProfileOut, ProfileTextParseRequest, ProfileTextParseResult, ProfileUpdate
from ..services.profile_photos import (
    add_photo,
    delete_photo,
    list_photos,
    rename_photo,
    set_primary_photo,
)
from ..services.profile_text_parser import parse_profile_text
from ..services.profile_service import get_profile_detail, to_profile_out, update_profile
from ..services.llm import create_provider
from ..services.llm.base import LLMError
from ..services.settings_service import get_llm_config
from ..services.attachments import (
    assert_attachment_budget,
    image_data_urls,
    normalize_extraction_images,
    total_attachment_bytes,
)
from ..services.document_text import extract_documents_text
from ..services.text_extraction import (
    ai_failed_warning,
    extract_profile_text,
    finalize_recognition_result,
    llm_is_configured,
    mark_local_fallback,
    no_model_warning,
)

router = APIRouter(prefix="/api/profile", tags=["profile"])
logger = logging.getLogger(__name__)


@router.get("", response_model=ProfileOut)
def get_profile(db: Session = Depends(get_db)):
    return to_profile_out(get_profile_detail(db))


@router.put("", response_model=ProfileOut)
def save_profile(payload: ProfileUpdate, db: Session = Depends(get_db)):
    return to_profile_out(update_profile(db, payload))


@router.get("/photos", response_model=list[ProfilePhotoOut])
def read_photos(db: Session = Depends(get_db)):
    """列出已保存的个人照片；当前使用的那张带 ``is_primary``。"""
    return list_photos(db)


@router.post("/photos", response_model=ProfilePhotoOut, status_code=201)
def create_photo(payload: ProfilePhotoCreate, db: Session = Depends(get_db)):
    try:
        return add_photo(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/photos/{photo_id}", response_model=ProfilePhotoOut)
def update_photo(photo_id: int, payload: ProfilePhotoUpdate, db: Session = Depends(get_db)):
    """重命名照片，或把它设为当前使用的照片。

    没有"取消主照片"的语义：照片面板总要有且只有一张在用的照片，切换只能靠
    ``is_primary=true`` 指到另一张。
    """
    if payload.name is None and payload.is_primary is not True:
        raise HTTPException(status_code=422, detail="请提供要修改的照片字段")
    photo = None
    if payload.name is not None:
        photo = rename_photo(db, photo_id, payload.name)
        if photo is None:
            raise HTTPException(status_code=404, detail="照片不存在或已被删除")
    if payload.is_primary:
        photo = set_primary_photo(db, photo_id)
        if photo is None:
            raise HTTPException(status_code=404, detail="照片不存在或已被删除")
    return photo


@router.delete("/photos/{photo_id}", status_code=204)
def remove_photo(photo_id: int, db: Session = Depends(get_db)):
    if not delete_photo(db, photo_id):
        raise HTTPException(status_code=404, detail="照片不存在或已被删除")


@router.post("/parse-text", response_model=ProfileTextParseResult)
async def parse_profile_text_draft(payload: ProfileTextParseRequest, db: Session = Depends(get_db)):
    """把用户粘贴的个人资料（或截图、文档）拆成可编辑草稿，不写入数据库。"""
    try:
        images = normalize_extraction_images(payload.images)
        documents = extract_documents_text(payload.documents)
        assert_attachment_budget(
            count=len(payload.images) + len(payload.documents),
            total_bytes=total_attachment_bytes(images) + documents.size_bytes,
        )
    except ValueError as exc:
        # 在路由层抛：只有 HTTPException 的 detail 会被前端原样展示。
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    image_urls = image_data_urls(images)
    has_images = bool(image_urls)
    has_documents = bool(payload.documents)

    # 文档文字与粘贴文本合并成同一份 source_text：本地规则与模型看到的材料一致，
    # 字段锚定也仍然对着原文，比图片那条"让模型自己抄录再核对"的路子强。
    source_text = "\n\n".join(part for part in (payload.text, documents.text) if part.strip())
    local_draft = parse_profile_text(source_text)
    config = get_llm_config(db)
    if not llm_is_configured(config):
        return finalize_recognition_result(
            mark_local_fallback(local_draft, no_model_warning(has_images, has_documents)),
            has_images=has_images,
            document_warnings=documents.warnings,
        )
    provider = create_provider(config)
    db.close()
    try:
        result = await extract_profile_text(provider, source_text, local_draft, image_urls)
    except LLMError as exc:
        logger.warning("个人资料 AI 识别失败，已回退本地解析：%s", exc)
        result = mark_local_fallback(
            local_draft, ai_failed_warning(has_images, str(exc), has_documents)
        )
    except Exception:  # noqa: BLE001 - 外部模型异常不能阻断草稿解析
        logger.exception("个人资料 AI 识别发生内部错误，已回退本地解析")
        result = mark_local_fallback(local_draft, ai_failed_warning(has_images, has_documents=has_documents))
    return finalize_recognition_result(
        result, has_images=has_images, document_warnings=documents.warnings
    )
