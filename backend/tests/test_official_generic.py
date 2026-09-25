"""通用路径适配器：从任意网页里读岗位。

两条设计意图各有对应的用例：

- **链接挑选宁可放宽**：挑错的代价只是多取几个抽不出岗位的页面；漏挑的代价是漏岗位。
  真正兜住错误的是对账——它不会因为"抓得少"就说抓全了。
- **列表页型站点必须能被识别**：普通公司招聘页的入口页本身不带岗位，只列出一批岗位页的
  地址。要求"必须直接读出岗位"会把这类站点全判成不支持，而它们正是通用路径的主要服务对象。
"""
from __future__ import annotations

import json

import pytest

from app.models.official import BLOCK_NONE, BLOCK_SOFT
from app.services.sites.official.base import (
    BROWSER_ACTION_PARAM,
    BROWSER_PAGE_PARAM,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    FeedHttp,
    FeedTarget,
    FetchResult,
    ProbeContext,
)
from app.services.sites.official.feeds.generic import GenericFeed
from app.services.sites.official.probe import (
    PROBE_BLOCKED,
    PROBE_HIT,
    probe_site,
)
from app.services.sites.official.registry import FeedRegistry
from app.services.sites.official.urls import looks_like_careers_index, looks_like_job_url

PAGE = "https://acme.example/careers"


def _posting_html(title: str = "大模型应用开发工程师") -> str:
    payload = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": title,
        "description": "<p>负责模型落地</p>",
        "hiringOrganization": {"name": "示例科技"},
    }
    return (
        "<html><head>"
        f'<script type="application/ld+json">{json.dumps(payload, ensure_ascii=False)}</script>'
        "</head><body></body></html>"
    )


def _listing_html(*hrefs: str, base: str = "") -> str:
    base_tag = f'<base href="{base}">' if base else ""
    links = "".join(f'<a href="{href}">岗位</a>' for href in hrefs)
    return f"<html><head>{base_tag}</head><body>{links}</body></html>"


def _button_pagination_html(*, disabled: bool = False) -> str:
    class_name = "atsx-pagination-disabled atsx-pagination-next" if disabled else "atsx-pagination-next"
    aria_disabled = "true" if disabled else "false"
    return (
        "<html><body><ul class='atsx-pagination'>"
        f"<li title='下一页' class='{class_name}' aria-disabled='{aria_disabled}'>"
        "<a class='atsx-pagination-item-link'>下一页</a></li>"
        "</ul></body></html>"
    )


class FakeHttp(FeedHttp):
    def __init__(self, routes: dict[str, FetchResult]):
        self._routes = routes
        self.calls: list[str] = []

    async def request(self, method, url, *, params=None, json_body=None, headers=None,
                      max_bytes=None):
        del method, params, json_body, headers, max_bytes
        self.calls.append(url)
        for prefix, result in self._routes.items():
            if url.startswith(prefix):
                return result
        return FetchResult(block="not_found", status_code=404)


def _html(text: str) -> FetchResult:
    return FetchResult(block=BLOCK_NONE, status_code=200, text=text, headers={})


# ===== 链接判定 =====


@pytest.mark.parametrize(
    "url",
    [
        "https://acme.example/jobs/123",
        "https://acme.example/job/abc-def",
        "https://acme.example/positions/42",
        "https://acme.example/en/careers/backend-engineer",
        "https://acme.example/zhaopin/1001",
    ],
)
def test_job_urls_are_recognised(url):
    assert looks_like_job_url(url, page_host="acme.example") is True


@pytest.mark.parametrize(
    "url",
    [
        # 栏目页本身没有"详情"，不该被当成岗位页。
        "https://acme.example/jobs/",
        "https://acme.example/jobs/type/back-end/",
        "https://acme.example/jobs/category/developer-engineer/",
        "https://acme.example/jobs/location/telecommute/",
        "https://acme.example/jobs/create/",
        "https://acme.example/careers",
        # 只会把栏目页带进队列的写法。
        "https://acme.example/job-board",
        # 跨站：社交分享、母公司官网、招聘平台外链。
        "https://other.example/jobs/1",
        "mailto:hr@acme.example",
        "javascript:void(0)",
        "https://acme.example/about",
    ],
)
def test_non_job_urls_are_rejected(url):
    assert looks_like_job_url(url, page_host="acme.example") is False


@pytest.mark.parametrize(
    "url",
    [
        "https://acme.example/careers",
        "https://acme.example/careers/",
        "https://acme.example/jobs",
        "https://acme.example/zh/about/join-us",
        "https://acme.example/work-with-us",
    ],
)
def test_careers_index_urls_are_recognised(url):
    assert looks_like_careers_index(url, page_host="acme.example") is True


