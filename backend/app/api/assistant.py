"""AI 求职助手：会话历史、显式上下文和流式模型回复。"""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.assistant import ChatMessage
from ..models.profile import utcnow
from ..schemas.assistant import (
    AssistantMessageCreate,
    ChatConversationBrief,
    ChatConversationCreate,
    ChatConversationDetail,
    ChatConversationUpdate,
)
from ..services.assistant_service import (
    conversation_title,
    normalize_attachments,
)
from ..services.assistant_web_search import search_web
from ..services.llm import create_provider
from ..services.settings_service import get_llm_config
from .assistant_context import load_local_context
from .assistant_conversations import (
    DEFAULT_TITLE,
    conversation_or_404,
    create_conversation as create_conversation_record,
    delete_conversation as delete_conversation_record,
    list_conversations as list_conversation_records,
    read_conversation as read_conversation_record,
    update_conversation as update_conversation_record,
)
from .assistant_stream import history_snapshot, stream_message_events

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/assistant", tags=["assistant"])

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "assistant_system.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")


@router.post("/conversations", response_model=ChatConversationBrief, status_code=201)
def create_conversation(payload: ChatConversationCreate, db: Session = Depends(get_db)):
    return create_conversation_record(payload, db)


@router.get("/conversations", response_model=list[ChatConversationBrief])
def list_conversations(
    limit: int = Query(default=100, ge=1, le=200), db: Session = Depends(get_db)
):
    return list_conversation_records(limit, db)


@router.get("/conversations/{conversation_id}", response_model=ChatConversationDetail)
def read_conversation(conversation_id: int, db: Session = Depends(get_db)):
    return read_conversation_record(conversation_id, db)


@router.patch("/conversations/{conversation_id}", response_model=ChatConversationBrief)
def rename_conversation(
    conversation_id: int,
    payload: ChatConversationUpdate,
    db: Session = Depends(get_db),
):
    return update_conversation_record(conversation_id, payload, db)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, db: Session = Depends(get_db)):
    delete_conversation_record(conversation_id, db)


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: int,
    payload: AssistantMessageCreate,
    db: Session = Depends(get_db),
):
    conversation = conversation_or_404(db, conversation_id)
    try:
        attachments = normalize_attachments(payload.attachments)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        context_blocks, context_metadata = load_local_context(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    config = get_llm_config(db)
    if not config.base_url or not config.model:
        raise HTTPException(status_code=400, detail="请先在「设置」页配置大模型 API")

    history = history_snapshot(db, conversation_id)
    had_messages = bool(history)
    user_message = ChatMessage(
        conversation_id=conversation_id,
        role="user",
        content=payload.content,
        attachments=attachments,
        context=context_metadata,
        status="complete",
    )
    assistant_message = ChatMessage(
        conversation_id=conversation_id,
        role="assistant",
        status="pending",
        model=config.model,
    )
    db.add_all([user_message, assistant_message])
    if not had_messages and conversation.title == DEFAULT_TITLE:
        conversation.title = conversation_title(payload.content, attachments)
    conversation.updated_at = utcnow()
    db.commit()
    db.refresh(user_message)
    db.refresh(assistant_message)
    user_message_id = user_message.id
    assistant_message_id = assistant_message.id
    generated_title = conversation.title
    provider = create_provider(config)
    db.close()

    return StreamingResponse(
        stream_message_events(
            payload=payload,
            attachments=attachments,
            provider=provider,
            history=history,
            context_blocks=context_blocks,
            context_metadata=context_metadata,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            generated_title=generated_title,
            system_prompt=_SYSTEM_PROMPT,
            search_web_fn=search_web,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
