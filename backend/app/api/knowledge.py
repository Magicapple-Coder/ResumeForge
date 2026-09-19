"""知识库接口：条目的增删改查与分类建议。"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas.knowledge import KNOWLEDGE_CATEGORIES, KnowledgeCreate, KnowledgeOut, KnowledgeUpdate
from ..services.knowledge_service import (
    create_knowledge,
    delete_knowledge,
    knowledge_categories,
    knowledge_or_none,
    list_knowledge,
    update_knowledge,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("", response_model=list[KnowledgeOut])
def read_knowledge(
    q: str = Query(default=""),
    category: str = Query(default=""),
    db: Session = Depends(get_db),
):
    return list_knowledge(db, q=q, category=category)


# 字面量段 /categories 必须排在 /{knowledge_id} 之前，否则会被参数段吞掉。
@router.get("/categories", response_model=list[str])
def read_categories(db: Session = Depends(get_db)):
    """候选分类：内置分类在前，用户已用过的自定义分类在后。"""
    used = knowledge_categories(db)
    return list(dict.fromkeys([*KNOWLEDGE_CATEGORIES, *used]))


@router.post("", response_model=KnowledgeOut, status_code=201)
def create_knowledge_entry(payload: KnowledgeCreate, db: Session = Depends(get_db)):
    return create_knowledge(db, payload)


@router.get("/{knowledge_id}", response_model=KnowledgeOut)
def read_knowledge_entry(knowledge_id: int, db: Session = Depends(get_db)):
    entry = knowledge_or_none(db, knowledge_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="知识库条目不存在或已被删除")
    return entry


@router.put("/{knowledge_id}", response_model=KnowledgeOut)
def save_knowledge_entry(
    knowledge_id: int, payload: KnowledgeUpdate, db: Session = Depends(get_db)
):
    entry = knowledge_or_none(db, knowledge_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="知识库条目不存在或已被删除")
    return update_knowledge(db, entry, payload)


@router.delete("/{knowledge_id}", status_code=204)
def remove_knowledge_entry(knowledge_id: int, db: Session = Depends(get_db)):
    if not delete_knowledge(db, knowledge_id):
        raise HTTPException(status_code=404, detail="知识库条目不存在或已被删除")
