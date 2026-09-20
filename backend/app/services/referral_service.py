"""内推管理（R-13）的持久化、检索与转化口径。

内推与投递台自动投递是两件事：这里记录的是通过人脉拿到的一次推荐机会。两者通过
``track_id`` 关联——内推成功后若能落到求职进度（``application_track``）里的某条记录，
就算"已转化"。

**转化口径的唯一来源**是关联的 ``ApplicationTrack``：有 ``track_id`` 且该漏斗进入
「面试」及以上（interview / offer）才算 ``converted=True``。**不在 referral 表里手算
第二份口径**——``converted`` 字段只在读取时派生（见 :func:`_is_converted`），写入侧
根本不接受该字段。

- **岗位被删不连坐**：``job_id`` 用 ``SET NULL`` + ``company``/``job_title`` 快照。
- **有效内推** = 状态不是 ``closed``/``invalid``（还在推进中的才算转化率分母）。
- 删除走软删除，列表查询一律 ``trash.live_only``。
"""
from __future__ import annotations

import logging
import secrets
from pathlib import Path

from sqlalchemy import or_
from sqlalchemy.orm import Session

from . import trash
from .ratios import rate
from .attachments import (
    MAX_ATTACHMENT_BYTES,
    declared_mime,
    format_mismatch_error,
    image_mime_for_extension,
    image_mime_of_content,
    image_signature_matches,
    safe_attachment_name,
    unsupported_attachment_error,
)
from ..config import DATA_DIR
from ..models.job import Job
from ..models.referral import (
    REFERRAL_STATUS_ACTIVE,
    REFERRAL_STATUS_SUBMITTED,
    REFERRAL_STATUSES,
    Referral,
)
from ..models.tracker import STATUS_INTERVIEW, STATUS_OFFER, ApplicationTrack
from ..schemas.referral import ReferralCreate, ReferralOut, ReferralStatsOut, ReferralUpdate

logger = logging.getLogger(__name__)

MAX_REFERRAL_LIST = 500

# 内推备注图片的本地目录（相对 ``DATA_DIR``）：与 captures、share_packages 同级，
# 天然不进仓库、不进备份。
REFERRAL_IMAGES_DIRNAME = "referral_images"

# 规范 MIME → 落盘扩展名。上传时若扩展名说谎（.jpg 实为 webp），以内容为准换扩展名。
_EXTENSION_BY_IMAGE_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
}


def referral_images_dir(bind=None) -> Path:
    """内推备注图片目录。

    文件型 SQLite 时落在数据库同目录（测试库自动隔离，不写进仓库的 ``backend/data``），
    其余回退到数据目录——与 ``share_package.share_root`` 同一套规则。
    """
    url = getattr(bind, "url", None)
    database = getattr(url, "database", None)
    if database and database != ":memory:" and Path(database).is_absolute():
        return Path(database).resolve().parent / REFERRAL_IMAGES_DIRNAME
    return DATA_DIR / REFERRAL_IMAGES_DIRNAME

# 有效内推：还没走到终态（closed/invalid）的才计入转化率分母。
_VALID_REFERRAL_STATUSES = (REFERRAL_STATUS_ACTIVE, REFERRAL_STATUS_SUBMITTED)


def save_referral_image(db: Session, filename: str, content_type: str, data: bytes) -> str:
    """校验并保存一张内推备注图片，返回相对路径（``referral_images/<name>``）。

    校验规则复用 ``services/attachments.py`` 的唯一实现：扩展名白名单、声明 MIME 与
    扩展名一致、文件头真是图片、单张不超过 2 MB。文件名只取最后一段且落盘名由服务端
    随机生成，挡路径穿越。
    """
    safe_name = safe_attachment_name(filename)
    canonical_mime = image_mime_for_extension(safe_name)
    if canonical_mime is None:
        raise unsupported_attachment_error(safe_name)

    declared = declared_mime(content_type)
    if declared and declared != canonical_mime:
        raise ValueError(f"附件“{safe_name}”的类型与扩展名不一致")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"附件“{safe_name}”不能超过 2 MB")

    if not image_signature_matches(canonical_mime, data):
        # 与附件校验同一条规则：扩展名可能说谎，以内容为准；认不出真实格式才拒绝。
        detected = image_mime_of_content(data)
        if detected is None:
            raise format_mismatch_error(safe_name, data)
        canonical_mime = detected

    extension = _EXTENSION_BY_IMAGE_MIME[canonical_mime]
    directory = referral_images_dir(db.get_bind())
    directory.mkdir(parents=True, exist_ok=True)
    stored_name = f"{secrets.token_hex(16)}{extension}"
    (directory / stored_name).write_bytes(data)
    return f"{REFERRAL_IMAGES_DIRNAME}/{stored_name}"


