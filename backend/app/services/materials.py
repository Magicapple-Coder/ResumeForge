"""资料箱：零散资料的持久化与检索。

资料可以是文字、链接、附件（图片缩略图或本机提取出的文档文字）。附件的原始文件
不落盘、不外发，与助手附件的取舍一致；照片只保存受限的 data URL。
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models.material import Material
from ..schemas.material import MaterialCreate, MaterialUpdate

logger = logging.getLogger(__name__)

# 助手读取单条资料时的返回上限（工具结果）。
MAX_MATERIAL_TOOL_CHARS = 6_000


def list_materials(db: Session, *, keyword: str = "", category: str = "") -> list[Material]:
    query = db.query(Material)
    if category.strip():
        query = query.filter(Material.category == category.strip())
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                Material.title.like(like),
                Material.content.like(like),
                Material.note.like(like),
                Material.url.like(like),
                Material.category.like(like),
            )
        )
    return query.order_by(Material.updated_at.desc(), Material.id.desc()).all()


def material_or_none(db: Session, material_id: int) -> Material | None:
    return db.get(Material, material_id)


def create_material(db: Session, payload: MaterialCreate) -> Material:
    material = Material(**payload.model_dump())
    db.add(material)
    db.commit()
    db.refresh(material)
    logger.info("已新增资料 id=%s category=%s 附件=%s", material.id, material.category, len(material.files))
    return material


def update_material(db: Session, material: Material, payload: MaterialUpdate) -> Material:
    for field, value in payload.model_dump().items():
        setattr(material, field, value)
    db.commit()
    db.refresh(material)
    return material


def delete_material(db: Session, material_id: int) -> bool:
    material = db.get(Material, material_id)
    if material is None:
        return False
    db.delete(material)
    db.commit()
    return True


def material_brief(material: Material) -> dict:
    """列表视图：不含附件正文，避免助手上下文被零散资料占满。"""
    return {
        "id": material.id,
        "标题": material.title,
        "分类": material.category,
        "链接": material.url,
        "备注": material.note,
        "正文预览": material.content[:200],
        "附件": [str(item.get("name", "")) for item in material.files if isinstance(item, dict)],
        "更新时间": material.updated_at.isoformat() if material.updated_at else None,
    }


def material_detail_text(material: Material, max_chars: int = MAX_MATERIAL_TOOL_CHARS) -> str:
    """详情视图：正文 + 附件文字，按预算截断。"""
    parts = [f"标题：{material.title}", f"分类：{material.category}"]
    if material.url:
        parts.append(f"链接：{material.url}")
    if material.note:
        parts.append(f"备注：{material.note}")
    if material.content:
        parts.append(f"正文：\n{material.content}")
    for item in material.files:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "附件"))
        text = str(item.get("text", "") or "").strip()
        has_image = bool(item.get("data_url"))
        if text:
            parts.append(f"[附件 {name}]\n{text}")
        elif has_image:
            parts.append(f"[附件 {name}]（图片，正文未提取）")
        else:
            parts.append(f"[附件 {name}]（无可用文字）")
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        text = f"{text[:max_chars].rstrip()}…"
    return text


def material_categories(db: Session) -> list[str]:
    """已使用过的分类，供助手与界面给出建议。"""
    rows = db.query(Material.category).distinct().all()
    return sorted({row[0] for row in rows if row[0]})


def dump_files(files: list[dict]) -> str:
    """调试/日志用途的紧凑表示，不泄露正文。"""
    return json.dumps(
        [{"name": item.get("name", ""), "size": item.get("size_bytes", 0)} for item in files],
        ensure_ascii=False,
    )


__all__ = [
    "MAX_MATERIAL_TOOL_CHARS",
    "create_material",
    "delete_material",
    "list_materials",
    "material_brief",
    "material_categories",
    "material_detail_text",
    "material_or_none",
    "update_material",
]
