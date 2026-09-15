"""求职助手历史快照、SSE 事件和模型流编排。"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models.assistant import ChatConversation, ChatMessage
from ..models.profile import utcnow
from ..schemas.assistant import AssistantMessageCreate, ChatMessageOut
from ..services.assistant_service import (
    current_user_message_for_model,
    history_messages_for_model,
)
from ..services.assistant_tools import execute_tool, tool_definitions
from ..services.assistant_web_search import AssistantSearchError
from ..services.llm.base import BaseLLMProvider, LLMError
from .assistant_context import web_context

logger = logging.getLogger(__name__)

# 一次回复里最多允许几轮工具调用；防止模型在两个工具之间来回打转。
MAX_TOOL_ROUNDS = 5


def _parse_tool_arguments(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"工具参数不是合法 JSON：{raw[:120]}") from exc
    if not isinstance(value, dict):
        raise ValueError("工具参数必须是 JSON 对象")
    return value


def _run_tool_call(call: dict[str, Any]) -> dict[str, Any]:
    """执行一次工具调用。

    任何失败都转成结构化的"工具结果"回给模型，而不是抛出去中断整轮对话——模型
    往往能据此换个参数重试，或者在回答里如实说明没做到。
    """
    function = call.get("function") or {}
    name = function.get("name") or ""
    record: dict[str, Any] = {
        "name": name,
        "arguments": {},
        "summary": "",
        "link": "",
        "ok": True,
        "error": "",
        "result_text": "",
    }
    try:
        arguments = _parse_tool_arguments(function.get("arguments") or "")
        record["arguments"] = arguments
        # 和本模块其它写回一样自开会话：不把连接跨整个流持有。
        with SessionLocal() as db:
            result = execute_tool(db, name, arguments)
        record["summary"] = result.summary
        record["link"] = result.link
        record["result_text"] = result.text
    except Exception as exc:  # noqa: BLE001 - 工具失败不能拖垮整轮回复
        record["ok"] = False
        record["error"] = str(exc)
        record["result_text"] = f"工具执行失败：{exc}"
        logger.warning("助手工具 %s 执行失败：%s", name, exc)
    return record


def format_sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def history_snapshot(db: Session, conversation_id: int) -> list[dict[str, Any]]:
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


def update_message_context(message_id: int, context: dict[str, Any]) -> None:
    with SessionLocal() as db:
        message = db.get(ChatMessage, message_id)
        if message is None:
            return
        message.context = context
        db.commit()


def finish_assistant_message(
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


def cancel_pending_assistant_message(message_id: int, content: str) -> None:
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


async def stream_message_events(
    *,
    payload: AssistantMessageCreate,
    attachments: list[dict[str, Any]],
    provider: BaseLLMProvider,
    history: list[dict[str, Any]],
    context_blocks: list[str],
    context_metadata: dict[str, Any],
    user_message_id: int,
    assistant_message_id: int,
    generated_title: str,
    system_prompt: str,
    search_web_fn: Callable[[str], Awaitable[list[dict[str, str]]]],
) -> AsyncIterator[str]:
    parts: list[str] = []
    metadata = dict(context_metadata)
    model_context = list(context_blocks)
    try:
        yield format_sse(
            {
                "type": "start",
                "user_message_id": user_message_id,
                "assistant_message_id": assistant_message_id,
                "conversation_title": generated_title,
            }
        )
        if payload.web_search:
            yield format_sse({"type": "progress", "message": "正在联网搜索公开资料…"})
            query = payload.content or " ".join(item["name"] for item in attachments)
            try:
                sources = await search_web_fn(query)
                metadata["sources"] = sources
                model_context.append(web_context(sources))
            except AssistantSearchError as exc:
                metadata["search_error"] = str(exc)
                model_context.append(f"[联网搜索状态]\n{exc}，请勿声称已获得联网资料。")
            update_message_context(user_message_id, metadata)
            yield format_sse(
                {
                    "type": "sources",
                    "sources": metadata.get("sources", []),
                    "error": metadata.get("search_error", ""),
                }
            )

        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        messages.extend(history_messages_for_model(history))
        messages.append(current_user_message_for_model(payload.content, attachments, model_context))

        tools = tool_definitions()
        tool_records: list[dict[str, Any]] = []
        for _round in range(MAX_TOOL_ROUNDS):
            calls: list[dict[str, Any]] = []
            async for delta in provider.stream_chat_events(messages, tools):
                if delta.text:
                    parts.append(delta.text)
                    yield format_sse({"type": "delta", "text": delta.text})
                if delta.tool_calls:
                    calls.extend(delta.tool_calls)
            if not calls:
                break

            # 把助手的这次调用原样回填进消息，模型才能把结果对上号。
            messages.append({"role": "assistant", "content": None, "tool_calls": calls})
            for call in calls:
                record = _run_tool_call(call)
                tool_records.append(record)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") or "",
                        "content": record["result_text"],
                    }
                )
                yield format_sse(
                    {
                        "type": "tool",
                        "name": record["name"],
                        "arguments": record["arguments"],
                        "summary": record["summary"],
                        "link": record["link"],
                        "ok": record["ok"],
                        "error": record["error"],
                    }
                )
            # 工具记录属于**助手这条消息**：它描述的是助手做了什么，历史回看时挂在
            # 助手回复下最自然（来源则属于用户那条消息，见上面的联网分支）。
            update_message_context(assistant_message_id, {"tool_calls": tool_records})
        else:
            # 到达轮次上限：停止继续调用工具，让用户看到已经做了什么。
            parts.append(
                f"\n\n（已经连续执行了 {MAX_TOOL_ROUNDS} 轮工具调用，为避免失控先停在这里，"
                "你可以继续追问。）"
            )

        content = "".join(parts)
        if not content.strip():
            if tool_records:
                # 只调了工具、没输出正文：把做过的事说清楚，而不是报错。
                content = "已完成：\n" + "\n".join(
                    f"- {record['summary'] or record['name']}" for record in tool_records
                )
            else:
                raise LLMError("模型没有返回内容，请重试或更换模型")
        saved = finish_assistant_message(assistant_message_id, content=content, status="complete")
        if saved is None:
            raise RuntimeError("assistant message disappeared")
        yield format_sse({"type": "done", "message": saved.model_dump(mode="json")})
    except asyncio.CancelledError:
        finish_assistant_message(
            assistant_message_id,
            content="".join(parts),
            status="cancelled",
            error="回复已中断",
        )
        raise
    except LLMError as exc:
        logger.warning("AI 助手模型调用失败：%s", exc)
        finish_assistant_message(
            assistant_message_id,
            content="".join(parts),
            status="error",
            error=str(exc),
        )
        yield format_sse({"type": "error", "message": str(exc)})
    except Exception:  # noqa: BLE001 - 流式响应必须转换内部异常
        logger.exception("AI 助手流式回复发生内部错误")
        message = "回复过程中发生内部错误，请查看后端日志"
        finish_assistant_message(
            assistant_message_id,
            content="".join(parts),
            status="error",
            error=message,
        )
        yield format_sse({"type": "error", "message": message})
    finally:
        # Closing an async generator can bypass CancelledError when the browser断开。
        cancel_pending_assistant_message(assistant_message_id, "".join(parts))


__all__ = [
    "format_sse",
    "history_snapshot",
    "update_message_context",
    "finish_assistant_message",
    "cancel_pending_assistant_message",
    "stream_message_events",
]
