"""自建 SearXNG 实例的 JSON 接口。

SearXNG 是开源的元搜索服务，自己部署后没有配额限制、也不会被单站限流。公共实例
经常禁用 JSON 输出或直接限流，所以这里**不预置任何默认地址**：用户填了自己的实例才
启用这一路来源。

地址由用户提供，因此只接受 http/https，且允许 http 仅限本机（与模型 Base URL 同一
套判断）：本机部署的实例就是 http://localhost:8080 这种形态。
"""
from __future__ import annotations

import json
import logging

import httpx

from ..llm.openai_compat import validated_base_url

logger = logging.getLogger(__name__)

_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)


def _normalize_url(value: str) -> str:
    return (value or "").strip().rstrip("/")


async def search_searxng(query: str, base_url: str, limit: int = 10) -> list[dict[str, str]]:
    """查询自建 SearXNG；实例不可用、JSON 被禁用或格式异常时返回空列表。"""
    normalized = _normalize_url(base_url)
    if not normalized:
        return []
    try:
        endpoint = f"{validated_base_url(normalized)}/search"
    except Exception as exc:  # noqa: BLE001 - 地址不合法时只跳过这一路来源
        logger.warning("SearXNG 地址不可用：%s", exc)
        return []

    params = {"q": query, "format": "json", "language": "zh-CN", "safesearch": "0"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
            response = await client.get(endpoint, params=params)
            if response.status_code != 200:
                logger.warning("SearXNG 搜索失败 status=%s", response.status_code)
                return []
            if len(response.content) > _MAX_RESPONSE_BYTES:
                logger.warning("SearXNG 响应过大，已跳过")
                return []
            payload = json.loads(response.content)
    except httpx.TimeoutException:
        logger.warning("SearXNG 搜索超时")
        return []
    except httpx.RequestError as exc:
        logger.warning("SearXNG 搜索无法连接：%s", exc)
        return []
    except (ValueError, UnicodeError):
        # 多数情况是实例没开 JSON 输出（返回了 HTML 页面）。
        logger.warning("SearXNG 返回的不是 JSON，请确认实例启用了 json 格式")
        return []

    items = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []

    results: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = " ".join(str(item.get("title") or "").split())[:300]
        url = str(item.get("url") or "").strip()
        if not title or not url.startswith(("http://", "https://")):
            continue
        results.append(
            {
                "title": title,
                "url": url[:2048],
                "snippet": " ".join(str(item.get("content") or "").split())[:1000],
            }
        )
        if len(results) >= limit:
            break
    logger.info("SearXNG 搜索完成 result_count=%s", len(results))
    return results


__all__ = ["search_searxng"]