def _is_converted(db: Session, referral: Referral) -> bool:
    """转化由关联的 ApplicationTrack 后置位派生，不读表里的冗余布尔。"""
    if referral.track_id is None:
        return False
    track = trash.get_live(db, ApplicationTrack, referral.track_id)
    return track is not None and track.status in (STATUS_INTERVIEW, STATUS_OFFER)


def referral_out(db: Session, referral: Referral) -> ReferralOut:
    """把一条内推转成回显结构，并把 ``converted`` 覆盖为派生口径。"""
    out = ReferralOut.model_validate(referral)
    out.converted = _is_converted(db, referral)
    return out


def list_referrals(
    db: Session, *, status: str = "", keyword: str = "", limit: int = 200
) -> list[Referral]:
    """按状态/关键词过滤；只取未软删除的行，最近更新的在前。"""
    query = db.query(Referral).filter(trash.live_only(Referral))
    if status.strip():
        query = query.filter(Referral.status == status.strip())
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                Referral.company.like(like),
                Referral.position.like(like),
                Referral.job_title.like(like),
                Referral.referrer_name.like(like),
            )
        )
    return (
        query.order_by(Referral.updated_at.desc(), Referral.id.desc())
        .limit(max(1, min(limit, MAX_REFERRAL_LIST)))
        .all()
    )


def referral_or_none(db: Session, referral_id: int) -> Referral | None:
    """取一条内推；已在回收站里的当作不存在。"""
    return trash.get_live(db, Referral, referral_id)


def _apply_payload(db: Session, values: dict) -> dict:
    """归一化写入值：绑定岗位时回填快照，岗位不存在则置空；track 不存在则置空。"""
    if values.get("job_id") is not None:
        job = trash.get_live(db, Job, values["job_id"])
        if job is None:
            values["job_id"] = None
        else:
            if not values.get("company"):
                values["company"] = job.company
            if not values.get("position"):
                values["position"] = job.title
            if not values.get("job_title"):
                values["job_title"] = job.title
    if values.get("track_id") is not None:
        if trash.get_live(db, ApplicationTrack, values["track_id"]) is None:
            values["track_id"] = None
    # 第 6 批新增字段：显式传 null 时归一化为空值，避免写入非空列。
    if "referral_code" in values and values["referral_code"] is None:
        values["referral_code"] = ""
    if "note_images" in values and values["note_images"] is None:
        values["note_images"] = []
    return values


def create_referral(db: Session, payload: ReferralCreate) -> Referral:
    values = _apply_payload(db, payload.model_dump())
    values.pop("converted", None)
    referral = Referral(**values)
    db.add(referral)
    db.commit()
    db.refresh(referral)
    logger.info("已新增内推 id=%s company=%s", referral.id, referral.company)
    return referral


def update_referral(db: Session, referral: Referral, payload: ReferralUpdate) -> Referral:
    """PATCH：只覆盖显式给出的字段，绑定对象同样做 SET NULL + 快照回填。"""
    values = _apply_payload(db, payload.model_dump(exclude_unset=True))
    values.pop("converted", None)
    for field, value in values.items():
        setattr(referral, field, value)
    db.commit()
    db.refresh(referral)
    return referral


def delete_referral(db: Session, referral_id: int) -> bool:
    """移入回收站（软删除）；彻底删除在「回收站」里单独提供。"""
    referral = db.get(Referral, referral_id)
    if referral is None or trash.is_deleted(referral):
        return False
    trash.soft_delete(db, "referral", referral)
    db.commit()
    return True


def referral_stats(db: Session) -> ReferralStatsOut:
    """转化率：converted（派生）/ 有效内推总数（非 closed/invalid）。"""
    rows = (
        db.query(Referral)
        .filter(trash.live_only(Referral), Referral.status.in_(_VALID_REFERRAL_STATUSES))
        .all()
    )
    converted = sum(1 for row in rows if _is_converted(db, row))
    total = len(rows)
    return ReferralStatsOut(total=total, converted=converted, rate=rate(converted, total))


def referral_status_counts(db: Session) -> list[dict]:
    """各内推状态的条数，按 ``REFERRAL_STATUSES`` 顺序（含计数为 0 的分支）。

    **只回 ``key``/``count``、不带中文标签**：内推状态的展示名归前端
    （``frontend/src/types/referral.ts`` 的 ``REFERRAL_STATUS_LABELS``），后端再写一份
    就是同一件事的两份定义、迟早漂移。
    """
    counts = {status: 0 for status in REFERRAL_STATUSES}
    rows = db.query(Referral.status).filter(trash.live_only(Referral)).all()
    for (status,) in rows:
        if status in counts:
            counts[status] += 1
    return [{"key": status, "count": counts[status]} for status in REFERRAL_STATUSES]


__all__ = [
    "MAX_REFERRAL_LIST",
    "REFERRAL_IMAGES_DIRNAME",
    "create_referral",
    "delete_referral",
    "list_referrals",
    "referral_images_dir",
    "referral_or_none",
    "referral_out",
    "referral_stats",
    "referral_status_counts",
    "save_referral_image",
    "update_referral",
]
