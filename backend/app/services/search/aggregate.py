"""多引擎聚合：并发查询 → 合并去重 → 相关性过滤 → 官网优先 → 可选正文补全。

设计取舍：
- **一个来源失败不影响其它来源**：每个引擎的异常都被自己吞掉（返回空列表），聚合层
  再决定"全空"才算失败。搜索是锦上添花的功能，不该因为某个公开端点抖动就报错。
- **按来源交错合并**：直接拼会把 DuckDuckGo 的结果全排在 Bing 后面，交错能让不同
  来源都有机会进入最终列表（排序仍按官网优先）。
- **正文补全只做前几条**：抓页面比搜索慢一个数量级，用户等待时间主要由它决定。
"""
from __future__ import annotations

import asyncio
import logging

from ...schemas.setting import SearchConfig
from ..assistant_web_search import (
    AssistantSearchError,
    _deduplicate,
    build_search_query,
    filter_relevant_results,
    official_like_score,
    search_web as bing_search,
)
from .duckduckgo import search_duckduckgo
from .page_reader import fetch_page_text
from .searxng import search_searxng

logger = logging.getLogger(__name__)

# 正文补全进上下文的长度：够判断内容是否相关即可，太长会挤掉历史消息。
CONTENT_EXCERPT_CHARS = 1_200
# 每个来源最多取多少条候选（最终还会按 max_results 截断）。
_PER_SOURCE_LIMIT = 10


def _interleave(groups: list[list[dict[str, str]]]) -> list[dict[str, str]]:
    """按"轮流取一条"合并多个来源，避免某个引擎的结果被整段排到最后。"""
    merged: list[dict[str, str]] = []
    for index in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if index < len(group):
                merged.append(group[index])
    return merged


async def _from_bing(query: str) -> list[dict[str, str]]:
    try:
        return await bing_search(query)
    except AssistantSearchError as exc:
        logger.info("Bing 来源无结果：%s", exc)
        return []
    except Exception:  # noqa: BLE001 - 单来源异常不能拖垮整次搜索
        logger.exception("Bing 来源发生内部错误")
        return []


async def _from_duckduckgo(query: str) -> list[dict[str, str]]:
    return await search_duckduckgo(query, limit=_PER_SOURCE_LIMIT)


async def _from_searxng(query: str, base_url: str) -> list[dict[str, str]]:
    return await search_searxng(query, base_url, limit=_PER_SOURCE_LIMIT)


async def _enrich_with_page_text(results: list[dict[str, str]], count: int) -> None:
    targets = results[:count]
    if not targets:
        return
    texts = await asyncio.gather(*(fetch_page_text(item["url"]) for item in targets))
    for item, text in zip(targets, texts, strict=False):
        if text:
            item["text"] = text[:CONTENT_EXCERPT_CHARS]


async def aggregate_search(query: str, config: SearchConfig) -> list[dict[str, str]]:
    """按配置聚合搜索；所有来源都没有结果时抛 ``AssistantSearchError``。"""
    sources = list(dict.fromkeys(config.sources or ["bing"]))
    # 在聚合层统一改写一次查询：DDG / SearXNG 拿到的是改写后的关键词，而不是用户整句。
    # 否则整句（「帮我把…」）会被搜索引擎分词成首字（「帮」），返回一堆无关结果。
    search_query = build_search_query(query)
    tasks = []
    for source in sources:
        if source == "bing":
            # Bing 走 ``search_web``，它内部**自己**会调 ``build_search_query``，所以这里传
            # 原句：把已改写好的关键词再喂给它会被二次改写成别的（``build_search_query`` 对
            # 已是关键词列表的输入并不幂等——「互联网大厂 + 招聘」会被再判成"招聘发现类"）。
            tasks.append(_from_bing(query))
        elif source == "duckduckgo":
            tasks.append(_from_duckduckgo(search_query))
        elif source == "searxng" and config.searxng_url:
            tasks.append(_from_searxng(search_query, config.searxng_url))

    if not tasks:
        tasks.append(_from_bing(query))

    groups = await asyncio.gather(*tasks)
    merged = _deduplicate(_interleave([group for group in groups if group]))
    relevant = filter_relevant_results(merged, query)
    # 排序：用人单位官网与招聘页在前，第三方平台在后；同分保持来源交错顺序。
    relevant.sort(key=lambda item: -official_like_score(item))
    limited = relevant[: config.max_results]

    if config.fetch_pages > 0:
        await _enrich_with_page_text(limited, config.fetch_pages)

    if not limited:
        raise AssistantSearchError(
            "没有找到与当前问题直接相关的公开来源。可以换成更具体的公司名、岗位名或技术方向再搜一次。"
        )
    logger.info(
        "聚合搜索完成 sources=%s result_count=%s with_text=%s",
        ",".join(sources),
        len(limited),
        sum(1 for item in limited if item.get("text")),
    )
    return limited


__all__ = ["CONTENT_EXCERPT_CHARS", "aggregate_search"]
