"""从地址里判断"这是哪一类页面"。

**为什么单独成模块**：这套判据有两个使用者，而且它们在不同的层——通用适配器用它挑出该跟进
的链接，采集服务用它把站点地图里的几千个地址筛成"可能是岗位页"的那一批。留在适配器里会让
服务层反向依赖某个适配器，而写第二份又必然与第一份漂移（漂移的表现是"链接挑得准、站点地图
筛得歪"，排查时很难想到是两处判据不一致）。

**这是启发式，会判错**（见 ``docs/official-collect-plan.md``）。设计上容忍它，因为两个方向的
代价不对称：多挑一个的代价是多取一个页面（抽不出岗位，什么也不会入库）；漏挑的代价是漏岗位。
真正兜住错误的是对账——它不会因为"抓得少"就说抓全了。
"""
from __future__ import annotations

from urllib.parse import urlsplit
from urllib.parse import parse_qsl

# 路径里出现这些片段就当作岗位详情页。**都带尾斜杠**：只写 ``/job`` 会把 ``/job-board``
# 这类栏目页也算进来，而它们往往列着几十个不相干的链接。
JOB_PATH_MARKERS = (
    "/job/",
    "/jobs/",
    "/position/",
    "/positions/",
    "/opening/",
    "/openings/",
    "/vacancy/",
    "/vacancies/",
    "/career/",
    "/careers/",
    "/zhiwei/",
    "/zhaopin/",
)

JOB_INDEX_SEGMENTS = frozenset(
    {
        "type",
        "types",
        "category",
        "categories",
        "location",
        "locations",
        "page",
        "search",
        "filter",
        "filters",
        "create",
        "submit",
        "login",
    }
)

# 招聘**栏目页**的路径片段。只在"从入口页找下一跳"时使用：用户给出的是官网首页时，
# 多这一跳才够得着岗位列表。
CAREERS_INDEX_MARKERS = (
    "/careers",
    "/career",
    "/jobs",
    "/positions",
    "/join-us",
    "/joinus",
    "/work-with-us",
    "/zhaopin",
    "/zhiwei",
)

PAGINATION_QUERY_KEYS = frozenset({"page", "p", "pageno", "page_no", "page_num", "offset"})
PAGINATION_TEXT = frozenset({"next", "next page", "下一页", "下页", "后一页", "更多岗位"})


# 这些子域是"招聘相关"的，不是公司名本身。
SUBDOMAIN_PREFIXES = frozenset(
    {"www", "careers", "career", "jobs", "job", "recruit", "recruiting", "hr", "join", "apply"}
)


def host_label(host: str) -> str:
    """从主机名里取一个像公司标识的标签。

    **这是低置信度的猜测**，两个用途都只拿它当起点：探测用它生成候选 token（命中与否由实际
    请求决定），公司发现用它兜底一个建议名（用户可改）。

    取"第一个不像招聘子域的标签"，对 ``careers.acme.com`` 与 ``acme.co.uk`` 都得到 ``acme``。
    实现只有这一份——两处各写一份的漂移表现是"探测猜得准、候选清单里的名字却很怪"。
    """
    cleaned = (host or "").strip().casefold().lstrip(".")
    if not cleaned:
        return ""
    for label in (item for item in cleaned.split(".") if item):
        if label not in SUBDOMAIN_PREFIXES:
            return label
    return ""


def _host_and_path(url: str, page_host: str) -> tuple[bool, str]:
    """地址是否与页面同主机；同主机时顺带返回归一化后的路径。

    **只认同主机**：跨站链接多半是社交分享、母公司官网、招聘平台外链，跟进它们会跑到我们
    没打算采集的站点上去。
    """
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False, ""
    if parsed.scheme not in ("http", "https"):
        return False, ""
    if (parsed.hostname or "").casefold() != page_host.casefold():
        return False, ""
    return True, parsed.path.casefold()


def looks_like_job_url(url: str, *, page_host: str) -> bool:
    """这个地址像不像一个岗位详情页。"""
    same_host, path = _host_and_path(url, page_host)
    if not same_host:
        return False
    for marker in JOB_PATH_MARKERS:
        index = path.find(marker)
        if index < 0:
            continue
        # 标记后面必须还有内容：``/jobs/`` 本身是栏目页，``/jobs/123`` 才是详情页。
        remainder = path[index + len(marker) :].strip("/")
        if not remainder:
            continue
        first_segment = remainder.split("/", 1)[0]
        if first_segment in JOB_INDEX_SEGMENTS:
            continue
        if remainder:
            return True
    return False


def looks_like_careers_index(url: str, *, page_host: str) -> bool:
    """这个地址像不像"招聘栏目首页"（岗位列表所在的那一页）。"""
    same_host, path = _host_and_path(url, page_host)
    if not same_host:
        return False
    trimmed = path.rstrip("/")
    return any(trimmed.endswith(marker) for marker in CAREERS_INDEX_MARKERS)


def looks_like_pagination_url(url: str, *, page_host: str) -> bool:
    """判断同站链接是否像列表的下一页。"""
    same_host, path = _host_and_path(url, page_host)
    if not same_host:
        return False
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if any(name.casefold() in PAGINATION_QUERY_KEYS for name in query):
        return True
    segments = [segment for segment in path.rstrip("/").split("/") if segment]
    return len(segments) >= 2 and segments[-2].casefold() == "page" and segments[-1].isdigit()


__all__ = [
    "CAREERS_INDEX_MARKERS",
    "JOB_INDEX_SEGMENTS",
    "JOB_PATH_MARKERS",
    "SUBDOMAIN_PREFIXES",
    "host_label",
    "looks_like_careers_index",
    "looks_like_job_url",
    "looks_like_pagination_url",
]
