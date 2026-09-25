"""站点地图的取回与解析：为集合对账提供"可枚举全集"。

**用途是事后对账，不是发现入口**：站点地图告诉我们"这个站点下有哪些页面"，把它与我们实际
抓到的岗位地址集合一比，差额就是**待核实的候选**。它给不出确定的漏抓数——地图里会有早就
招满、URL 却还留着的岗位，逐个访问才能区分（见 ``reconcile`` 的集合对账那一段）。

两条安全边界：

- **XML 是不可信输入**。这里用"前置拒绝 ``DOCTYPE`` / ``ENTITY``"来挡住实体展开类攻击
  （billion laughs 能把几 KB 的文档炸成几 GB；XXE 能读本地文件）。``ElementTree`` 本身
  不解析外部实体，但对内部实体声明是放行的，所以这一层检查是必需的。**刻意不引入
  ``defusedxml``**：本功能的输入面只有"响应体大小已封顶的 XML"，一条前置检查足够，
  而新增依赖要与现有版本钉死、还要过许可证审查，代价大于收益。
- 响应体大小由取回层封顶（``max_bytes``），这里再封顶**地址条数**与**跟进的子地图数**：
  一个站点地图索引可以指向几千个子地图，无上限地跟下去就是一次自我发起的压测。
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from xml.etree import ElementTree

from .base import FeedHttp
from .robots import RobotsAwareHttp

logger = logging.getLogger(__name__)

# 单个站点地图的响应体上限。真实站点地图常在几百 KB 到几 MB。
MAX_SITEMAP_BYTES = 8_000_000
# 索引文件里最多跟进多少个子地图，以及总共最多收集多少个地址。
MAX_NESTED_SITEMAPS = 10
MAX_URLS = 20_000

# 这些声明一旦出现就拒绝解析——它们是实体展开类攻击的入口。
_FORBIDDEN_XML_MARKERS = ("<!doctype", "<!entity")


@dataclass(frozen=True)
class SitemapUrls:
    """一次站点地图收集的结果。"""

    urls: frozenset[str] = frozenset()
    # 是否因为上限而没收集完。为真时**不能**把"差集"当成完整结论。
    truncated: bool = False
    # 面向用户的说明（没取到、格式不支持、被截断…），报告页直接展示。
    detail: str = ""
    # 跟进了哪些子地图，供诊断。
    fetched: tuple[str, ...] = field(default_factory=tuple)

    @property
    def usable(self) -> bool:
        """有地址、且没被截断，才能拿去做集合对账。"""
        return bool(self.urls) and not self.truncated


def _local_name(tag: str) -> str:
    """去掉命名空间前缀：``{http://www.sitemaps.org/...}url`` → ``url``。"""
    return tag.rsplit("}", 1)[-1].casefold()


def is_safe_xml(text: str) -> bool:
    """文档里是否没有实体声明类构造。

    检查的是整段文本而不是只看开头：``DOCTYPE`` 按规范必须在序言里，但"看起来像序言"的
    判断本身就要写一个解析器，直接扫全文更简单也更不容易漏。
    """
    lowered = text[:200_000].casefold()
    return not any(marker in lowered for marker in _FORBIDDEN_XML_MARKERS)


def parse_sitemap(text: str) -> tuple[list[str], list[str]]:
    """解析一份站点地图，返回 ``(页面地址, 下级站点地图地址)``。

    **任何失败都返回空**：站点地图取不到或格式不认识，只意味着这一层对账做不了，
    不该让整次采集失败。
    """
    if not text or not is_safe_xml(text):
        return [], []
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        logger.info("站点地图解析失败")
        return [], []

    pages: list[str] = []
    nested: list[str] = []
    if _local_name(root.tag) == "sitemapindex":
        for element in root:
            if _local_name(element.tag) != "sitemap":
                continue
            location = _loc_text(element)
            if location:
                nested.append(location)
    else:
        for element in root:
            if _local_name(element.tag) != "url":
                continue
            location = _loc_text(element)
            if location:
                pages.append(location)
    return pages, nested


def _loc_text(element: ElementTree.Element) -> str:
    """取子元素 ``<loc>`` 的文本。"""
    for child in element:
        if _local_name(child.tag) == "loc":
            return (child.text or "").strip()
    return ""


async def fetch_sitemap_urls(
    http: FeedHttp,
    sitemap_urls: Sequence[str],
    *,
    max_sitemaps: int = MAX_NESTED_SITEMAPS,
    max_urls: int = MAX_URLS,
) -> SitemapUrls:
    """取回并展开站点地图（含索引文件），收集其中的页面地址。

    ``http`` 应当是已经过 robots 闸门的取回层——**站点地图也是一次抓取**，没有理由不受
    ``robots.txt`` 约束。
    """
    gate = RobotsAwareHttp.wrap(http)
    pending = [url for url in sitemap_urls if url]
    if not pending:
        return SitemapUrls(detail="站点未声明站点地图")

    urls: set[str] = set()
    fetched: list[str] = []
    truncated = False

    while pending:
        current = pending.pop(0)
        if len(fetched) >= max_sitemaps:
            truncated = True
            break
        if current.endswith(".gz"):
            # 压缩站点地图取回来是二进制，会被取回层按 UTF-8 容错解码成乱码。
            # 如实说明"这一层做不了"，而不是安静地当成"站点地图是空的"。
            return SitemapUrls(
                detail="站点地图是压缩格式（.gz），暂不支持", fetched=tuple(fetched)
            )

        result = await gate.request("GET", current, max_bytes=MAX_SITEMAP_BYTES)
        if not result.ok:
            return SitemapUrls(
                detail=f"站点地图取回失败：{result.detail or '未知原因'}",
                fetched=tuple(fetched),
            )
        fetched.append(current)

        pages, nested = parse_sitemap(result.text)
        urls.update(pages)
        if nested:
            pending.extend(nested)
        if len(urls) > max_urls:
            truncated = True
            urls = set(list(urls)[:max_urls])
            break

    detail = f"站点地图共 {len(urls)} 个地址"
    if truncated:
        detail += "（因数量或子地图上限被截断，差额不能当作完整结论）"
    return SitemapUrls(urls=frozenset(urls), truncated=truncated, detail=detail,
                       fetched=tuple(fetched))


__all__ = [
    "MAX_NESTED_SITEMAPS",
    "MAX_SITEMAP_BYTES",
    "MAX_URLS",
    "SitemapUrls",
    "fetch_sitemap_urls",
    "is_safe_xml",
    "parse_sitemap",
]
