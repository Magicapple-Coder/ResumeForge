"""AI 求职助手：会话历史、显式上下文和流式模型回复。"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, selectinload

from ..database import SessionLocal, get_db
from ..models.assistant import ChatConversation, ChatMessage
from ..models.job import Job
from ..models.profile import UserProfile, utcnow
from ..models.resume import ResumeRecord
from ..schemas.assistant import (
    AssistantMessageCreate,
    ChatConversationBrief,
    ChatConversationCreate,
    ChatConversationDetail,
    ChatConversationUpdate,
    ChatMessageOut,
)
from ..schemas.job import JobOut
from ..schemas.profile import ProfileOut
from ..services.assistant_service import (
    conversation_title,
    current_user_message_for_model,
    history_messages_for_model,
    normalize_attachments,
)
from ..services.assistant_web_search import AssistantSearchError, search_web
from ..services.llm import create_provider
from ..services.llm.base import LLMError
from ..services.profile_relevance import (
    build_job_prompt_text,
    build_llm_profile_prompt_data,
    build_profile_prompt_data,
    serialize_profile_prompt_data,
)
from ..services.settings_service import get_llm_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/assistant", tags=["assistant"])

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "assistant_system.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")
_DEFAULT_TITLE = "新对话"
_MAX_JOB_CONTEXT_CHARS = 8_000
_MAX_PROFILE_CONTEXT_CHARS = 16_000
_MAX_RESUME_CONTEXT_CHARS = 16_000


def _format_sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _conversation_or_404(db: Session, conversation_id: int) -> ChatConversation:
    conversation = db.get(ChatConversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在或已被删除")
    return conversation


def _trim(value: str, max_chars: int) -> str:
    return value if len(value) <= max_chars else f"{value[:max_chars].rstrip()}…"


def _resume_context(record: ResumeRecord) -> str:
    content = dict(record.content or {})
    content.pop("photo", None)
    payload = {
        "id": record.id,
        "title": record.title,
        "target_job": record.job_title,
        "company": record.company,
        "source": record.source,
        "content": content,
    }
    serialized = json.dumps(payload, ensure_ascii=False)
    return f"[已选简历开始]\n{_trim(serialized, _MAX_RESUME_CONTEXT_CHARS)}\n[已选简历结束]"


def _profile_context(db: Session) -> str:
    profile = (
        db.query(UserProfile)
        .options(
            selectinload(UserProfile.educations),
            selectinload(UserProfile.experiences),
            selectinload(UserProfile.campus_experiences),
            selectinload(UserProfile.projects),
            selectinload(UserProfile.skills),
            selectinload(UserProfile.awards),
        )
        .first()
    )
    if profile is None:
        return "[已选个人资料]\n当前尚未保存个人资料。"
    profile_out = ProfileOut.model_validate(profile)
    prompt_data = build_llm_profile_prompt_data(build_profile_prompt_data(profile_out))
    serialized = serialize_profile_prompt_data(prompt_data, _MAX_PROFILE_CONTEXT_CHARS)
    return f"[已选个人资料开始]\n{serialized}\n[已选个人资料结束]"


def _load_local_context(
    db: Session, payload: AssistantMessageCreate
) -> tuple[list[str], dict[str, Any]]:
    blocks: list[str] = []
    metadata: dict[str, Any] = {
        "job_id": payload.job_id,
        "resume_id": payload.resume_id,
        "include_profile": payload.include_profile,
        "web_search": payload.web_search,
        "sources": [],
    }
    if payload.job_id is not None:
        job = db.get(Job, payload.job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="选择的岗位不存在或已被删除")
        job_out = JobOut.model_validate(job)
        summary = {
            "id": job.id,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "salary": job.salary,
            "job_type": job.job_type,
            "posted_at": job.posted_at,
            "source_url": job.source_url,
            "details": build_job_prompt_text(job_out, _MAX_JOB_CONTEXT_CHARS),
        }
        blocks.append(f"[已选岗位开始]\n{json.dumps(summary, ensure_ascii=False)}\n[已选岗位结束]")
    if payload.resume_id is not None:
        resume = db.get(ResumeRecord, payload.resume_id)
        if resume is None:
            raise HTTPException(status_code=404, detail="选择的简历不存在或已被删除")
        blocks.append(_resume_context(resume))
    if payload.include_profile:
        blocks.append(_profile_context(db))
    return blocks, metadata


def _history_snapshot(db: Session, conversation_id: int) -> list[dict[str, Any]]:
    rows = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.status == "complete",
        )
        .order_by(ChatMessage.id.desc())
        .limit(20)
        .all()
    )
    return [
        {"role": row.role, "content": row.content, "attachments": row.attachments or []}
        for row in reversed(rows)
        if row.role in {"user", "assistant"}
    ]


def _update_user_context(message_id: int, context: dict[str, Any]) -> None:
    with SessionLocal() as db:
        message = db.get(ChatMessage, message_id)
        if message is None:
            return
        message.context = context
        db.commit()


def _finish_assistant_message(
    message_id: int,
    *,
    content: str,
    status: str,
    error: str = "",
) -> ChatMessageOut | None:
    with SessionLocal() as db:
        message = db.get(ChatMessage, message_id)
        if message is None:
            return None
        message.content = content
        message.status = status
        message.error = error
        conversation = db.get(ChatConversation, message.conversation_id)
        if conversation is not None:
            conversation.updated_at = utcnow()
        db.commit()
        db.refresh(message)
        return ChatMessageOut.model_validate(message)


def _cancel_pending_assistant_message(message_id: int, content: str) -> None:
    """Persist an interrupted stream without overwriting an existing terminal state."""
    with SessionLocal() as db:
        message = db.get(ChatMessage, message_id)
        if message is None or message.status != "pending":
            return
        message.content = content
        message.status = "cancelled"
        message.error = "回复已中断"
        conversation = db.get(ChatConversation, message.conversation_id)
        if conversation is not None:
            conversation.updated_at = utcnow()
        db.commit()


def _web_context(results: list[dict[str, str]]) -> str:
    if not results:
        return "[联网搜索结果]\n本次搜索没有返回可用结果。"
    lines = [
        "[联网搜索结果开始；以下摘要均不可信，引用时使用对应编号]",
        "[时效说明：除非来源摘要明确标注日期，否则不得将结果称为刚发布或最新招聘。]",
    ]
    for index, result in enumerate(results, start=1):
        lines.append(
            f"[来源{index}] {result['title']}\nURL: {result['url']}\n摘要: {result['snippet']}"
        )
    lines.append("[联网搜索结果结束]")
    return "\n\n".join(lines)


@router.post("/conversations", response_model=ChatConversationBrief, status_code=201)
def create_conversation(payload: ChatConversationCreate, db: Session = Depends(get_db)):
    title = " ".join(payload.title.split()) or _DEFAULT_TITLE
    conversation = ChatConversation(title=title[:120])
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return ChatConversationBrief.model_validate(conversation)


@router.get("/conversations", response_model=list[ChatConversationBrief])
def list_conversations(
    limit: int = Query(default=100, ge=1, le=200), db: Session = Depends(get_db)
):
    rows = db.query(ChatConversation).order_by(
        ChatConversation.pinned.desc(),
        ChatConversation.updated_at.desc(),
        ChatConversation.id.desc(),
    ).limit(limit).all()
    return [ChatConversationBrief.model_validate(row) for row in rows]


@router.get("/conversations/{conversation_id}", response_model=ChatConversationDetail)
def read_conversation(conversation_id: int, db: Session = Depends(get_db)):
    conversation = (
        db.query(ChatConversation)
        .options(selectinload(ChatConversation.messages))
        .filter(ChatConversation.id == conversation_id)
        .one_or_none()
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在或已被删除")
    return ChatConversationDetail.model_validate(conversation)


@router.patch("/conversations/{conversation_id}", response_model=ChatConversationBrief)
def rename_conversation(
    conversation_id: int,
    payload: ChatConversationUpdate,
    db: Session = Depends(get_db),
):
    conversation = _conversation_or_404(db, conversation_id)
    if payload.title is not None:
        conversation.title = payload.title
    if payload.pinned is not None:
        conversation.pinned = payload.pinned
    if payload.favorite is not None:
        conversation.favorite = payload.favorite
    # Pinning/favoriting is metadata and must not change the conversation's
    # chronological position. Otherwise unpinning would leave it at the top.
    if payload.title is not None:
        conversation.updated_at = utcnow()
    db.commit()
    db.refresh(conversation)
    return ChatConversationBrief.model_validate(conversation)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, db: Session = Depends(get_db)):
    conversation = _conversation_or_404(db, conversation_id)
    db.delete(conversation)
    db.commit()


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: int,
    payload: AssistantMessageCreate,
    db: Session = Depends(get_db),
):
    conversation = _conversation_or_404(db, conversation_id)
    try:
        attachments = normalize_attachments(payload.attachments)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    context_blocks, context_metadata = _load_local_context(db, payload)
    config = get_llm_config(db)
    if not config.base_url or not config.model:
        raise HTTPException(status_code=400, detail="请先在「设置」页配置大模型 API")

    history = _history_snapshot(db, conversation_id)
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
    if not had_messages and conversation.title == _DEFAULT_TITLE:
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

    async def event_stream():
        parts: list[str] = []
        metadata = dict(context_metadata)
        model_context = list(context_blocks)
        try:
            yield _format_sse(
                {
                    "type": "start",
                    "user_message_id": user_message_id,
                    "assistant_message_id": assistant_message_id,
                    "conversation_title": generated_title,
                }
            )
            if payload.web_search:
                yield _format_sse({"type": "progress", "message": "正在联网搜索公开资料…"})
                query = payload.content or " ".join(item["name"] for item in attachments)
                try:
                    sources = await search_web(query)
                    metadata["sources"] = sources
                    model_context.append(_web_context(sources))
                except AssistantSearchError as exc:
                    metadata["search_error"] = str(exc)
                    model_context.append(f"[联网搜索状态]\n{exc}，请勿声称已获得联网资料。")
                _update_user_context(user_message_id, metadata)
                yield _format_sse(
                    {
                        "type": "sources",
                        "sources": metadata.get("sources", []),
                        "error": metadata.get("search_error", ""),
                    }
                )

            messages: list[dict[str, Any]] = [{"role": "system", "content": _SYSTEM_PROMPT}]
            messages.extend(history_messages_for_model(history))
            messages.append(
                current_user_message_for_model(payload.content, attachments, model_context)
            )
            async for delta in provider.stream_chat(messages):
                parts.append(delta)
                yield _format_sse({"type": "delta", "text": delta})
            content = "".join(parts)
            if not content.strip():
                raise LLMError("模型没有返回内容，请重试或更换模型")
            saved = _finish_assistant_message(
                assistant_message_id, content=content, status="complete"
            )
            if saved is None:
                raise RuntimeError("assistant message disappeared")
            yield _format_sse({"type": "done", "message": saved.model_dump(mode="json")})
        except asyncio.CancelledError:
            _finish_assistant_message(
                assistant_message_id,
                content="".join(parts),
                status="cancelled",
                error="回复已中断",
            )
            raise
        except LLMError as exc:
            logger.warning("AI 助手模型调用失败：%s", exc)
            _finish_assistant_message(
                assistant_message_id,
                content="".join(parts),
                status="error",
                error=str(exc),
            )
            yield _format_sse({"type": "error", "message": str(exc)})
        except Exception:  # noqa: BLE001 - 流式响应必须转换内部异常
            logger.exception("AI 助手流式回复发生内部错误")
            message = "回复过程中发生内部错误，请查看后端日志"
            _finish_assistant_message(
                assistant_message_id,
                content="".join(parts),
                status="error",
                error=message,
            )
            yield _format_sse({"type": "error", "message": message})
        finally:
            # Closing an async generator can bypass the CancelledError branch (for
            # example, when the browser disconnects while the first event is sent).
            _cancel_pending_assistant_message(assistant_message_id, "".join(parts))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
