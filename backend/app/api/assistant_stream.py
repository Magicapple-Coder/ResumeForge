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
from ..services.assistant.assistant_service import (
    current_user_message_for_model,
    history_messages_for_model,
)
from ..services.assistant.assistant_sources import SourceNumberer
from ..services.assistant_tools import execute_tool_async, tool_definitions
from ..services.assistant.assistant_web_search import AssistantSearchError
from ..services.llm.base import BaseLLMProvider, LLMError
from .assistant_context import web_context

logger = logging.getLogger(__name__)

# 一次回复里最多允许几轮工具调用；防止模型在两个工具之间来回打转。
MAX_TOOL_ROUNDS = 5
# 一轮回答里最多搜几次网，**含自动预搜的那一次**。系统提示、README 与使用指南都写着
# "最多 3 次"，这里把它变成真的：此前只有提示词里那句话，代码侧真正的约束是 5 轮工具
# 调用，而且每轮可以并行发多个搜索——用户按文档预期 3 次，实际可能多花好几倍。
MAX_WEB_SEARCHES = 3

# 思考内容写进助手消息 `context` 的上限（字符数）。**为什么必须限长**：
#   1) 思考内容常常比正文长一个量级（高强度思考尤甚），而 context 是随每条历史消息
#      一起被批量加载的 JSON；不设限会让单条消息无限膨胀，历史列表的内存与带宽都会失控。
#   2) 它**不参与后续对话**（见下面流循环里的说明），所以保存得完整与否不影响回答质量，
#      它是"给用户回看的解释"，按上限截断即可。
# 超限时**如实截断并打标记**（context 里 `reasoning_truncated=True`），不静默丢弃。
MAX_REASONING_CONTEXT_CHARS = 20_000


def _truncate_reasoning(text: str) -> tuple[str, bool]:
    """把思考内容裁到存储上限，返回 ``(文本, 是否被截断)``。"""
    if len(text) <= MAX_REASONING_CONTEXT_CHARS:
        return text, False
    return text[:MAX_REASONING_CONTEXT_CHARS], True



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


def _is_web_search(call: dict[str, Any]) -> bool:
    return ((call.get("function") or {}).get("name") or "") == "web_search"


