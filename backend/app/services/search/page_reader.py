"""受限的网页正文读取。

助手要"上网收集信息"，只有搜索摘要不够——很多招聘页/技术博客的摘要几乎为空。这里
把前几条结果页的正文取回来，作为**不可信资料**附在搜索上下文里。

安全边界（这是本模块存在的理由）：
- 只允许 http/https，且**拒绝解析到内网/回环/保留地址的主机**（本地应用不该被当成
  打内网的跳板）；
- 限制响应体大小、超时、重定向次数，只取文本类内容；
- 只抽取正文标签的可见文字，不执行任何脚本。
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

MAX_PAGE_BYTES = 1_500_000
MAX_TEXT_CHARS = 2_500
_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
_HEADERS = {
    "User-Agent": "ResumeForge/0.8 (+local career assistant; page summary)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
# 这些标签里的文字不是正文。
_SKIPPED_TAGS = frozenset({"script", "style", "nav", "header", "footer", "aside", "form", "svg"})
_TEXT_TAGS = frozenset({"p", "li", "h1", "h2", "h3", "h4", "blockquote", "td", "dd", "pre"})


class _ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._depth = 0
        self._capture = False
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_TAGS:
            self._depth += 1
        elif tag in _TEXT_TAGS and self._depth == 0:
            self._capture = True
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS and self._depth > 0:
            self._depth -= 1
        elif tag in _TEXT_TAGS and self._capture:
            self._capture = False
            text = " ".join("".join(self._buffer).split())
            if len(text) >= 20:  # 太短的片段多半是导航或标签
                self.parts.append(text)
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capture and self._depth == 0:
            self._buffer.append(data)


def is_public_http_url(url: str) -> bool:
    """只放行指向公网主机的 http/https 地址。"""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    host = parsed.hostname.casefold()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return False
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None)}
    except (socket.gaierror, OSError):
        return False
    for address in addresses:
        try:
            parsed_ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        # 解析到内网/回环/保留地址一律拒绝（DNS 解析在请求前做一次；
        # 本机单用户工具不追求抵抗 DNS rebinding，但要挡住"直接写内网地址"）。
        if (
            parsed_ip.is_private
            or parsed_ip.is_loopback
            or parsed_ip.is_link_local
            or parsed_ip.is_reserved
            or parsed_ip.is_multicast
        ):
            return False
    return True


def extract_text(html_text: str, max_chars: int = MAX_TEXT_CHARS) -> str:
    parser = _ArticleParser()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:  # noqa: BLE001 - 页面再乱也不该中断整次搜索
        pass
    text = "\n".join(parser.parts)
    return text[:max_chars]


async def fetch_page_text(url: str, max_chars: int = MAX_TEXT_CHARS) -> str:
    """读取一页正文；任何失败都返回空串（调用方按"这条没有正文"处理）。"""
    if not is_public_http_url(url):
        logger.info("跳过不可抓取的地址")
        return ""
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, follow_redirects=True, max_redirects=3
        ) as client:
            async with client.stream("GET", url, headers=_HEADERS) as response:
                if response.status_code != 200:
                    return ""
                content_type = response.headers.get("content-type", "").casefold()
                if content_type and not any(
                    marker in content_type for marker in ("text/html", "text/plain", "xml")
                ):
                    return ""
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_PAGE_BYTES:
                        break
                    body.extend(chunk)
        return extract_text(body.decode("utf-8", errors="replace"), max_chars)
    except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPError) as exc:
        logger.info("正文抓取失败：%s", type(exc).__name__)
        return ""


__all__ = ["MAX_TEXT_CHARS", "extract_text", "fetch_page_text", "is_public_http_url"]
