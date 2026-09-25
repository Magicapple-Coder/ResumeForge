"""从页面内嵌的结构化数据里读岗位（schema.org ``JobPosting``）。

**这是通用路径里唯一有公开规范的一级**：字段名、类型与嵌套结构都由 schema.org 定义，
不依赖任何一家站点的私有格式。命中它就能零模型、零选择器地拿到结构化岗位——所以在
"选择器配方"之前先做它。

**三种容器形态都得支持**，少一种就会让整个站在这一级失败（而这三种在真实页面里都很常见）：

- 裸对象 ``{"@type": "JobPosting", ...}``
- 数组 ``[{...}, {...}]``
- ``@graph`` 包装 ``{"@graph": [...]}``（一个页面里塞多种类型时最常见）

``@type`` 本身也有三种写法，同样都要认：``"JobPosting"``、
``"https://schema.org/JobPosting"``、``["JobPosting", "Thing"]``。

**字段拿不准就留空，不猜**（与项目既有取向一致）：例如 ``employmentType`` 只映射
``INTERN``，因为 ``FULL_TIME`` 回答的是"这份工作是不是全职"，而本项目的岗位类型
分的是"校招 / 实习 / 社招"——那是招聘渠道，不是雇佣形式，硬映射会把校招岗位标成社招。
原始值一律留在 ``extra`` 里不丢。
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

from ..base import FeedJob
from ..html_text import html_to_text

logger = logging.getLogger(__name__)

LD_JSON_TYPE = "application/ld+json"
JOB_POSTING = "JobPosting"

# ``employmentType`` 里唯一能安全映射到本项目岗位类型的取值。
# 其余（FULL_TIME 等）描述的是雇佣形式，不是招聘渠道，映射过去会给出错误结论。
_EMPLOYMENT_TYPE_MAP = {"INTERN": "实习", "INTERNSHIP": "实习"}

# 描述与公司名这类字段可能很长，封顶防止单条岗位挤爆下游预算。
_MAX_TEXT_CHARS = 20_000


class _LdJsonParser(HTMLParser):
    """收集 ``<script type="application/ld+json">`` 的内容。

    只认带明确类型的 script：普通 ``<script>`` 是代码，不是数据。
    """

    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[str] = []
        self._capturing = False
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script" or self._capturing:
            return
        for name, value in attrs:
            if name.casefold() == "type" and (value or "").strip().casefold() == LD_JSON_TYPE:
                self._capturing = True
                self._buffer = []
                return

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._capturing:
            self._capturing = False
            self.blocks.append("".join(self._buffer))

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self._buffer.append(data)


def script_payloads(html_text: str) -> list[str]:
    """取出页面里所有 JSON-LD 脚本块的内容（原样字符串）。

    解析失败不抛：页面再乱也只是拿不到结构化数据，不该让一次采集失败。
    """
    if not html_text:
        return []
    parser = _LdJsonParser()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:  # noqa: BLE001 - 页面再乱也不该中断
        return parser.blocks
    return parser.blocks


def iter_nodes(payload: Any) -> Iterator[dict]:
    """拍平 JSON-LD：裸对象 / 数组 / ``@graph`` 及其任意嵌套组合。

    外层节点自己也会被产出——它可能本身就是一个 JobPosting，而不是纯粹装 ``@graph`` 的容器。
    类型判断在后面把关，多产出一个不含目标的节点没有代价。
    """
    if isinstance(payload, dict):
        graph = payload.get("@graph")
        if isinstance(graph, (list, dict)):
            yield from iter_nodes(graph)
        yield payload
    elif isinstance(payload, list):
        for item in payload:
            yield from iter_nodes(item)


def _type_matches(value: Any, expected: str) -> bool:
    """``@type`` 是否命中目标类型（认完整 IRI、前缀写法与数组形态）。"""
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, list):
        candidates = [item for item in value if isinstance(item, str)]
    else:
        return False
    target = expected.casefold()
    for candidate in candidates:
        # 取最后一段：``https://schema.org/JobPosting``、``schema:JobPosting``、
        # ``JobPosting`` 三种写法都会归到 ``jobposting``。
        tail = candidate.rstrip("/")
        for separator in ("/", "#", ":"):
            tail = tail.rsplit(separator, 1)[-1]
        if tail.casefold() == target:
            return True
    return False


def _text(value: Any) -> str:
    """把 schema.org 里"可能是字符串、可能是对象"的字段收敛成一行文本。"""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        # ``{"@value": "..."}``（RDF 写法）与 ``{"name": "..."}``（Organization/Country）都见过。
        for key in ("@value", "name", "value", "text"):
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return ""


def _organization_name(value: Any) -> str:
    """``hiringOrganization``：可能是对象、字符串，也可能是个数组。"""
    if isinstance(value, list):
        for item in value:
            name = _organization_name(item)
            if name:
                return name
        return ""
    return _text(value)


def _postal_address(address: Any) -> str:
    """把 ``PostalAddress`` 拼成一行"城市 省 国家"。

    只取对求职有意义的三级（街道级信息对筛选岗位没用，还会把 64 字符的显示字段撑满）。
    **按前缀去重**：中文行政区名里 ``addressLocality="上海"`` 与
    ``addressRegion="上海市"`` 同时给出是常态，逐字比较会得到"上海 上海市"这种冗余；
    而"新的这一段以已收录的某段开头"正是这类包含关系，判定简单且不会误伤
    （"朝阳区"不会被认为包含在"北京"里）。
    """
    if isinstance(address, str):
        return address.strip()
    if not isinstance(address, dict):
        return ""
    parts: list[str] = []
    for key in ("addressLocality", "addressRegion", "addressCountry"):
        piece = _text(address.get(key))
        if not piece:
            continue
        if any(part == piece or piece.startswith(part) for part in parts):
            continue
        parts.append(piece)
    return " ".join(parts)


def _location_text(value: Any) -> str:
    """``jobLocation``：可能是 Place / 数组 / 地址对象 / 纯字符串。"""
    if isinstance(value, list):
        found: list[str] = []
        for item in value:
            piece = _location_text(item)
            if piece and piece not in found:
                found.append(piece)
        return " / ".join(found)
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    from_address = _postal_address(value.get("address"))
    return from_address or _text(value.get("name"))


def _salary_text(value: Any) -> str:
    """``baseSalary`` → 可读的一行。

    schema.org 允许两种写法：``MonetaryAmount``（带 currency + value）与
    ``PriceSpecification``（直接给 min/max）。只做**如实转写**，不做"月薪/年薪"的换算——
    换算需要知道工作时长，而那不在数据里。
    """
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""

    currency = _text(value.get("currency"))
    amount = value.get("value")
    if isinstance(amount, dict):
        low = _text(amount.get("minValue")) or _text(amount.get("value"))
        high = _text(amount.get("maxValue"))
        unit = _text(amount.get("unitText"))
    elif isinstance(amount, (str, int, float)):
        low, high, unit = _text(amount), "", ""
    else:
        low = _text(value.get("minValue"))
        high = _text(value.get("maxValue"))
        unit = _text(value.get("unitText"))

    if low and high and low != high:
        body = f"{low}-{high}"
    else:
        body = low or high
    if not body:
        return ""
    pieces = [piece for piece in (currency, body, unit) if piece]
    return " ".join(pieces)


def _external_id(value: Any) -> str:
    """``identifier``：可能是 PropertyValue、字符串，也可能是数组。"""
    if isinstance(value, list):
        for item in value:
            found = _external_id(item)
            if found:
                return found
        return ""
    if isinstance(value, dict):
        return _text(value.get("value")) or _text(value.get("name"))
    return _text(value)


def parse_job_posting(node: dict, *, base_url: str = "") -> FeedJob | None:
    """把一个 ``JobPosting`` 节点转成 ``FeedJob``；``title`` 缺失时返回 ``None``。

    标题与描述在规范里都是必填项，但真实页面两者都可能缺。**标题缺就丢掉这一条**：
    没有标题的岗位在下游无法使用（去重判据、列表展示都依赖它）。描述缺则照收——
    标题、公司、链接、发布时间仍然有价值，与既有采集链路"缺 JD 也照样暂存"一致。
    """
    title = _text(node.get("title"))
    if not title:
        return None

    url = _text(node.get("url")) or _text(node.get("sameAs"))
    if url and base_url:
        url = urljoin(base_url, url)

    employment = node.get("employmentType")
    if isinstance(employment, list):
        employment_type = next(
            (_EMPLOYMENT_TYPE_MAP.get(str(item).upper(), "") for item in employment
             if _EMPLOYMENT_TYPE_MAP.get(str(item).upper())),
            "",
        )
    else:
        employment_type = _EMPLOYMENT_TYPE_MAP.get(str(employment).upper(), "")

    posted_at = _text(node.get("datePosted"))
    return FeedJob(
        title=title[:200],
        company=_organization_name(node.get("hiringOrganization"))[:128],
        location=_location_text(node.get("jobLocation"))[:64],
        salary=_salary_text(node.get("baseSalary"))[:64],
        url=url,
        # 描述是 HTML，且**整段**（规范里没有单独的"任职要求"字段）——分段交给
        # 既有的 JD 切分逻辑去做，那一份实现全项目只该有一处。
        description=html_to_text(_text(node.get("description")), max_chars=_MAX_TEXT_CHARS),
        job_type=employment_type,
        posted_at=posted_at,
        external_id=_external_id(node.get("identifier")),
        extra={
            "date_posted": node.get("datePosted"),
            "valid_through": node.get("validThrough"),
            "employment_type": node.get("employmentType"),
            "job_location_type": node.get("jobLocationType"),
            "base_salary": node.get("baseSalary"),
            "source": "json-ld",
        },
    )


def _dedupe_key(job: FeedJob) -> tuple[str, str, str]:
    return (job.url.strip(), job.title.strip().casefold(), job.company.strip().casefold())


def extract_job_postings(html_text: str, *, base_url: str = "") -> list[FeedJob]:
    """从一个页面里抽出全部岗位。**任何解析失败都返回已拿到的部分，不抛异常。**"""
    found: dict[tuple[str, str, str], FeedJob] = {}
    for block in script_payloads(html_text):
        try:
            payload = json.loads(block)
        except (ValueError, TypeError):
            # 单个脚本块坏掉不影响其它块，也不影响兜底路径接手。
            logger.debug("JSON-LD 块解析失败，跳过")
            continue
        for node in iter_nodes(payload):
            if not _type_matches(node.get("@type"), JOB_POSTING):
                continue
            try:
                job = parse_job_posting(node, base_url=base_url)
            except Exception:  # noqa: BLE001 - 畸形节点不该让整页的岗位都拿不到
                logger.debug("JobPosting 节点解析失败，跳过", exc_info=True)
                continue
            if job is None:
                continue
            key = _dedupe_key(job)
            # 同一条岗位常被多个脚本块重复声明（一个摘要版、一个完整版）。保留描述更长的
            # 那个——否则"页面上明明有完整 JD、库里却是摘要"会成为一个查不出来的静默降级。
            existing = found.get(key)
            if existing is None or len(job.description) > len(existing.description):
                found[key] = job
    return list(found.values())


__all__ = [
    "JOB_POSTING",
    "LD_JSON_TYPE",
    "extract_job_postings",
    "iter_nodes",
    "parse_job_posting",
    "script_payloads",
]