def test_careers_index_rejects_cross_host_and_detail_pages():
    assert looks_like_careers_index("https://other.example/careers", page_host="acme.example") is False
    assert looks_like_careers_index("https://acme.example/about", page_host="acme.example") is False


# ===== 取回与解析 =====


async def test_page_with_jsonld_yields_jobs_directly():
    feed = GenericFeed()
    http = FakeHttp({PAGE: _html(_posting_html())})

    page = await feed.fetch_page(http, FeedTarget("generic", PAGE))

    assert page.block == BLOCK_NONE
    assert [job.title for job in page.jobs] == ["大模型应用开发工程师"]
    # 页面只有一条 JSON-LD 岗位但没有 ``url`` 时，用当前地址补齐归属，
    # 否则详情页过滤会把它误认为相关职位并丢掉。
    assert [job.url for job in page.jobs] == [PAGE]
    # 已经读出岗位的页面不再派发链接：它多半是详情页或完整列表页，再排一轮只会白取。
    assert page.next_targets == []


async def test_listing_page_yields_titles_and_still_dispatches_job_links():
    """列表页既给出条目名（锚文本），也继续派发详情页——**两者不是二选一**。

    默认配方给出的是条目名与少量字段、**不含正文**，而详情页可能带着完整的职位描述。
    去重按地址合并，所以不会变成两条。
    """
    feed = GenericFeed()
    http = FakeHttp({
        PAGE: _html(_listing_html("/jobs/1", "/jobs/2", "/about", "https://other.example/jobs/9"))
    })

    page = await feed.fetch_page(http, FeedTarget("generic", PAGE))

    assert [job.url for job in page.jobs] == [
        "https://acme.example/jobs/1",
        "https://acme.example/jobs/2",
    ]
    endpoints = {target.endpoint for target in page.next_targets}
    assert endpoints == {"https://acme.example/jobs/1", "https://acme.example/jobs/2"}
    # 派发出去的深度 +1，编排层据此设上限。
    assert all(target.depth == 1 for target in page.next_targets)
    # 正文为空要如实记账（编排层据此统计 detail_missing），不能因为"有标题了"就当作完整条目。
    assert all(job.description == "" for job in page.jobs)


async def test_fragments_are_stripped_so_the_same_page_is_not_fetched_twice():
    feed = GenericFeed()
    http = FakeHttp({PAGE: _html(_listing_html("/jobs/1#apply", "/jobs/1"))})

    page = await feed.fetch_page(http, FeedTarget("generic", PAGE))

    assert [target.endpoint for target in page.next_targets] == ["https://acme.example/jobs/1"]


async def test_base_href_changes_the_resolution_base():
    """站内页面用 ``<base href>`` 很常见，不认它会解析出一堆错误地址。"""
    feed = GenericFeed()
    http = FakeHttp({PAGE: _html(_listing_html("jobs/1", base="https://acme.example/en/"))})

    page = await feed.fetch_page(http, FeedTarget("generic", PAGE))

    assert [target.endpoint for target in page.next_targets] == ["https://acme.example/en/jobs/1"]


async def test_link_count_is_capped():
    feed = GenericFeed()
    hrefs = [f"/jobs/{index}" for index in range(300)]
    http = FakeHttp({PAGE: _html(_listing_html(*hrefs))})

    page = await feed.fetch_page(http, FeedTarget("generic", PAGE))

    assert len(page.next_targets) == 100


async def test_pagination_without_href_is_delegated_to_the_browser():
    """React 分页器没有 href 时，也必须被当成可继续的列表页。"""
    feed = GenericFeed()
    http = FakeHttp({PAGE: _html(_button_pagination_html())})

    page = await feed.fetch_page(http, FeedTarget("generic", PAGE))

    assert len(page.next_targets) == 1
    target = page.next_targets[0]
    assert target.target_kind == "pagination"
    assert target.endpoint == PAGE
    assert target.params == {
        BROWSER_ACTION_PARAM: "下一页",
        BROWSER_PAGE_PARAM: "2",
    }
    assert target.depth == 0


async def test_disabled_pagination_without_href_is_not_followed():
    feed = GenericFeed()
    http = FakeHttp({PAGE: _html(_button_pagination_html(disabled=True))})

    page = await feed.fetch_page(http, FeedTarget("generic", PAGE))

    assert page.next_targets == []


