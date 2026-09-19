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
_FALLBACK_SEARCH_URL = "https://www.bing.com/search"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_QUERY_CHARS = 300
# 返回上限提到 8：搜索摘要本来就是线索而非结论，给模型更多可挑选的来源比少而精
# 更有用（筛选规则仍在，明显无关的结果不会进来）。
_MAX_RESULTS = 8
_MAX_CANDIDATE_RESULTS = 15
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
# 「明显与招聘无关」的高置信度标记：词典/百科/诗歌页。它们会命中问句里的某个字，却不带
# 任何招聘含义。组合成页面标题时常见「XX_百度百科」「在线字典」这类形态，所以既列具体站名，
# 也列「百科/字典/词典/笔顺/拼音」这种一眼可辨的类别词。
_OBVIOUSLY_UNRELATED_MARKERS = frozenset(
    {"百度百科", "维基百科", "百科", "汉语国学", "诗歌", "词典", "字典", "笔顺", "拼音"}
)
_RECRUITMENT_DISCOVERY_MARKERS = frozenset({"招聘", "招募", "招聘信息", "招聘岗位", "职位", "岗位"})
_INTERNET_EMPLOYER_MARKERS = frozenset({"互联网", "大厂", "科技企业", "科技公司"})
_RECRUITMENT_URL_MARKERS = frozenset(
    {"career", "careers", "jobs", "recruit", "recruiting", "talent", "campus"}
)
# 第三方平台只能作为线索，排序时排在用人单位官网之后。
_THIRD_PARTY_HOST_MARKERS = frozenset(
    {
        "zhipin.com",
        "lagou.com",
        "liepin.com",
        "51job.com",
        "nowcoder.com",
        "zhihu.com",
        "csdn.net",
        "jianshu.com",
        "douban.com",
        "weibo.com",
        "baike.baidu.com",
        "sohu.com",
        "163.com",
        "qq.com",
    }
)
_OFFICIAL_HOST_SUFFIXES = (".gov.cn", ".edu.cn", ".org.cn", ".ac.cn")


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


# 句首的祈使/语气词。搜索引擎会把句首虚词当成主键，所以对"不含明确求职词"的问题先把它们
# 剥掉，别让「帮」这种字当搜索词。按长度降序匹配，避免「帮我一下」被拆成「帮我」+「一下」。
_QUERY_LEADING_FILLERS = (
    "麻烦帮我",
    "帮我一下",
    "请帮我",
    "麻烦你",
    "帮我",
    "帮忙",
    "麻烦",
    "我想",
    "我要",
    "给我",
    "你能",
    "能否",
    "可以",
    "替我",
    "请",
    "把",
)
# 句尾语气词。
_QUERY_TRAILING_FILLERS = ("可以吗", "好吗", "谢谢", "多谢", "一下", "吧", "呢", "啊", "吗")
# 句中的祈使连接词："把 X 整理成 Y" 里的「整理成」。只在无求职词的问题里剥掉。
_QUERY_CONNECTORS = ("整理成", "整理为", "总结成", "汇总成", "归纳成", "转换成", "转成")


def _strip_conversational_filler(text: str) -> str:
    """剥掉句首祈使词、句尾语气词与句中祈使连接词（纯函数，可单独测试）。

    **只用于没有明确求职词的问题**（求职类问题走 ``build_search_query`` 的关键词列表分支，
    本来就不带口语词）。返回可能是空串（整句都是语气词），调用方要负责兜底。
    """
    stripped = text.strip()
    # 反复剥句首：'请帮我把 X' 要先剥 '请帮我'、再剥 '把'。
    leading = sorted(_QUERY_LEADING_FILLERS, key=len, reverse=True)
    while stripped:
        filler = next((item for item in leading if stripped.startswith(item)), "")
        if not filler:
            break
        stripped = stripped[len(filler):].strip()
    # 反复剥句尾：'... 一下 吧'。
    trailing = sorted(_QUERY_TRAILING_FILLERS, key=len, reverse=True)
    while stripped:
        filler = next((item for item in trailing if stripped.endswith(item)), "")
        if not filler:
            break
        stripped = stripped[: -len(filler)].strip()
    for connector in _QUERY_CONNECTORS:
        stripped = stripped.replace(connector, " ")
    return " ".join(stripped.split())


def build_search_query(question: str) -> str:
    """Remove conversational filler from Chinese career questions before calling Bing.

    Search engines can overweight opening words such as ``如果`` in a natural-language
    question. For a recognisable career question, use only concrete career concepts and
    add a recruitment qualifier. Questions **without** clear career words keep their
    concrete wording but lose conversational fillers (``帮我`` / ``把…整理成`` / ``一下``):
    otherwise an opening particle such as ``帮`` becomes the effective query — Bing splits
    long Chinese sentences and often keeps only the first character.
    """
    normalized = _normalized_query(question)
    if _is_recruitment_discovery_question(normalized):
        return _build_recruitment_discovery_query(normalized)
    terms = _matched_career_terms(normalized)
    if len(terms) < 2:
        # 不含（或只含一个）明确求职词：不改成关键词列表，但要剥掉口语填充词。
        # 剥完可能只剩空串（整句都是语气词），那时退回原句，别把空查询发出去。
        stripped = _strip_conversational_filler(normalized)
        return stripped or normalized
    if "招聘" not in terms and "求职" not in terms:
        terms.append("招聘")
    return " ".join(terms)[:_MAX_QUERY_CHARS]