async def _run_tool_call(call: dict[str, Any], numberer: SourceNumberer) -> dict[str, Any]:
    """执行一次工具调用。

    任何失败都转成结构化的"工具结果"回给模型，而不是抛出去中断整轮对话——模型
    往往能据此换个参数重试，或者在回答里如实说明没做到。``numberer`` 是本次回答
    跨所有联网搜索共享的来源编号器。
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
        "changed": False,
        "sources": [],
    }
    try:
        arguments = _parse_tool_arguments(function.get("arguments") or "")
        record["arguments"] = arguments
        # 和本模块其它写回一样自开会话：不把连接跨整个流持有。
        with SessionLocal() as db:
            # 搜索类工具要 await（联网请求），所以走异步入口。
            result = await execute_tool_async(db, name, arguments, numberer=numberer)
        record["summary"] = result.summary
        record["link"] = result.link
        record["result_text"] = result.text
        record["changed"] = result.changed
        record["sources"] = result.sources
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
    quoted: dict[str, Any] | None = None,
    fetch_pages: int = 0,
) -> AsyncIterator[str]:
    parts: list[str] = []
    metadata = dict(context_metadata)
    model_context = list(context_blocks)
    # 助手这条消息的 context：思考内容与工具记录都挂在这里，供历史回看。
    # 用**同一个** dict 累积再整体写回——`update_message_context` 是整体替换而非合并，
    # 分开写会把先写进去的字段冲掉。
    assistant_context: dict[str, Any] = {}
    # 思考内容跨轮累积（模型可能每轮都先想一段再调用工具）。
    reasoning_parts: list[str] = []
    # 本次回答里所有联网来源的全局编号器：自动预搜与后续的 web_search 工具共用，
    # 保证正文里的 [来源N] 能对应到模型当时看到的那条 URL（跨两个入口不重号）。
    numberer = SourceNumberer()
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
                model_context.append(web_context(sources, numberer))
            except AssistantSearchError as exc:
                metadata["search_error"] = str(exc)
                model_context.append(f"[联网搜索状态]\n{exc}，请勿声称已获得联网资料。")
            update_message_context(user_message_id, metadata)
            yield format_sse(
                {
                    "type": "sources",
                    "sources": metadata.get("sources", []),
                    "source_map": numberer.mapping(),
                    "error": metadata.get("search_error", ""),
                }
            )

        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        messages.extend(history_messages_for_model(history))
        messages.append(
            current_user_message_for_model(payload.content, attachments, model_context, quoted)
        )

        # 只有用户打开联网开关时才把搜索工具下发给模型；关掉开关就是不希望联网。
        # fetch_pages 决定工具描述怎么说（开了抓正文就不能再说"不打开网页"）。
        tools = tool_definitions(web_search=payload.web_search, fetch_pages=fetch_pages)
        tool_records: list[dict[str, Any]] = []
        # 工具里搜到的来源与手动搜索的来源合并展示，按 URL 去重。
        collected_sources: list[dict[str, Any]] = list(metadata.get("sources") or [])
        seen_source_urls = {str(item.get("url", "")) for item in collected_sources}
        # 上面那次自动预搜**也算一次**：它同样真的发了网络请求、真的花了时间。此前这个
        # 计数从 0 起算，于是开了联网开关时"最多 3 次"实际是 4 次，和系统提示、README、
        # 使用指南里写的数字对不上。失败的预搜不计数——它没给模型任何资料，这时更需要
        # 让工具补上。
        web_searches_used = 1 if metadata.get("sources") else 0
        for _round in range(MAX_TOOL_ROUNDS):
            calls: list[dict[str, Any]] = []
            round_reasoning: list[str] = []
            async for delta in provider.stream_chat_events(messages, tools):
                if delta.text:
                    parts.append(delta.text)
                    yield format_sse({"type": "delta", "text": delta.text})
                if delta.reasoning:
                    # 思考内容单独成一个事件下发前端；它**只用于展示**，绝不塞回
                    # `messages`——把它当正文回灌给模型会让它把自己的草稿当成事实，
                    # 并且（对 Anthropic）会触发"必须原样回传 thinking 块"的协议要求，
                    # 那是另一套改动（见 `anthropic._convert_messages` 的说明）。
                    reasoning_parts.append(delta.reasoning)
                    round_reasoning.append(delta.reasoning)
                    yield format_sse({"type": "reasoning", "text": delta.reasoning})
                if delta.tool_calls:
                    calls.extend(delta.tool_calls)
            if round_reasoning:
                # 把"到目前为止的全部思考"写进 context 并立刻落库，这样即使这一轮之后
                # 流被中断，已经产生的思考历史回看仍能看到。
                stored, truncated = _truncate_reasoning("".join(reasoning_parts))
                assistant_context["reasoning"] = stored
                if truncated:
                    assistant_context["reasoning_truncated"] = True
                update_message_context(assistant_message_id, dict(assistant_context))
            if not calls:
                break

            # 把助手的这次调用原样回填进消息，模型才能把结果对上号。
            messages.append({"role": "assistant", "content": None, "tool_calls": calls})
            for call in calls:
                if _is_web_search(call) and web_searches_used >= MAX_WEB_SEARCHES:
                    # 超预算时**明确告诉模型**次数用完了，而不是静默丢掉这次调用：
                    # 静默丢弃会让它以为搜索失败、换个词再来一轮，白烧一轮调用。
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id") or "",
                            "content": (
                                f"本轮联网搜索次数已用完（最多 {MAX_WEB_SEARCHES} 次）。"
                                "请基于已经拿到的结果作答，并说明信息可能不完整。"
                            ),
                        }
                    )
                    continue
                if _is_web_search(call):
                    web_searches_used += 1
                record = await _run_tool_call(call, numberer)
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
                        # 透传"是否真的改了数据"：前端折叠标题要用它写「改动了 N 项」。
                        # 让后端说了算，前端就不必再按工具名猜哪些是写操作（猜一份必然漂移）。
                        "changed": record["changed"],
                    }
                )
                new_sources = [
                    item
                    for item in record.get("sources") or []
                    if str(item.get("url", "")) not in seen_source_urls
                ]
                if new_sources:
                    for item in new_sources:
                        seen_source_urls.add(str(item.get("url", "")))
                    collected_sources.extend(new_sources)
                    metadata["sources"] = collected_sources
                    # 来源属于用户那条消息：它说明"这次回答参考了哪些公开来源"。
                    update_message_context(user_message_id, metadata)
                    yield format_sse(
                        {
                            "type": "sources",
                            "sources": collected_sources,
                            "source_map": numberer.mapping(),
                            "error": "",
                        }
                    )
            # 工具记录属于**助手这条消息**：它描述的是助手做了什么，历史回看时挂在
            # 助手回复下最自然（来源则属于用户那条消息，见上面的联网分支）。
            assistant_context["tool_calls"] = tool_records
            update_message_context(assistant_message_id, dict(assistant_context))
        else:
            # 到达轮次上限：停止继续调用工具，让用户看到已经做了什么。
            parts.append(
                f"\n\n（已经连续执行了 {MAX_TOOL_ROUNDS} 轮工具调用，为避免失控先停在这里，"
                "你可以继续追问。）"
            )

        # 来源编号映射随助手这条消息一起落库：前端渲染正文里的 [来源N] 时按它解析，
        # 而不是拿"去重后的参考来源"下标去对——那会跳错来源。即使这轮没有工具调用/
        # 思考，只要预搜命中过，也要在结束前写回。
        assistant_context["source_map"] = numberer.mapping()
        update_message_context(assistant_message_id, dict(assistant_context))

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
