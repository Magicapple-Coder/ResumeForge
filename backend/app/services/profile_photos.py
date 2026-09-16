"""个人照片管理：多张照片的增删改与主照片切换。

``UserProfile.photo`` 始终是"当前使用的那一张"的镜像：简历生成、预览和导出全部读
它，所以切换/删除照片时同步维护该字段，老链路一行都不用改。
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ..models.profile import ProfilePhoto, UserProfile
from ..schemas.photo import MAX_PROFILE_PHOTOS, ProfilePhotoCreate
from .profile_service import get_or_create_profile

logger = logging.getLogger(__name__)


def _query_photos(db: Session, profile_id: int) -> list[ProfilePhoto]:
    return (
        db.query(ProfilePhoto)
        .filter(ProfilePhoto.profile_id == profile_id)
        .order_by(ProfilePhoto.id)
        .all()
    )


def list_photos(db: Session) -> list[ProfilePhoto]:
    """列出照片；首次调用时把老的单张照片转成一条可管理的记录。"""
    profile = get_or_create_profile(db)
    photos = _query_photos(db, profile.id)
    if not photos and profile.photo:
        # 兼容：早期版本只有一张照片存在 user_profile.photo。第一次打开照片面板时
        # 把它变成可管理的记录，用户不必重新上传。
        photo = ProfilePhoto(
            profile_id=profile.id,
            name="当前照片",
            image=profile.photo,
            is_primary=True,
        )
        db.add(photo)
        db.commit()
        db.refresh(photo)
        return [photo]
    return photos


def _sync_primary(db: Session, profile: UserProfile, photo: ProfilePhoto) -> None:
    """把某张照片设为主照片，并同步老链路读取的 user_profile.photo。"""
    for item in _query_photos(db, profile.id):
        item.is_primary = item.id == photo.id
    profile.photo = photo.image


def add_photo(db: Session, payload: ProfilePhotoCreate) -> ProfilePhoto:
    profile = get_or_create_profile(db)
    existing = _query_photos(db, profile.id)
    if len(existing) >= MAX_PROFILE_PHOTOS:
        raise ValueError(f"最多保存 {MAX_PROFILE_PHOTOS} 张照片，请先删除不再使用的")
    is_primary = not existing or not any(item.is_primary for item in existing)
    photo = ProfilePhoto(
        profile_id=profile.id,
        name=payload.name.strip()[:128] or f"照片 {len(existing) + 1}",
        image=payload.image,
        is_primary=is_primary,
    )
    db.add(photo)
    db.flush()
    if is_primary:
        _sync_primary(db, profile, photo)
    db.commit()
    db.refresh(photo)
    logger.info("已保存个人照片 id=%s 主照片=%s", photo.id, is_primary)
    return photo


def rename_photo(db: Session, photo_id: int, name: str) -> ProfilePhoto | None:
    photo = db.get(ProfilePhoto, photo_id)
    if photo is None:
        return None
    photo.name = name.strip()[:128]
    db.commit()
    db.refresh(photo)
    return photo


def set_primary_photo(db: Session, photo_id: int) -> ProfilePhoto | None:
    photo = db.get(ProfilePhoto, photo_id)
    if photo is None:
        return None
    profile = get_or_create_profile(db)
    _sync_primary(db, profile, photo)
    db.commit()
    db.refresh(photo)
    return photo


def delete_photo(db: Session, photo_id: int) -> bool:
    photo = db.get(ProfilePhoto, photo_id)
    if photo is None:
        return False
    profile = get_or_create_profile(db)
    was_primary = photo.is_primary
    db.delete(photo)
    db.flush()
    remaining = _query_photos(db, profile.id)
    if was_primary or not any(item.is_primary for item in remaining):
        if remaining:
            # 删掉主照片后自动把下一张设为主照片，避免简历突然没有照片。
            _sync_primary(db, profile, remaining[0])
        else:
            profile.photo = ""
    db.commit()
    return True


__all__ = [
    "add_photo",
    "delete_photo",
    "list_photos",
    "rename_photo",
    "set_primary_photo",
]