def _has_recruitment_url_marker(url: str) -> bool:
    parsed = urlsplit(url)
    url_text = f"{parsed.hostname or ''}{parsed.path}".casefold()
    return any(marker in url_text for marker in _RECRUITMENT_URL_MARKERS)


def _is_obviously_unrelated_result(result: dict[str, str]) -> bool:
    """结果明显与招聘无关（词典/百科/诗歌…），且**不带任何**招聘/求职线索。

    判定刻意保守：只要结果里出现招聘/求职线索，或链接带 careers/jobs 这类标记，就**不**算
    "明显无关"——宁可留几条普通的，也不误杀可能相关的。
    """
    haystack = f"{result['title']} {result['snippet']} {result['url']}".casefold()
    if _has_recruitment_url_marker(result["url"]) or any(
        marker.casefold() in haystack for marker in _CAREER_MARKERS
    ):
        return False
    return any(marker.casefold() in haystack for marker in _OBVIOUSLY_UNRELATED_MARKERS)


def _is_relevant_career_result(
    result: dict[str, str], terms: list[str], question: str
) -> bool:
    haystack = f"{result['title']} {result['snippet']} {result['url']}".casefold()
    matched = [term for term in terms if term.casefold() in haystack]
    has_recruitment_url_marker = _has_recruitment_url_marker(result["url"])
    has_career_marker = has_recruitment_url_marker or any(
        marker.casefold() in haystack for marker in _CAREER_MARKERS
    )
    # A dictionary or poem result can match a generic word in a question. It is not a
    # useful recruitment source unless it also contains explicit hiring context.
    if _is_obviously_unrelated_result(result):
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
        # 问题里没有任何已知求职词时判断不了"相关"，但**明显无关**的（词典/百科/诗歌）仍要
        # 丢：它们只是匹配了问句里的某个字，没有任何招聘含义。
        # 这里**不再整体放行**——那正是「帮」被当成关键词时 8 条字典页全部塞进模型上下文的
        # 原因（terms 为空 → 短路 → _OBVIOUSLY_UNRELATED_MARKERS 那套过滤根本没机会执行）。
        # 取舍：只丢高置信度的明显无关项，其余一律保留（无法判断就不乱丢）。
        return [result for result in results if not _is_obviously_unrelated_result(result)]
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
        if len(results) >= max(1, min(limit, _MAX_CANDIDATE_RESULTS)):
            break
    return results


async def _fetch_rss_once(url: str, query: str) -> bytes:
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    headers = {
        "Accept": "application/rss+xml, application/xml;q=0.9",
        "User-Agent": "ResumeForge/0.2 (+local career assistant)",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            async with client.stream(
                "GET",
                url,
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


async def fetch_bing_rss(query: str) -> bytes:
    """请求固定 Bing 端点；不跟随重定向，也不记录用户查询。

    国内网络走 ``cn.bing.com``，它不可用时退回 ``www.bing.com``——两个端点返回同一种
    RSS，多一次尝试就能覆盖"某个域被拦但另一个可用"的情况。
    """
    last_error: AssistantSearchError | None = None
    for url in (BING_SEARCH_URL, _FALLBACK_SEARCH_URL):
        try:
            return await _fetch_rss_once(url, query)
        except AssistantSearchError as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


def _deduplicate(results: list[dict[str, str]]) -> list[dict[str, str]]:
    """按主机名 + 路径去重，丢掉查询参数造成的同页重复。"""
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, str]] = []
    for result in results:
        parsed = urlsplit(result["url"])
        key = ((parsed.hostname or "").casefold(), parsed.path.rstrip("/"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(result)
    return unique


def official_like_score(result: dict[str, str]) -> int:
    """用人单位官网/招聘页排序权重；第三方平台降权，但不会被丢掉。"""
    host = (urlsplit(result["url"]).hostname or "").casefold()
    score = 0
    if any(host.endswith(suffix) for suffix in _OFFICIAL_HOST_SUFFIXES):
        score += 2
    if _has_recruitment_url_marker(result["url"]):
        score += 2
    if any(marker in host for marker in _THIRD_PARTY_HOST_MARKERS):
        score -= 2
    if "招聘" in f"{result['title']} {result['snippet']}":
        score += 1
    return score


def rank_results(results: list[dict[str, str]]) -> list[dict[str, str]]:
    """官网招聘页在前；同分保持搜索服务给出的原始顺序。"""
    indexed = list(enumerate(results))
    indexed.sort(key=lambda pair: (-official_like_score(pair[1]), pair[0]))
    return [item for _, item in indexed]


async def search_web(query: str) -> list[dict[str, str]]:
    normalized = _normalized_query(query)
    if not normalized:
        raise AssistantSearchError("请先输入要搜索的内容")
    search_query = build_search_query(normalized)
    candidates = parse_bing_rss(
        await fetch_bing_rss(search_query), limit=_MAX_CANDIDATE_RESULTS
    )
    results = rank_results(
        _deduplicate(filter_relevant_results(candidates, normalized))
    )[:_MAX_RESULTS]
    if not results:
        # 零结果就如实报错，**不再**以"问题含已知求职词"为前提：那样非求职类问题即使被
        # 过滤得一条不剩也会静默返回空，模型可能据此瞎编。报错会让调用方明确"没拿到资料"。
        raise AssistantSearchError(
            "没有找到与当前问题直接相关的公开来源。可以换成更具体的公司名、岗位名或技术方向再搜一次。"
        )
    logger.info("Bing RSS 搜索完成 result_count=%s", len(results))
    return results
