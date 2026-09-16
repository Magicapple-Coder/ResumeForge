"""求职助手会话的数据库读写。"""
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from ..models.assistant import ChatConversation, ChatMessage
from ..models.profile import utcnow
from ..schemas.assistant import (
    ChatConversationBrief,
    ChatConversationCreate,
    ChatConversationDetail,
    ChatConversationForkRequest,
    ChatConversationUpdate,
)

DEFAULT_TITLE = "新对话"
WELCOME_TITLE = "开始使用求职助手"
_WELCOME_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "assistant_welcome.md"


def welcome_message() -> str:
    """内置引导对话的正文。

    读文件而不是写死在代码里：引导内容会随功能变化，和系统提示一样应该可以单独
    修改、评审；文件缺失时退回一句最小说明，不让"没有引导"变成接口 500。
    """
    try:
        return _WELCOME_PROMPT_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return "你好，我是简历通的求职助手。可以在下方输入框直接提问，或先关联岗位、简历和资料。"


def conversation_or_404(db: Session, conversation_id: int) -> ChatConversation:
    conversation = db.get(ChatConversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在或已被删除")
    return conversation


def _message_counts(db: Session, conversation_ids: list[int]) -> dict[int, int]:
    """一次查询取回所有会话的消息条数，避免每条会话各查一次。"""
    if not conversation_ids:
        return {}
    rows = (
        db.query(ChatMessage.conversation_id, func.count(ChatMessage.id))
        .filter(ChatMessage.conversation_id.in_(conversation_ids))
        .group_by(ChatMessage.conversation_id)
        .all()
    )
    return {conversation_id: count for conversation_id, count in rows}


def _to_brief(conversation: ChatConversation, message_count: int = 0) -> ChatConversationBrief:
    return ChatConversationBrief(
        id=conversation.id,
        title=conversation.title,
        pinned=conversation.pinned,
        favorite=conversation.favorite,
        archived=conversation.archived,
        group_name=conversation.group_name,
        message_count=message_count,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def create_conversation(payload: ChatConversationCreate, db: Session) -> ChatConversationBrief:
    title = " ".join(payload.title.split()) or DEFAULT_TITLE
    conversation = ChatConversation(title=title[:120])
    db.add(conversation)
    db.flush()
    message_count = 0
    if payload.welcome:
        conversation.title = (title[:120] if title != DEFAULT_TITLE else WELCOME_TITLE)
        db.add(
            ChatMessage(
                conversation_id=conversation.id,
                role="assistant",
                content=welcome_message(),
                status="complete",
            )
        )
        message_count = 1
    db.commit()
    db.refresh(conversation)
    return _to_brief(conversation, message_count)


def list_conversations(limit: int, db: Session) -> list[ChatConversationBrief]:
    """按置顶、更新时间排序返回会话（含已归档，由前端按筛选展示）。"""
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
    counts = _message_counts(db, [row.id for row in rows])
    return [_to_brief(row, counts.get(row.id, 0)) for row in rows]


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
    if payload.archived is not None:
        conversation.archived = payload.archived
        # 归档时顺手取消置顶：置顶的归档会话在侧栏顶部会显得很矛盾。
        if payload.archived:
            conversation.pinned = False
    if payload.group_name is not None:
        conversation.group_name = payload.group_name
    # 标记变化不改变会话的时间排序，取消置顶后仍回到原位置。
    if payload.title is not None:
        conversation.updated_at = utcnow()
    db.commit()
    db.refresh(conversation)
    count = _message_counts(db, [conversation.id]).get(conversation.id, 0)
    return _to_brief(conversation, count)


def fork_conversation(
    conversation_id: int, payload: ChatConversationForkRequest, db: Session
) -> ChatConversationDetail:
    """「在新对话中继续」：把原会话最近若干条消息复制成一段新会话。

    只复制文本：附件（尤其是图片 data URL）原样搬运会让同一份大文件在库里存两份，
    所以只在正文后附上文件名的提示，需要时用户可以重新上传。
    """
    source = conversation_or_404(db, conversation_id)
    rows = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.status == "complete",
            ChatMessage.role.in_(("user", "assistant")),
        )
        .order_by(ChatMessage.id.desc())
        .limit(payload.message_limit)
        .all()
    )
    title = " ".join(payload.title.split())[:120] or f"{source.title}（续）"[:120]
    conversation = ChatConversation(title=title)
    db.add(conversation)
    db.flush()
    for row in reversed(rows):
        content = row.content
        attachment_names = [
            str(item.get("name", "")).strip()
            for item in (row.attachments or [])
            if isinstance(item, dict) and str(item.get("name", "")).strip()
        ]
        if attachment_names:
            content = f"{content}\n\n（原对话附件：{'、'.join(attachment_names)}）".strip()
        db.add(
            ChatMessage(
                conversation_id=conversation.id,
                role=row.role,
                content=content,
                status="complete",
                model=row.model,
            )
        )
    db.commit()
    db.refresh(conversation)
    return read_conversation(conversation.id, db)


def delete_conversation(conversation_id: int, db: Session) -> None:
    conversation = conversation_or_404(db, conversation_id)
    db.delete(conversation)
    db.commit()


__all__ = [
    "DEFAULT_TITLE",
    "WELCOME_TITLE",
    "conversation_or_404",
    "create_conversation",
    "fork_conversation",
    "list_conversations",
    "read_conversation",
    "update_conversation",
    "welcome_message",
]
