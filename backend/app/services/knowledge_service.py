"""知识库：条目的持久化、检索与软删除。

检索口径集中在 ``list_knowledge``：标题/正文按关键词命中（``q``）、分类精确筛选
（``category``）、只取未删除的行（``live_only``）、按 ``updated_at`` 倒序。删除一律走
``trash.soft_delete`` 进回收站（``knowledge_entry`` 已在 ``TRASH_SPECS`` 注册）。
"""
from __future__ import annotations

import logging

from sqlalchemy import or_
from sqlalchemy.orm import Session

from . import trash
from ..models.knowledge_entry import KnowledgeEntry
from ..schemas.knowledge import KnowledgeCreate, KnowledgeUpdate

logger = logging.getLogger(__name__)


def list_knowledge(db: Session, *, q: str = "", category: str = "") -> list[KnowledgeEntry]:
    """列表：按分类/关键词筛选，只看未删除条目，按更新时间倒序。"""
    query = db.query(KnowledgeEntry).filter(trash.live_only(KnowledgeEntry))
    if category.strip():
        query = query.filter(KnowledgeEntry.category == category.strip())
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                KnowledgeEntry.title.like(like),
                KnowledgeEntry.content.like(like),
            )
        )
    return query.order_by(KnowledgeEntry.updated_at.desc(), KnowledgeEntry.id.desc()).all()


def knowledge_or_none(db: Session, knowledge_id: int) -> KnowledgeEntry | None:
    """取一条条目；**已在回收站里的当作不存在**（与资料箱 ``material_or_none`` 同语义）。"""
    entry = db.get(KnowledgeEntry, knowledge_id)
    if entry is None or trash.is_deleted(entry):
        return None
    return entry


def create_knowledge(db: Session, payload: KnowledgeCreate) -> KnowledgeEntry:
    """新增一条知识库条目。"""
    entry = KnowledgeEntry(**payload.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    logger.info(
        "已新增知识库条目 id=%s category=%s 标签=%s",
        entry.id,
        entry.category,
        len(entry.tags),
    )
    return entry


def update_knowledge(
    db: Session, entry: KnowledgeEntry, payload: KnowledgeUpdate
) -> KnowledgeEntry:
    for field, value in payload.model_dump().items():
        setattr(entry, field, value)
    db.commit()
    db.refresh(entry)
    return entry


def delete_knowledge(db: Session, knowledge_id: int) -> bool:
    """移入回收站（软删除）；彻底删除在「回收站」里单独提供。"""
    entry = db.get(KnowledgeEntry, knowledge_id)
    if entry is None or trash.is_deleted(entry):
        return False
    trash.soft_delete(db, "knowledge_entry", entry)
    db.commit()
    return True


def knowledge_categories(db: Session) -> list[str]:
    """已使用过的分类，供界面与接口给出建议。"""
    rows = db.query(KnowledgeEntry.category).distinct().all()
    return sorted({row[0] for row in rows if row[0]})


__all__ = [
    "create_knowledge",
    "delete_knowledge",
    "knowledge_categories",
    "knowledge_or_none",
    "list_knowledge",
    "update_knowledge",
]

