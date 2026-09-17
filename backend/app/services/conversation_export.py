"""把一段助手对话导出成可以带走的文本。

两种用途，格式要求不同：

- **导出到外部**（Markdown / 纯文本 / JSON）：用户要的是"能读、能贴、能存档"，
  所以 Markdown 里保留标题层级、时间与来源链接，纯文本去掉所有标记符号。
- **导入资料箱**：同一份文本会成为资料箱的一条内容，之后助手还能读它、总结它、
  把它整理进个人资料。所以标题、时间与逐条消息都要在，且不要塞入渲染用的 HTML。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ..models.assistant import ChatConversation, ChatMessage

# 单条消息在导出文件里的长度上限：附件与长表格可能很长，导出文件不该失控。
MAX_EXPORTED_MESSAGE_CHARS = 8_000


def _display_time(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%Y-%m-%d %H:%M")


def _role_label(role: str) -> str:
    return "求职助手" if role == "assistant" else "我"


def _clip(content: str) -> str:
    text = (content or "").strip()
    if len(text) <= MAX_EXPORTED_MESSAGE_CHARS:
        return text
    return f"{text[:MAX_EXPORTED_MESSAGE_CHARS]}\n\n…（本条消息过长，导出时已截断）"


def _tool_summaries(message: ChatMessage) -> list[str]:
    """把"助手做了什么"整理成一行行摘要，导出后仍能看出它改过什么东西。"""
    tools = (message.context or {}).get("tools") or []
    summaries: list[str] = []
    if not isinstance(tools, list):
        return summaries
    for item in tools:
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary") or "").strip()
        if not summary:
            continue
        ok = item.get("ok", True)
        summaries.append(summary if ok else f"{summary}（失败）")
    return summaries


def _sources(message: ChatMessage) -> list[dict[str, str]]:
    items = (message.context or {}).get("sources") or []
    if not isinstance(items, list):
        return []
    collected: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        collected.append({"title": str(item.get("title") or url).strip(), "url": url})
    return collected


def conversation_to_markdown(conversation: ChatConversation, messages: list[ChatMessage]) -> str:
    lines = [
        f"# {conversation.title or '求职助手对话'}",
        "",
        f"> 导出时间：{_display_time(datetime.now())}",
        f"> 消息数：{len(messages)}",
        "",
    ]
    seen_sources: set[str] = set()
    for message in messages:
        lines.append(f"## {_role_label(message.role)} · {_display_time(message.created_at)}")
        if message.content.strip():
            lines.append("")
            lines.append(_clip(message.content))
        attachments = message.attachments or []
        if attachments:
            names = "、".join(
                str(item.get("name") or "附件")
                for item in attachments
                if isinstance(item, dict)
            )
            if names:
                lines.extend(["", f"（附件：{names}）"])
        summaries = _tool_summaries(message)
        if summaries:
            lines.extend(["", "助手操作：", *[f"- {item}" for item in summaries]])
        sources = _sources(message)
        if sources:
            lines.append("")
            lines.append("参考来源：")
            for source in sources:
                if source["url"] in seen_sources:
                    continue
                seen_sources.add(source["url"])
                lines.append(f"- [{source['title']}]({source['url']})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def conversation_to_text(conversation: ChatConversation, messages: list[ChatMessage]) -> str:
    """纯文本版本：去掉所有 Markdown 标记，适合贴进聊天窗口或邮件。"""
    lines = [
        conversation.title or "求职助手对话",
        f"导出时间：{_display_time(datetime.now())}    消息数：{len(messages)}",
        "-" * 40,
    ]
    for message in messages:
        lines.append(f"[{_display_time(message.created_at)}] {_role_label(message.role)}：")
        if message.content.strip():
            lines.append(_clip(message.content))
        summaries = _tool_summaries(message)
        if summaries:
            lines.append("（助手操作：" + "；".join(summaries) + "）")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def conversation_to_json(conversation: ChatConversation, messages: list[ChatMessage]) -> str:
    """结构化导出：便于用户自己再加工（也方便以后导回来）。"""
    payload: dict[str, Any] = {
        "title": conversation.title,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "created_at": conversation.created_at.isoformat(timespec="seconds")
        if conversation.created_at
        else "",
        "group_name": conversation.group_name,
        "messages": [
            {
                "role": message.role,
                "content": _clip(message.content),
                "created_at": message.created_at.isoformat(timespec="seconds")
                if message.created_at
                else "",
                "quoted": (message.context or {}).get("quoted"),
                "attachments": [
                    {"name": str(item.get("name") or "")}
                    for item in (message.attachments or [])
                    if isinstance(item, dict)
                ],
                "tools": _tool_summaries(message),
                "sources": _sources(message),
            }
            for message in messages
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


EXPORT_FORMATS = {
    "md": ("text/markdown; charset=utf-8", conversation_to_markdown),
    "txt": ("text/plain; charset=utf-8", conversation_to_text),
    "json": ("application/json; charset=utf-8", conversation_to_json),
}


def build_conversation_filename(conversation: ChatConversation, fmt: str) -> str:
    """文件名：对话标题 + 日期，去掉文件系统不接受的字符。"""
    raw = (conversation.title or "求职助手对话").strip()
    safe = "".join("_" if char in '\\/:*?"<>|\n\r\t' else char for char in raw)[:60]
    stamp = datetime.now().strftime("%Y%m%d")
    return f"{safe or '求职助手对话'}_{stamp}.{fmt}"


__all__ = [
    "EXPORT_FORMATS",
    "build_conversation_filename",
    "conversation_to_json",
    "conversation_to_markdown",
    "conversation_to_text",
]