async def test_careers_index_is_only_followed_from_the_entry_page():
    """栏目页那一跳只在入口发生：再往下就该由岗位链接接手，否则成了遍历整站导航。

    这里用的是 ``/join-us`` 而不是 ``/careers/xxx``：后者**同时命中岗位页标记**，会走岗位
    链接那一支——用它做样例就验不到栏目页这条分支了。
    """
    feed = GenericFeed()
    http = FakeHttp({PAGE: _html(_listing_html("/join-us", "/about"))})

    entry = await feed.fetch_page(http, FeedTarget("generic", PAGE))
    assert [t.endpoint for t in entry.next_targets] == ["https://acme.example/join-us"]
    # **栏目页那一跳不占深度额度**：它换来的是"首页 → 招聘页 → 岗位"，占一层的话岗位就在
    # 第 2 层，会被编排层的深度上限挡掉——只填官网首页的用户一条岗位也拿不到。
    assert entry.next_targets[0].depth == 0

    deeper = await feed.fetch_page(http, FeedTarget("generic", PAGE, depth=1))
    assert deeper.next_targets == [], "非入口页不该再找栏目页"


async def test_the_homepage_chain_actually_reaches_the_job_pages():
    """**首页 → 招聘页 → 岗位，这条链要真的够得到岗位。**

    从前栏目页那一跳占了唯一的深度额度，于是它上面的岗位链接成了第 2 层、被上限全部挡掉：
    用户只填官网首页时，采到的是栏目页上那批**没有正文**的条目名（详情页一个都没取）。
    """
    careers = "https://acme.example/join-us"
    feed = GenericFeed()
    http = FakeHttp(
        {
            PAGE: _html(_listing_html("/join-us", "/about")),
            careers: _html(_listing_html("/jobs/1", "/jobs/2")),
        }
    )

    entry = await feed.fetch_page(http, FeedTarget("generic", PAGE))
    index = await feed.fetch_page(http, entry.next_targets[0])

    depths = {target.endpoint: target.depth for target in index.next_targets}
    assert depths == {
        "https://acme.example/jobs/1": 1,
        "https://acme.example/jobs/2": 1,
    }, "岗位链接必须落在深度上限之内，否则这一整条链白走"


async def test_job_links_win_over_careers_index():
    """有岗位链接时就不要再退回去找栏目页。"""
    feed = GenericFeed()
    http = FakeHttp({PAGE: _html(_listing_html("/join-us", "/jobs/1"))})

    page = await feed.fetch_page(http, FeedTarget("generic", PAGE))

    assert [t.endpoint for t in page.next_targets] == ["https://acme.example/jobs/1"]


async def test_non_html_response_is_reported_not_treated_as_an_empty_page():
    feed = GenericFeed()
    http = FakeHttp({PAGE: FetchResult(block="", status_code=200, text="%PDF-1.4", headers={})})

    page = await feed.fetch_page(http, FeedTarget("generic", PAGE))

    assert page.block == BLOCK_SOFT
    assert "不是网页" in page.detail


async def test_transport_block_is_propagated():
    feed = GenericFeed()
    http = FakeHttp({PAGE: FetchResult(block="rate_limit", status_code=429, detail="限流")})

    page = await feed.fetch_page(http, FeedTarget("generic", PAGE))

    assert page.block == "rate_limit"


async def test_broken_html_does_not_raise():
    feed = GenericFeed()
    http = FakeHttp({PAGE: _html("<div><a href='/jobs/1'>未闭合")})

    page = await feed.fetch_page(http, FeedTarget("generic", PAGE))

    assert page.block == BLOCK_NONE


# ===== 候选与探测 =====


def test_candidates_prefer_the_careers_page():
    feed = GenericFeed()
    candidates = feed.probe_candidates(
        ProbeContext(careers_url=PAGE, homepage_url="https://acme.example/")
    )

    assert candidates[0].confidence == CONFIDENCE_HIGH
    assert candidates[0].target.endpoint == PAGE
    assert candidates[1].confidence == CONFIDENCE_LOW


def test_candidates_deduplicate_when_both_urls_are_the_same():
    feed = GenericFeed()
    candidates = feed.probe_candidates(ProbeContext(careers_url=PAGE, homepage_url=PAGE))
    assert len(candidates) == 1


def test_no_candidates_without_a_url():
    assert GenericFeed().probe_candidates(ProbeContext()) == []


async def test_probe_accepts_a_listing_page_as_a_hit():
    """**核心**：入口页不带结构化数据、只列岗位链接时，也必须算命中。

    否则普通公司招聘页会被一律判成"不支持"，而它们正是通用路径的主要服务对象。
    """
    registry = FeedRegistry()
    registry.register(GenericFeed())
    http = FakeHttp({PAGE: _html(_listing_html("/jobs/1", "/jobs/2"))})

    outcome = await probe_site(http, ProbeContext(careers_url=PAGE), registry=registry)

    assert outcome.state == PROBE_HIT
    assert outcome.job_count == 2


