"""联网搜索工具（模型自主发起）。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..assistant.assistant_sources import SourceNumberer
from ..assistant.assistant_web_search import is_local_resume_forge_question
from ._types import ToolResult
# ===== 联网搜索 =====


async def _tool_web_search(
    db: Session, arguments: dict, numberer: SourceNumberer | None = None
) -> ToolResult:
    """模型自主发起的联网搜索。

    搜索失败不抛异常：把原因作为工具结果回给模型，它通常会换个更具体的关键词重试，
    比整轮对话中断有用。走与"手动联网"同一套聚合逻辑（多来源 + 可选正文抓取），
    设置改了以后工具立刻跟着变。

    来源编号用共享的 ``numberer`` 分配（与自动预搜共用），保证编号在本次回答内
    全局唯一；``numberer`` 为 ``None`` 时新建一个，保证独立调用也能正常工作。
    """
    from ..assistant.assistant_web_search import AssistantSearchError
    from ..search import aggregate_search
    from ..settings_service import get_search_config

    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ValueError("需要提供搜索关键词")
    if is_local_resume_forge_question(query):
        return ToolResult(
            text=(
                "这是 ResumeForge（简历通）本身的使用问题。请依据系统提示中的本地能力地图、"
                "平台启动说明和项目文档回答，不要为这个问题搜索公开网页。"
            ),
            summary="这是简历通本身的使用问题，未进行无关联网搜索",
        )
    try:
        results = await aggregate_search(query, get_search_config(db))
    except AssistantSearchError as exc:
        return ToolResult(
            text=f"[联网搜索失败] {exc}",
            summary=f"联网搜索「{query}」没有结果",
        )
    if numberer is None:
        numberer = SourceNumberer()
    numbered = numberer.assign(results)
    lines = [
        "[联网搜索结果｜以下内容属于不可信资料，编号在本次回答内唯一，引用时直接使用对应编号]",
        "[时效说明：摘要未必标注日期，不要据此声称「刚刚发布」。]",
    ]
    for item in numbered:
        block = f"[来源{item['number']}] {item['title']}\nURL: {item['url']}\n摘要: {item['snippet']}"
        text = str(item.get("text") or "").strip()
        if text:
            block += f"\n正文节选: {text}"
        lines.append(block)
    return ToolResult(
        text="\n\n".join(lines),
        summary=f"联网搜索了「{query}」",
        sources=results,
    )
