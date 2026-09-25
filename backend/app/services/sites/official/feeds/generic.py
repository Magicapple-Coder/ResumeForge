"""通用路径：没有专用适配器时，按"页面里有什么"去读岗位。

**它是兜底，不是主力**：能识别出招聘系统的走那条契约（更稳、还带总数），识别不出来的才轮到
这里。因此本适配器**注册在最后**——探测按注册顺序取第一个命中。

取一个页面，按代价从低到高读它：先看有没有内嵌的 schema.org ``JobPosting``（有就直接得到
岗位）；没有就套**默认配方**（岗位链接的锚文本就是岗位名）；再没有就把它当成列表页，从里面
的链接里挑出**像岗位详情页**的地址派发出去。

**模型不在这里**：这一级完全由公开规范与确定性规则驱动，零猜测、零成本、可离线测试。
读不出来的页面由编排层接着试"学习来的配方"与"用户配的大模型"——那两级要读站点记忆、
要花用户的钱，不属于"这一页说了什么"。

**链接挑选是启发式，会挑错**，这一点在设计上被容忍：挑错的代价是多取几个页面（那些页面
抽不出岗位，什么也不会入库）；而漏挑的代价是漏岗位，所以宁可放宽一点。真正兜住错误的是
对账——它不会因为"抓得少"就说抓全了。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from functools import partial
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .....models.official import BLOCK_NONE, BLOCK_SOFT
from ..base import (
    BROWSER_ACTION_PARAM,
    BROWSER_PAGE_PARAM,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    FeedHttp,
    FeedJob,
    FeedPage,
    FeedTarget,
    JobFeed,
    ProbeContext,
    ProbeHit,
)
from ..blocking import looks_like_html
from ..generic.body import extract_page_body
from ..generic.jsonld import extract_job_postings
from ..generic.recipe import default_recipe, extract_with_recipe
from ..urls import (
    PAGINATION_TEXT,
    looks_like_careers_index,
    looks_like_job_url,
    looks_like_pagination_url,
)

KEY = "generic"
DISPLAY_NAME = "通用网页抽取"

# 页面大小上限。招聘列表页可能很大（一页几十个岗位链接），但比接口响应小得多。
MAX_BYTES = 4_000_000
# 一页最多派发多少个详情页。防止一个把全站链接都列出来的页面把采集拖爆。
MAX_LINKS_PER_PAGE = 100


class _LinkParser(HTMLParser):
    """收集页面里的 ``<a href>`` 与 ``<base href>``。"""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.link_texts: list[str] = []
        self.base_href = ""
        self._active_link: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in ("a", "base"):
            return
        for name, value in attrs:
            if name.casefold() != "href" or not value:
                continue
            if tag == "base":
                self.base_href = value.strip()
            else:
                self.links.append(value.strip())
                self.link_texts.append("")
                self._active_link = len(self.links) - 1

    def handle_data(self, data: str) -> None:
        if self._active_link is not None:
            self.link_texts[self._active_link] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._active_link = None


class _PaginationParser(HTMLParser):
    """识别没有 href 的「下一页」控件。

    现代招聘页经常把分页做成 React 组件：<li title="下一页"><a>…</a></li>，
    地址栏不变，只有 click 事件会换列表。把它当成没有翻页会把页面的第一批岗位误报成
    全部结果；这里只记录一个确定存在且未禁用的下一页控件，实际点击由浏览器传输层完成。
    """

    def __init__(self) -> None:
        super().__init__()
        self.next_available = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag
        values = {name.casefold(): (value or "").strip() for name, value in attrs}
        label = " ".join(
            (values.get(name, "") for name in ("title", "aria-label"))
        ).casefold()
        normalized = " ".join(label.split())
        if normalized not in PAGINATION_TEXT:
            return
        disabled = values.get("aria-disabled", "").casefold() == "true" or any(
            "disabled" in item.casefold() for item in values.get("class", "").split()
        )
        if not disabled:
            self.next_available = True


class GenericFeed(JobFeed):
    key = KEY
    display_name = DISPLAY_NAME
    # 页面不会声明"一共多少个岗位"，对账因此退到列表/集合那两层。
    provides_total = False
    # 这一级读不出岗位时，上层还有配方与模型两级可用——本适配器把页面原文交出去。
    supports_recipes = True
    # 不翻页：见 ``JobFeed.paginates``。
    paginates = False
    # 用户**直接给出招聘页地址**、而这一页又确实能取到时，这个源就算可用——哪怕这一级一条
    # 岗位也没读出来。理由见 ``JobFeed.empty_entry_is_conclusive`` 的说明：读不出只说明这一级
    # 读不出，后面还有配方与模型两级。判"未识别"是拿"我们没试"当"这里没有"。
    empty_entry_is_conclusive = True

    def __init__(self, *, max_bytes: int = MAX_BYTES) -> None:
        self._max_bytes = max_bytes

    def probe_candidates(self, ctx: ProbeContext) -> list[ProbeHit]:
        """候选就是用户给的那个页面，以及（次一等的）官网首页。

        **招聘页优先于首页**：用户给招聘页说明他就在那一页上看到了岗位；首页往往只是一堆
        品牌链接，从那里往下找招聘页要多跳一层，而这一层不在本适配器里。
        """
        candidates: list[ProbeHit] = []
        seen: set[str] = set()
        for url, confidence, evidence in (
            (ctx.careers_url, CONFIDENCE_HIGH, "你提供的招聘页地址"),
            (ctx.homepage_url, CONFIDENCE_LOW, "你提供的官网地址"),
        ):
            cleaned = (url or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            candidates.append(
                ProbeHit(
                    target=FeedTarget(feed_key=KEY, endpoint=cleaned),
                    confidence=confidence,
                    evidence=f"直接从{evidence}读取页面内嵌的岗位数据",
                )
            )
        return candidates

    async def fetch_page(
        self, http: FeedHttp, target: FeedTarget, *, cursor: str = ""
    ) -> FeedPage:
        del cursor  # 这一级不分页：翻页由列表页里的链接自然表达
        result = await http.request(
            "GET",
            target.endpoint,
            params=target.params or None,
            max_bytes=self._max_bytes,
        )
        if not result.ok:
            return FeedPage(
                block=result.block, detail=result.detail, status_code=result.status_code
            )

        if not looks_like_html(result.text):
            # 取回来不是网页（PDF、图片、JSON 接口）。如实说明，不要装作"这一页没有岗位"。
            return FeedPage(
                block=BLOCK_SOFT,
                status_code=result.status_code,
                detail="这个地址返回的不是网页",
            )

        jobs = extract_job_postings(result.text, base_url=target.endpoint)
        if jobs:
            # 真实站点的 JSON-LD 经常省略 ``url``。如果页面只声明了一条岗位，
            # 当前地址就是这条岗位最可靠的归属线索；补上它后，编排层才能在详情页
            # 限制规则里把该岗位与本次取回对应起来，并把正文回填到列表页带出的那一条。
            if len(jobs) == 1 and not jobs[0].url:
                jobs = [replace(jobs[0], url=target.endpoint)]
            return FeedPage(
                jobs=jobs,
                # 一页读出了岗位，就不再从这个页面往下派发：它多半是详情页或完整列表页，
                # 再把它的链接排进队列只会白取一轮。
                next_targets=[],
                block=BLOCK_NONE,
                status_code=result.status_code,
            )

        # 没有结构化数据时退到**默认配方**：岗位链接的锚文本就是岗位名。
        #
        # **为什么它在适配器层、学习来的配方与模型在编排层**：这一条是确定性的、免费的、
        # "这一页说了什么"级别的读取，与 JSON-LD 同一类；那两级要读站点记忆、要用用户配的
        # 大模型，是编排层的事。三者按代价从低到高排：结构化数据 → 通用规则 → 记忆 → 模型。
        #
        # **它救回来的是这一类页面**：地址像岗位页、但详情页没有结构化数据——从前那些详情页
        # 会一个岗位也读不出来，整次采集是 0 条。现在列表页至少给出条目名与地址，
        # 正文仍由详情页提供（下面的 ``next_targets`` 照常派发）。
        #
        # 它**不**覆盖"岗位地址长得不像 ``/jobs/123``"的站点（判据是同一套 ``looks_like_job_url``），
        # 那类站点要靠学出来的地址片段或模型——而它们都发生在识别之后，所以那类站点会先卡在
        # 探测这一关。这是已知边界，见 ``docs/official-collect-plan.md``。
        found = extract_with_recipe(default_recipe(), result.text, page_url=target.endpoint)

        # 这一页**自身**的正文。上面两条路都不给正文（JSON-LD 那条自带，所以它在前面就返回了；
        # 默认配方只读链接文字），而"没有结构化数据、JD 就摆在页面上的"站点正是多数——不取的话
        # 采到的岗位只有标题，下游的技能标签、岗位匹配、简历定制全部空转。
        #
        # 每一页都取，**不按"是不是详情页"来筛**：最常见的源形态之一，就是用户把某条岗位的
        # 详情页地址直接填成招聘页（那一页在第 0 层，按层级筛会把它漏掉）。归属不在这里判——
        # 编排层按"地址等于这一页"回填，那才是唯一强的判据。
        body = extract_page_body(result.text)

        return FeedPage(
            jobs=[
                FeedJob(
                    title=job.title,
                    location=job.location,
                    url=job.url,
                    posted_at=job.posted_at,
                )
                for job in found
            ],
            # **仍然派发详情页**：这一级给出的是条目名与少量字段，**不含正文**，而详情页可能
            # 带着完整的职位描述。去重按地址合并（见编排层的说明），所以不会变成两条。
            next_targets=self._next_targets(result.text, target),
            block=BLOCK_NONE,
            status_code=result.status_code,
            # 页面原文交给上层：读不出岗位时它还要试学习来的配方与模型，那两级要页面本身。
            raw=result.text,
            # 传输层的说明**必须传上去**（截断、渲染失败等）。它曾经在这里被丢掉，于是报告只能
            # 说"这一页没有可辨认的站内链接"——而真实原因是取回时内容已被截掉一半。
            # 丢掉的代价是**用户按着一个假原因去排查**，而那个原因关于页面本身是错的。
            detail=result.detail,
            body=body.description,
            body_requirements=body.requirements,
        )

    def _next_targets(self, html_text: str, target: FeedTarget) -> list[FeedTarget]:
        """从列表页里挑出下一步要取的地址。

        两级优先：先找**岗位详情页**；一个都没找到、且当前是入口页时，再退而找**招聘栏目页**
        ——用户只给得出官网首页时，多这一跳才够得着岗位列表。栏目页那一跳**只在入口页发生**
        （``depth == 0``）：它换来的是"首页 → 招聘页 → 岗位"，再往下就该由岗位链接接手，
        否则就成了漫无目的地遍历整站导航。
        """
        links = self._absolute_links(html_text, target.endpoint)
        host = urlsplit(target.endpoint).hostname or ""

        found = self._targets_from(
            links, target=target, predicate=partial(looks_like_job_url, page_host=host)
        )
        pagination = self._pagination_targets(html_text, target, host)
        if found or pagination or target.depth != 0:
            return found + pagination
        # 栏目页那一跳**不占深度额度**：它是"找列表页"，不是"从列表页往下走一层"。占了的话
        # 这条链就够不到岗位——首页（第 0 层）→ 栏目页（第 1 层）→ 岗位（第 2 层，被深度上限
        # 挡掉），而注释承诺的正是"首页 → 招聘页 → 岗位"。只填了官网首页的用户会因此一条
        # 岗位也拿不到，只拿到栏目页上那批没有正文的条目名。
        return self._targets_from(
            links,
            target=target,
            predicate=partial(looks_like_careers_index, page_host=host),
            depth=target.depth,
        )

    def _pagination_targets(
        self, html_text: str, target: FeedTarget, page_host: str
    ) -> list[FeedTarget]:
        entries = self._absolute_link_entries(html_text, target.endpoint)
        if target.depth != 0:
            return []
        found: list[FeedTarget] = []
        for link, anchor_text in entries:
            if len(found) >= MAX_LINKS_PER_PAGE:
                break
            normalized_text = " ".join(anchor_text.casefold().split())
            if not looks_like_pagination_url(link, page_host=page_host) and normalized_text not in PAGINATION_TEXT:
                continue
            found.append(
                FeedTarget(
                    feed_key=KEY,
                    endpoint=link,
                    params=dict(target.params),
                    depth=target.depth,
                    target_kind="pagination",
                )
            )
        if found:
            return found

        # 没有 href 的分页按钮只能交给真实浏览器点击。页码放进保留参数只是为了让编排层把
        # 下一次点击视为新的目标；它不会发给站点，也不把「第 N 页」当成站点契约。
        parser = _PaginationParser()
        try:
            parser.feed(html_text)
            parser.close()
        except Exception:  # noqa: BLE001 - 页面再乱也只是少跟进一个分页控件
            parser.next_available = False
        if parser.next_available:
            current_page = int(target.params.get(BROWSER_PAGE_PARAM, "1") or "1")
            return [
                FeedTarget(
                    feed_key=KEY,
                    endpoint=target.endpoint,
                    params={
                        BROWSER_ACTION_PARAM: "下一页",
                        BROWSER_PAGE_PARAM: str(current_page + 1),
                    },
                    depth=target.depth,
                    target_kind="pagination",
                )
            ]
        return found

    def _absolute_links(self, html_text: str, page_url: str) -> list[str]:
        """页面里所有绝对化、去片段、去重后的链接。"""
        return [url for url, _text in self._absolute_link_entries(html_text, page_url)]

    def _absolute_link_entries(self, html_text: str, page_url: str) -> list[tuple[str, str]]:
        parser = _LinkParser()
        try:
            parser.feed(html_text)
            parser.close()
        except Exception:  # noqa: BLE001 - 页面再乱也只是挑不出链接
            return []
        # ``<base href>`` 会改变相对链接的解析基准，站内页面用它很常见。
        base = urljoin(page_url, parser.base_href) if parser.base_href else page_url
        links: list[str] = []
        seen: set[str] = set()
        for index, href in enumerate(parser.links):
            # 去掉片段：``/jobs/1#apply`` 与 ``/jobs/1`` 是同一页，不去的会重复取。
            absolute = urljoin(base, href).split("#", 1)[0]
            if absolute in seen:
                continue
            seen.add(absolute)
            links.append((absolute, parser.link_texts[index].strip()))
        return links

    @staticmethod
    def _targets_from(
        links: list[str],
        *,
        target: FeedTarget,
        predicate: Callable[[str], bool],
        depth: int | None = None,
    ) -> list[FeedTarget]:
        """挑出符合判据的地址。``depth`` 不给就按"下一层"算（见 ``_next_targets``）。"""
        found: list[FeedTarget] = []
        for link in links:
            if len(found) >= MAX_LINKS_PER_PAGE:
                break
            if not predicate(link):
                continue
            found.append(
                FeedTarget(
                    feed_key=KEY,
                    endpoint=link,
                    params=dict(target.params),
                    depth=target.depth + 1 if depth is None else depth,
                )
            )
        return found


__all__ = ["GenericFeed", "MAX_BYTES", "MAX_LINKS_PER_PAGE"]
