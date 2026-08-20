"""受限的 Bing RSS 搜索，只返回公开结果摘要，不抓取结果页面。"""

import html
import logging
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

BING_SEARCH_URL = "https://cn.bing.com/search"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_QUERY_CHARS = 300
_MAX_RESULTS = 5
_TAG_RE = re.compile(r"\s+")


class AssistantSearchError(Exception):
    """可安全展示给用户的联网搜索错误。"""


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain_text(value: str, max_chars: int) -> str:
    parser = _HTMLTextExtractor()
    try:
        parser.feed(value)
        parser.close()
        text = " ".join(parser.parts)
    except Exception:  # noqa: BLE001 - 搜索摘要损坏时退回实体解码文本
        text = html.unescape(value)
    text = _TAG_RE.sub(" ", text).strip()
    return text[:max_chars]


def _child_text(node: ET.Element, name: str) -> str:
    for child in node:
        if child.tag.rsplit("}", 1)[-1].casefold() == name:
            return child.text or ""
    return ""


def _safe_result_url(value: str) -> str:
    value = value.strip()
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username or parsed.password:
        return ""
    return value[:2048]


def parse_bing_rss(xml_bytes: bytes, limit: int = _MAX_RESULTS) -> list[dict[str, str]]:
    """解析体积已受限的 RSS；显式拒绝 DTD/实体声明，避免 XML 实体展开。"""
    upper = xml_bytes.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise AssistantSearchError("联网搜索返回了不安全的响应格式")
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise AssistantSearchError("联网搜索返回了无法解析的响应") from exc

    results: list[dict[str, str]] = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1].casefold() != "item":
            continue
        url = _safe_result_url(_child_text(node, "link"))
        title = _plain_text(_child_text(node, "title"), 300)
        if not url or not title:
            continue
        results.append(
            {
                "title": title,
                "url": url,
                "snippet": _plain_text(_child_text(node, "description"), 1000),
            }
        )
        if len(results) >= max(1, min(limit, _MAX_RESULTS)):
            break
    return results


async def fetch_bing_rss(query: str) -> bytes:
    """请求固定 Bing 端点；不跟随重定向，也不记录用户查询。"""
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    headers = {
        "Accept": "application/rss+xml, application/xml;q=0.9",
        "User-Agent": "ResumeForge/0.1 (+local career assistant)",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            async with client.stream(
                "GET",
                BING_SEARCH_URL,
                params={"q": query, "format": "rss", "mkt": "zh-CN", "setlang": "zh-hans"},
                headers=headers,
            ) as response:
                if response.status_code != 200:
                    logger.warning("Bing RSS 搜索失败 status=%s", response.status_code)
                    raise AssistantSearchError("联网搜索服务暂时不可用，请稍后重试")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
                        raise AssistantSearchError("联网搜索返回内容过大，已停止读取")
                    body.extend(chunk)
    except httpx.TimeoutException as exc:
        raise AssistantSearchError("联网搜索响应超时，请稍后重试") from exc
    except httpx.RequestError as exc:
        raise AssistantSearchError("无法连接联网搜索服务，请检查网络状态") from exc
    return bytes(body)


async def search_web(query: str) -> list[dict[str, str]]:
    normalized = " ".join(query.split())[:_MAX_QUERY_CHARS]
    if not normalized:
        raise AssistantSearchError("请先输入要搜索的内容")
    results = parse_bing_rss(await fetch_bing_rss(normalized))
    logger.info("Bing RSS 搜索完成 result_count=%s", len(results))
    return results
