"""求职助手会话的数据库读写。"""

from fastapi import HTTPException
from sqlalchemy.orm import Session, selectinload

from ..models.assistant import ChatConversation
from ..models.profile import utcnow
from ..schemas.assistant import (
    ChatConversationBrief,
    ChatConversationCreate,
    ChatConversationDetail,
    ChatConversationUpdate,
)

DEFAULT_TITLE = "新对话"


def conversation_or_404(db: Session, conversation_id: int) -> ChatConversation:
    conversation = db.get(ChatConversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在或已被删除")
    return conversation


def create_conversation(payload: ChatConversationCreate, db: Session) -> ChatConversationBrief:
    title = " ".join(payload.title.split()) or DEFAULT_TITLE
    conversation = ChatConversation(title=title[:120])
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return ChatConversationBrief.model_validate(conversation)


def list_conversations(limit: int, db: Session) -> list[ChatConversationBrief]:
    rows = (
        db.query(ChatConversation)
        .order_by(
            ChatConversation.pinned.desc(),
            ChatConversation.updated_at.desc(),
            ChatConversation.id.desc(),
        )
        .limit(limit)
        .all()
    )
    return [ChatConversationBrief.model_validate(row) for row in rows]


def read_conversation(conversation_id: int, db: Session) -> ChatConversationDetail:
    conversation = (
        db.query(ChatConversation)
        .options(selectinload(ChatConversation.messages))
        .filter(ChatConversation.id == conversation_id)
        .one_or_none()
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在或已被删除")
    return ChatConversationDetail.model_validate(conversation)


def update_conversation(
    conversation_id: int, payload: ChatConversationUpdate, db: Session
) -> ChatConversationBrief:
    conversation = conversation_or_404(db, conversation_id)
    if payload.title is not None:
        conversation.title = payload.title
    if payload.pinned is not None:
        conversation.pinned = payload.pinned
    if payload.favorite is not None:
        conversation.favorite = payload.favorite
    # 标记变化不改变会话的时间排序，取消置顶后仍回到原位置。
    if payload.title is not None:
        conversation.updated_at = utcnow()
    db.commit()
    db.refresh(conversation)
    return ChatConversationBrief.model_validate(conversation)


def delete_conversation(conversation_id: int, db: Session) -> None:
    conversation = conversation_or_404(db, conversation_id)
    db.delete(conversation)
    db.commit()


__all__ = [
    "DEFAULT_TITLE",
    "conversation_or_404",
    "create_conversation",
    "list_conversations",
    "read_conversation",
    "update_conversation",
    "delete_conversation",
]