async def test_a_careers_page_we_cannot_read_is_still_usable():
    """**用户说"这是它的招聘页"、这一页又确实取得到，就该认它可用**——哪怕这一级一条岗位
    也没读出来。

    判"未识别"等于把"我们这一级没读出来"说成了"这里没有"：后面还有配方与大模型两级没试，
    而地址长得不像岗位页的站点（``/p/8821``）正是那两级唯一能救回来的一类。从前这里会
    卡在探测——用户连采集按钮都点不动。
    """
    registry = FeedRegistry()
    registry.register(GenericFeed())
    http = FakeHttp({PAGE: _html(_listing_html("/p/8821", "/p/8822"))})

    outcome = await probe_site(http, ProbeContext(careers_url=PAGE), registry=registry)

    assert outcome.state == PROBE_HIT
    assert outcome.job_count == 0
    # 措辞要如实：认下来的是"这个源可用"，不是"这里有岗位"。接下来会发生什么也要说清。
    assert "没有直接读出岗位" in outcome.detail
    assert "大模型" in outcome.detail


async def test_a_guessed_homepage_is_not_accepted_on_an_empty_page():
    """**放行的只有用户直接给的那个地址。**首页是域名猜出来的候选，没有那份证据——
    它读到 0 条就只说明"这个入口没有岗位"，认了它等于任何网址都成了可用的源。
    """
    registry = FeedRegistry()
    registry.register(GenericFeed())
    http = FakeHttp({PAGE: _html(_listing_html("/about", "/contact"))})

    outcome = await probe_site(
        http, ProbeContext(homepage_url=PAGE), registry=registry
    )

    assert outcome.state != PROBE_HIT


async def test_a_page_that_is_not_a_webpage_is_still_not_a_hit():
    """取回来不是网页（PDF、图片、接口）：**"能取到"不等于"能读"**，这个区分不能丢。

    而且它该报「被阻断」而不是「未识别」——后者是"这家公司不用这套系统"的意思，
    而这里的事实是"我们没看到内容"，两句话对用户的下一步指引完全不同。
    """
    registry = FeedRegistry()
    registry.register(GenericFeed())
    http = FakeHttp({PAGE: FetchResult(block=BLOCK_NONE, status_code=200, text="%PDF-1.4", headers={})})

    outcome = await probe_site(http, ProbeContext(careers_url=PAGE), registry=registry)

    assert outcome.state != PROBE_HIT
    assert outcome.state == PROBE_BLOCKED


async def test_transport_detail_survives_a_successful_fetch():
    """取回成功、但传输层有话要说时，那句话**不能丢**。

    真实站点上踩到过：渲染取回的内容被字节上限截断，而这一级在成功分支上把 ``result.detail``
    丢了。于是报告里只剩抽取层那句"这一页没有可辨认的站内链接"——**一句关于页面的假话**，
    而真相是内容在取回时就被截掉了。用户拿着这个假原因去排查，方向从一开始就是错的。
    """
    feed = GenericFeed()
    http = FakeHttp(
        {
            PAGE: FetchResult(
                block="",
                status_code=200,
                text=_html("<p>当前没有在招岗位</p>").text,
                detail="渲染后的页面超过上限已截断，内容可能不完整",
                headers={},
            )
        }
    )

    page = await feed.fetch_page(http, FeedTarget("generic", PAGE))

    assert page.block == BLOCK_NONE
    assert "已截断" in page.detail


async def test_the_page_body_is_attached_to_the_fetched_page():
    """详情页的正文随页面一起交出去（归属由编排层按地址判）。

    这一条守的是**接线**：``extract_page_body`` 本身有它自己的用例，但"它到底有没有被接到
    ``fetch_page`` 的返回上"是另一回事——漏接的话整级静默失效，而报告里只会说"这一页没有
    可辨认的站内链接"，看不出正文那一级压根没跑。
    """
    feed = GenericFeed()
    markup = (
        "<html><body><div class='job'>"
        "<div class='block-title'>职位描述</div>"
        "<div class='block-content'>负责平台广告策略的制定与迭代，结合行业数据给出可执行方案。</div>"
        "<div class='block-title'>职位要求</div>"
        "<div class='block-content'>本科及以上学历，五年以上相关行业经验，沟通能力强。</div>"
        "</div></body></html>"
    )
    http = FakeHttp({PAGE: FetchResult(block="", status_code=200, text=markup, headers={})})

    page = await feed.fetch_page(http, FeedTarget("generic", PAGE))

    assert page.body.startswith("负责平台广告策略")
    assert page.body_requirements.startswith("本科及以上学历")
