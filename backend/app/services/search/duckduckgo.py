"""DuckDuckGo 的 HTML 端点（无需 API Key）。

为什么选它作为第二来源：Bing RSS 在国内可用但对长中文问句理解有限，DuckDuckGo 的
英文技术类查询质量明显更好，两者互补。这里只解析 HTML 页面（``html.duckduckgo.com``），
不引入任何第三方库——项目已经用 ``HTMLParser`` 处理过 HTML。

注意：它是公开的 HTML 接口，可能限流或调整结构。解析失败一律当作"这个来源没结果"，
由聚合层决定是否降级，绝不让整次搜索失败。
"""
from __future__ import annotations

import logging
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlsplit

import httpx

logger = logging.getLogger(__name__)

HTML_ENDPOINT = "https://html.duckduckgo.com/html/"
LITE_ENDPOINT = "https://lite.duckduckgo.com/lite/"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_TIMEOUT = httpx.Timeout(connect=5.0, read=12.0, write=5.0, pool=5.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 ResumeForge/0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class _ResultParser(HTMLParser):
    """从 html.duckduckgo.com 的结果页里提取标题、链接与摘要。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._field: str = ""
        self._current: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """HTMLParser 回调：遇到结果标题链接/摘要容器时切换当前抓取字段。"""
        if tag != "a":
            return
        attributes = {name: (value or "") for name, value in attrs}
        classes = attributes.get("class", "")
        if "result__a" in classes:
            url = _unwrap_redirect(attributes.get("href", ""))
            if not url:
                return
            self._current = {"title": "", "url": url, "snippet": ""}
            self.results.append(self._current)
            self._field = "title"
        elif "result__snippet" in classes and self.results:
            self._current = self.results[-1]
            self._field = "snippet"

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._field = ""

    def handle_data(self, data: str) -> None:
        if self._field and self._current is not None:
            self._current[self._field] += data


def _unwrap_redirect(href: str) -> str:
    """DuckDuckGo 的链接常是 ``//duckduckgo.com/l/?uddg=<编码后的真实地址>``。"""
    if not href:
        return ""
    candidate = href if href.startswith(("http://", "https://")) else f"https:{href}"
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return ""
    host = (parsed.hostname or "").casefold()
    if "duckduckgo.com" in host and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return unquote(target) if target else ""
    if host and "duckduckgo.com" not in host:
        return candidate
    return ""


def _clean(value: str, limit: int) -> str:
    return " ".join(value.split())[:limit]


async def search_duckduckgo(query: str, limit: int = 10) -> list[dict[str, str]]:
    """执行一次 DuckDuckGo HTML 搜索；失败或无结果时返回空列表。"""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            response = await client.post(
                HTML_ENDPOINT,
                data={"q": query},
                headers=_HEADERS,
            )
            if response.status_code != 200:
                logger.warning("DuckDuckGo 搜索失败 status=%s", response.status_code)
                return []
            body = response.content[:_MAX_RESPONSE_BYTES]
    except httpx.TimeoutException:
        logger.warning("DuckDuckGo 搜索超时")
        return []
    except httpx.RequestError as exc:
        logger.warning("DuckDuckGo 搜索无法连接：%s", exc)
        return []

    parser = _ResultParser()
    try:
        parser.feed(body.decode("utf-8", errors="replace"))
        parser.close()
    except Exception:  # noqa: BLE001 - 页面结构变了就当这个来源没结果
        logger.warning("DuckDuckGo 结果页解析失败")
        return []

    results: list[dict[str, str]] = []
    for item in parser.results:
        title = _clean(item.get("title", ""), 300)
        url = item.get("url", "")
        if not title or not url:
            continue
        results.append(
            {"title": title, "url": url, "snippet": _clean(item.get("snippet", ""), 1000)}
        )
        if len(results) >= limit:
            break
    logger.info("DuckDuckGo 搜索完成 result_count=%s", len(results))
    return results


__all__ = ["search_duckduckgo", "_unwrap_redirect"]
