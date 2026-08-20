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
_MAX_CANDIDATE_RESULTS = 10
_TAG_RE = re.compile(r"\s+")
_QUERY_SEPARATOR_RE = re.compile(r"[，。！？、；：,.!?;:\n\r]+")
_CAREER_TERMS = (
    "互联网大厂",
    "冷却期",
    "秋招",
    "春招",
    "校招",
    "社招",
    "投递",
    "招聘",
    "求职",
    "面试",
    "简历",
    "实习",
    "转正",
    "offer",
    "就业",
    "岗位",
    "职业发展",
)
_CAREER_MARKERS = frozenset(_CAREER_TERMS) | {"人才", "人力资源", "应聘"}
_OBVIOUSLY_UNRELATED_MARKERS = frozenset({"百度百科", "维基百科", "汉语国学", "诗歌", "词典"})
_RECRUITMENT_DISCOVERY_MARKERS = frozenset({"招聘", "招募", "招聘信息", "招聘岗位", "职位", "岗位"})
_INTERNET_EMPLOYER_MARKERS = frozenset({"互联网", "大厂", "科技企业", "科技公司"})
_RECRUITMENT_URL_MARKERS = frozenset(
    {"career", "careers", "jobs", "recruit", "recruiting", "talent", "campus"}
)


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


def _normalized_query(value: str) -> str:
    return " ".join(_QUERY_SEPARATOR_RE.sub(" ", value).split())[:_MAX_QUERY_CHARS]


def _matched_career_terms(value: str) -> list[str]:
    """Return distinct career terms in their order of appearance in the question."""
    matches = [(value.casefold().find(term.casefold()), term) for term in _CAREER_TERMS]
    return [term for position, term in sorted(matches) if position >= 0]


def _is_recruitment_discovery_question(value: str) -> bool:
    normalized = value.casefold()
    return any(marker.casefold() in normalized for marker in _RECRUITMENT_DISCOVERY_MARKERS) and any(
        marker.casefold() in normalized for marker in _INTERNET_EMPLOYER_MARKERS
    )


def _build_recruitment_discovery_query(value: str) -> str:
    """Use a compact query because Bing RSS mishandles long Chinese questions."""
    normalized = value.casefold()
    employer = "互联网企业" if "互联网" in normalized or "大厂" in normalized else "企业"
    return f"{employer} 招聘"


def build_search_query(question: str) -> str:
    """Remove conversational filler from Chinese career questions before calling Bing.

    Search engines can overweight opening words such as ``如果`` in a natural-language
    question. For a recognisable career question, use only concrete career concepts and
    add a recruitment qualifier. Other questions keep their original wording.
    """
    normalized = _normalized_query(question)
    if _is_recruitment_discovery_question(normalized):
        return _build_recruitment_discovery_query(normalized)
    terms = _matched_career_terms(normalized)
    if len(terms) < 2:
        return normalized
    if "招聘" not in terms and "求职" not in terms:
        terms.append("招聘")
    return " ".join(terms)[:_MAX_QUERY_CHARS]


def _has_recruitment_url_marker(url: str) -> bool:
    parsed = urlsplit(url)
    url_text = f"{parsed.hostname or ''}{parsed.path}".casefold()
    return any(marker in url_text for marker in _RECRUITMENT_URL_MARKERS)


def _is_relevant_career_result(
    result: dict[str, str], terms: list[str], question: str
) -> bool:
    haystack = f"{result['title']} {result['snippet']} {result['url']}".casefold()
    matched = [term for term in terms if term.casefold() in haystack]
    has_recruitment_url_marker = _has_recruitment_url_marker(result["url"])
    has_career_marker = has_recruitment_url_marker or any(
        marker.casefold() in haystack for marker in _CAREER_MARKERS
    )
    is_obviously_unrelated = any(marker.casefold() in haystack for marker in _OBVIOUSLY_UNRELATED_MARKERS)
    # A dictionary or poem result can match a generic word in a question. It is not a
    # useful recruitment source unless it also contains explicit hiring context.
    if is_obviously_unrelated and not has_career_marker:
        return False
    if _is_recruitment_discovery_question(question):
        # Official career pages frequently use English "Careers" or "Jobs" and may not
        # repeat the Chinese word "招聘" in their title or summary.
        return bool(has_career_marker and (matched or has_recruitment_url_marker))
    return bool(matched and has_career_marker)


def filter_relevant_results(
    results: list[dict[str, str]], question: str
) -> list[dict[str, str]]:
    """Keep only sources that visibly relate to an identifiable career question."""
    terms = _matched_career_terms(question)
    if not terms:
        return results
    return [result for result in results if _is_relevant_career_result(result, terms, question)]


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
    normalized = _normalized_query(query)
    if not normalized:
        raise AssistantSearchError("请先输入要搜索的内容")
    search_query = build_search_query(normalized)
    candidates = parse_bing_rss(
        await fetch_bing_rss(search_query), limit=_MAX_CANDIDATE_RESULTS
    )
    results = filter_relevant_results(candidates, normalized)[:_MAX_RESULTS]
    if not results and _matched_career_terms(normalized):
        raise AssistantSearchError("没有找到与当前求职问题直接相关的公开来源，请调整关键词后重试")
    logger.info("Bing RSS 搜索完成 result_count=%s", len(results))
    return results
