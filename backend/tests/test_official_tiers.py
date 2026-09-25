"""三级抽取在编排层的接线：默认配方 → 模型（含成本上限）→ 记忆写回。

四处最容易做错的地方：

- **模型不是在每个读不出东西的页面上都试一次**。五十个详情页各问一次模型是真实存在的花法，
  单页上限挡不住它——所以只有入口页与派发出了岗位链接的页面才轮得到模型。
- **成本上限是按"一次采集"算的**，踩到时要如实记进报告，而不是悄悄继续花。
- **同一条岗位的两次取回要合成一条**：列表页给得出条目名、给不出正文，详情页反过来。
- **公司名由源补上**：适配器只认得地址，不认得"我们采的是哪家公司"。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from urllib.parse import urljoin

import pytest

from app.models.official import BLOCK_NONE
from app.schemas.setting import LLMConfig
from app.services.llm.base import BaseLLMProvider
from app.services.sites.official.base import (
    FeedHttp,
    FeedJob,
    FeedPage,
    FeedTarget,
    FetchResult,
    JobFeed,
    ProbeContext,
)
from app.services.sites.official.collector import (
    MAX_LLM_CALLS_PER_RUN,
    OfficialCollectReport,
    OfficialCollector,
)
from app.services.sites.official.feeds.generic import GenericFeed
from app.services.sites.official.generic.llm_extract import ListingExtractor
from app.services.sites.official.generic.memory import SiteMemory

PAGE = "https://careers.example.com/jobs"

# 默认配方读不出来：链接文字是操作文案，标题在旁边，地址也不像岗位页。
OPAQUE_PAGE = """<ul>
<li class="row"><h3>大模型应用开发工程师</h3><span class="loc">北京</span>
  <a class="act" href="/p/8821">查看详情</a></li>
<li class="row"><h3>算法工程师</h3><span class="loc">上海</span>
  <a class="act" href="/p/8822">查看详情</a></li>
</ul>"""

# 默认配方读得出来：链接文字就是岗位名。
PLAIN_PAGE = """<ul>
<li><a href="/jobs/1">大模型应用开发工程师</a></li>
<li><a href="/jobs/2">算法工程师</a></li>
</ul>"""

# 详情页：没有结构化数据、也没有岗位链接，通用路径从它身上读不出东西。
DETAIL_PAGE = "<article><h1>大模型应用开发工程师</h1><p>职责……</p></article>"

# 岗位地址像岗位页、但锚文本是操作文案——派发得出去，默认配方却读不出标题。
OPAQUE_LINKS_PAGE = '<div><a href="/jobs/1">查看详情</a></div>'


def _posting_html(title: str, description: str) -> str:
    payload = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": title,
        "description": description,
    }
    return (
        "<html><head>"
        f'<script type="application/ld+json">{json.dumps(payload, ensure_ascii=False)}</script>'
        "</head><body></body></html>"
    )



class ScriptedProvider(BaseLLMProvider):
    def __init__(self, *replies: str):
        super().__init__(LLMConfig(base_url="http://fake", model="fake-model"))
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    async def chat(self, messages: list[dict]) -> str:
        self.calls.append(messages)
        index = min(len(self.calls) - 1, len(self.replies) - 1)
        return self.replies[index]

    async def stream_chat(self, messages: list[dict]):  # pragma: no cover - 未用到
        yield ""


def _jobs_reply(*pairs: tuple[int, str]) -> str:
    return json.dumps(
        {"jobs": [{"index": index, "title": title} for index, title in pairs]},
        ensure_ascii=False,
    )


class PageFeed(GenericFeed):
    """把写死的页面喂给**真实的通用路径**（JSON-LD → 默认配方 → 派发链接）。

    刻意不在夹具里自己模拟抽取：这一层要验的正是"真适配器 + 真编排"合起来的行为，
    自己写一遍抽取等于把被测对象换成了另一个实现。
    """

    def __init__(self, pages: dict[str, str], details: dict[str, str] | None = None):
        super().__init__()
        # 相对地址按入口页拼成绝对地址——写死的页面表用相对路径更好读，而取回层拿到的一定是
        # 绝对地址。不归一化的话，页面表的键永远也命中不了，取回全变成 404。
        self._pages = {urljoin(PAGE, key): value for key, value in pages.items()}
        self._details = {urljoin(PAGE, key): value for key, value in (details or {}).items()}

    async def fetch_page(self, http: FeedHttp, target: FeedTarget, *, cursor: str = "") -> FeedPage:
        del http
        return await super().fetch_page(
            _StaticHttp(self._pages, self._details), target, cursor=cursor
        )


class _StaticHttp(FeedHttp):
    """写死的页面表。``details`` 用来伪造**传输层自己要说的话**（截断、渲染失败…）。"""

    def __init__(self, pages: dict[str, str], details: dict[str, str] | None = None):
        self._pages = pages
        self._details = details or {}

    async def request(self, method, url, *, params=None, json_body=None, headers=None,
                      max_bytes=None) -> FetchResult:
        del method, params, json_body, headers, max_bytes
        markup = self._pages.get(url)
        if markup is None:
            return FetchResult(block="not_found", status_code=404)
        return FetchResult(
            block=BLOCK_NONE,
            status_code=200,
            text=markup,
            headers={},
            detail=self._details.get(url, ""),
        )


class WideFeed(JobFeed):
    """一批平行的、都读不出岗位的页面，每个都派发下一批同样读不出岗位的页面。

    **它存在是因为真实通用路径表达不了这个形状**：``GenericFeed`` 派发出去的子页在第 1 层，
    子页再派发就是第 2 层，会被深度上限挡掉整轮采集。这里的子页一律只派发**已经在队列里过**
    的地址（第 1 层），所以既满足"够格问模型"（有派发），又不会触发深度上限。
    """

    key = "wide"
    display_name = "平行页面"
    supports_recipes = True

    def __init__(self, pages: dict[str, str], dispatch: dict[str, list[str]]):
        self._pages = pages
        self._dispatch = dispatch

    def probe_candidates(self, ctx: ProbeContext) -> list:  # pragma: no cover - 采集不走探测
        del ctx
        return []

    async def fetch_page(self, http: FeedHttp, target: FeedTarget, *, cursor: str = "") -> FeedPage:
        del http, cursor
        return FeedPage(
            jobs=[],
            next_targets=[
                FeedTarget(feed_key=self.key, endpoint=url, depth=1)
                for url in self._dispatch.get(target.endpoint, [])
            ],
            block=BLOCK_NONE,
            status_code=200,
            raw=self._pages.get(target.endpoint, ""),
        )


class UnusedHttp(FeedHttp):
    async def request(self, method, url, **kwargs) -> FetchResult:  # pragma: no cover
        raise AssertionError("脚本适配器不该走到传输层")


@dataclass
class FakeSite:
    company: str = "示例公司"
    endpoint: str = PAGE
    params: dict = field(default_factory=dict)
    min_interval_seconds: int = 0
    max_per_hour: int = 120
    recipe: dict = field(default_factory=dict)


async def _run(session, feed, *, site=None, extractor=None, **kwargs):
    return await OfficialCollector().run(
        session=session,
        site=site or FakeSite(),
        feed=feed,
        http=UnusedHttp(),
        extractor=extractor,
        **kwargs,
    )


# ===== 默认配方这一级 =====


async def test_the_default_recipe_fills_a_page_the_adapter_could_not_read(db_session):
    """没有 JSON-LD 的列表页从前一个岗位也读不出来；默认配方让它有结果。"""
    feed = PageFeed({PAGE: PLAIN_PAGE, "/jobs/1": DETAIL_PAGE, "/jobs/2": DETAIL_PAGE})

    report = await _run(db_session, feed)

    assert report.collected == 2
    assert report.llm_calls == 0, "白读得出来的页面不该花钱"


async def test_staged_jobs_carry_the_company_from_the_source(db_session):
    """公司名由源决定，不由页面决定——我们采的就是这家公司。"""
    from app.models.material import CandidateJob

    feed = PageFeed({PAGE: PLAIN_PAGE, "/jobs/1": DETAIL_PAGE, "/jobs/2": DETAIL_PAGE})
    await _run(db_session, feed)

    staged = db_session.query(CandidateJob).all()
    assert {job.company for job in staged} == {"示例公司"}


# ===== 模型这一级 =====


async def test_the_model_is_asked_for_a_page_the_default_recipe_cannot_read(db_session):
    provider = ScriptedProvider(_jobs_reply((1, "大模型应用开发工程师"), (2, "算法工程师")))
    feed = PageFeed({PAGE: OPAQUE_PAGE})

    report = await _run(db_session, feed, extractor=ListingExtractor(provider))

    assert report.collected == 2
    assert report.llm_calls == 1
    assert report.recipes_learned == 1
    assert len(provider.calls) == 1


async def test_a_learned_recipe_spares_the_next_run(db_session):
    """**为模型只付一次钱**——第二次采集走配方，零调用。"""
    provider = ScriptedProvider(_jobs_reply((1, "大模型应用开发工程师"), (2, "算法工程师")))
    site = FakeSite()
    feed = PageFeed({PAGE: OPAQUE_PAGE})

    first = await _run(db_session, feed, site=site, extractor=ListingExtractor(provider))
    # 编排层把记忆写在 report 上，由调用方写回源；这里模拟写回。
    site.recipe = first.memory.to_blob()
    second = await _run(db_session, feed, site=site, extractor=ListingExtractor(provider))

    assert second.collected == 2
    assert second.llm_calls == 0
    assert len(provider.calls) == 1


async def test_detail_pages_never_reach_the_model(db_session):
    """**五十个详情页各问一次模型是真实存在的花法**：单页上限挡不住它。

    详情页读不出东西是死胡同，不是"我们没读懂列表页"。
    """
    provider = ScriptedProvider(_jobs_reply())
    feed = PageFeed({PAGE: OPAQUE_LINKS_PAGE, "/jobs/1": DETAIL_PAGE})

    report = await _run(db_session, feed, extractor=ListingExtractor(provider))

    # 入口页与它派发出去的详情页都真的取过了——否则这条断言什么也没证明。
    assert report.pages == 2
    assert report.llm_calls == 1
    assert len(provider.calls) == 1


async def test_the_model_call_cap_is_per_run_and_reported(db_session):
    """踩到上限要**如实记进报告**，而不是悄悄继续花用户的钱。

    没有这个按"一次采集"算的上限，下面二十来个读不出东西的页面会各问一次模型——
    而单页上限对此完全无感。
    """
    children = [f"/p/{n}" for n in range(1, 21)]
    pages = {PAGE: OPAQUE_PAGE}
    dispatch = {PAGE: children}
    for url in children:
        pages[url] = OPAQUE_PAGE
        # 子页也派发（指向第一个子页，已经在队列里过）——这样它们**同样够格**问模型，
        # 而不会产生第 2 层的地址。
        dispatch[url] = [children[0]]
    feed = WideFeed(pages, dispatch)
    provider = ScriptedProvider(_jobs_reply())

    report = await _run(db_session, feed, extractor=ListingExtractor(provider))

    assert report.pages == 21, "用例前提：这些页面确实都被取过"
    assert report.llm_calls == MAX_LLM_CALLS_PER_RUN
    assert len(provider.calls) == MAX_LLM_CALLS_PER_RUN
    assert any("上限" in note for note in report.extraction_notes)


async def test_without_a_model_the_report_says_the_page_could_not_be_read(db_session):
    """没配模型时如实说明，不假装试过了——"读不出来"与"没试"对用户是两件事。"""
    feed = PageFeed({PAGE: OPAQUE_PAGE})

    report = await _run(db_session, feed, extractor=None)

    assert report.llm_calls == 0
    assert report.collected == 0
    assert any("没有配置" in note for note in report.extraction_notes)


async def test_extraction_notes_name_the_page_and_the_method(db_session):
    """报告要能回答"这一页是怎么读出来的"。"""
    provider = ScriptedProvider(_jobs_reply())
    feed = PageFeed({PAGE: OPAQUE_PAGE})

    report = await _run(db_session, feed, extractor=ListingExtractor(provider))

    assert any(PAGE in note for note in report.extraction_notes)


async def test_a_page_the_adapter_read_needs_no_note(db_session):
    """适配器自己就读出来了的页面不留说明——没有要解释的成本。"""
    feed = PageFeed({PAGE: PLAIN_PAGE, "/jobs/1": DETAIL_PAGE, "/jobs/2": DETAIL_PAGE})

    report = await _run(db_session, feed)

    assert report.extraction_notes == []


# ===== 记忆 =====


async def test_memory_is_only_marked_changed_when_something_changed(db_session):
    """没改就不写库：每次采集都写一遍会让 updated_at 失去意义。"""
    feed = PageFeed({PAGE: PLAIN_PAGE, "/jobs/1": DETAIL_PAGE, "/jobs/2": DETAIL_PAGE})

    report = await _run(db_session, feed)

    assert report.memory is not None
    assert report.memory.changed is False


async def test_an_unreadable_page_is_remembered(db_session):
    provider = ScriptedProvider(_jobs_reply())
    feed = PageFeed({PAGE: OPAQUE_PAGE})

    report = await _run(db_session, feed, extractor=ListingExtractor(provider))

    assert report.memory is not None
    assert report.memory.changed is True
    assert report.memory.should_skip_model(PAGE, OPAQUE_PAGE)


async def test_an_interface_adapter_gets_no_memory(db_session):
    """接口型适配器读的是契约，没有"页面结构"可记。"""

    class ApiFeed(PageFeed):
        supports_recipes = False

    report = await _run(db_session, ApiFeed({PAGE: PLAIN_PAGE}))

    assert report.memory is None


@pytest.mark.parametrize("blob", [None, {}, {"schema": 99}])
async def test_a_broken_recipe_blob_does_not_break_the_run(db_session, blob):
    """旧的或损坏的配方**当成没有**，而不是让采集失败。"""
    feed = PageFeed({PAGE: PLAIN_PAGE, "/jobs/1": DETAIL_PAGE, "/jobs/2": DETAIL_PAGE})

    report = await _run(db_session, feed, site=FakeSite(recipe=blob))

    assert report.collected == 2


async def test_a_stored_recipe_from_a_previous_run_is_reused(db_session):
    """把上一轮归纳的配方写回源，下一轮就该直接用它。"""
    provider = ScriptedProvider(_jobs_reply((1, "大模型应用开发工程师"), (2, "算法工程师")))
    feed = PageFeed({PAGE: OPAQUE_PAGE})
    first = await _run(db_session, feed, extractor=ListingExtractor(provider))

    remembered = SiteMemory.from_blob(first.memory.to_blob())
    assert remembered.listing is not None


# ===== 同一条岗位的两次取回合并 =====


async def test_the_detail_body_fills_in_what_the_listing_could_not_give(db_session):
    """**列表页给条目名、详情页给正文——该合成一条。**

    这正是默认配方带出来的新情况：从前列表页读不出任何东西，而详情页若也没有结构化数据，
    整次采集就是 0 条。
    """
    from app.models.material import CandidateJob

    listing = '<ul><li><a href="/jobs/1">大模型应用开发工程师</a></li></ul>'
    detail = _posting_html("大模型应用开发工程师", "<p>负责大模型应用的设计与落地</p>")
    feed = PageFeed({PAGE: listing, "/jobs/1": detail})

    report = await _run(db_session, feed)

    staged = db_session.query(CandidateJob).all()
    assert len(staged) == 1, "同一岗位不该在暂存区出现两条"
    assert staged[0].title == "大模型应用开发工程师"
    assert "负责大模型应用的设计与落地" in staged[0].description
    # 两次取回都算抓到了，但只落一条库。
    assert report.collected == 1
    assert report.stored == 1
    assert report.detail_missing == 0, "正文补上了，就不该再记一笔「没有正文」"


async def test_filling_never_overwrites_a_value_that_is_already_there(db_session):
    """**只补空，不覆盖**：先到的那次拿到的值不能被后到的那次的空字段换掉。"""
    from app.models.material import CandidateJob

    existing = CandidateJob(
        title="大模型应用开发工程师", company="示例公司", location="北京", description=""
    )
    db_session.add(existing)
    db_session.flush()
    report = OfficialCollectReport()
    report.detail_missing = 1

    OfficialCollector._fill_blank(
        report,
        existing,
        FeedJob(title="大模型应用开发工程师", location="上海", description="职责……"),
    )

    assert existing.location == "北京", "已有值被覆盖了"
    assert existing.description == "职责……", "空字段没有被补上"
    # 正文补上了，那一笔「没有正文」要退回去，否则报告会一直说缺正文。
    assert report.detail_missing == 0


def test_the_same_url_wins_over_a_different_title():
    """按地址合并：列表页与详情页对同一个岗位的写法常常不一样，按标题会看成两条。"""
    from app.services.sites.official.collector import StagedIndex

    index = StagedIndex()
    index.add(FeedJob(title="大模型应用开发工程师", url="https://x.com/jobs/1"), "first")

    found = index.find(
        FeedJob(title="大模型应用开发工程师（北京）", url="https://x.com/jobs/1/#apply")
    )

    assert found == "first"


def test_a_record_without_a_url_can_still_be_recognised_by_title():
    """结构化数据里常常不带 ``url``，那条记录只能靠标题认。"""
    from app.services.sites.official.collector import StagedIndex

    index = StagedIndex()
    index.add(FeedJob(title="大模型应用开发工程师", company="示例公司"), "first")

    assert index.find(FeedJob(title=" 大模型应用开发工程师 ", company="示例公司")) == "first"


def test_two_jobs_with_the_same_title_but_different_urls_stay_separate():
    """**同名不同地址是两条**：同一家公司不同城市各招一个同名岗位很常见。"""
    from app.services.sites.official.collector import StagedIndex

    index = StagedIndex()
    index.add(FeedJob(title="算法工程师", company="示例公司", url="https://x.com/jobs/1"), "first")

    assert index.find(FeedJob(title="算法工程师", company="示例公司", url="https://x.com/jobs/2")) is None




async def test_the_generic_path_does_not_claim_it_reached_the_last_page(db_session):
    """**这一级不翻页，就不能在依据里说"已翻到列表最后一页"。**

    通用路径从没有"第几页"的概念——它靠页面里有没有可跟进的链接。队列走空只说明我们跟进完了
    所有认得出来的链接，而那句话会让用户以为这个列表就是全部。措辞只在终止那一层分流，
    判定一个字都没动。
    """
    feed = PageFeed({PAGE: PLAIN_PAGE, "/jobs/1": DETAIL_PAGE, "/jobs/2": DETAIL_PAGE})

    report = await _run(db_session, feed)

    assert report.reconcile is not None
    layers = {layer["layer"]: layer["detail"] for layer in report.reconcile.layers}
    assert "不翻页" in layers["termination"]
    assert "已翻到列表最后一页" not in layers["termination"]


async def test_a_paginating_feed_keeps_the_original_wording(db_session):
    """接口型适配器照旧——它确实知道"没有下一页"是接口的契约。"""

    class CursorFeed(PageFeed):
        paginates = True

    # 详情页也要给：派发出去却 404 会变成"翻页信号矛盾"，那条终止说明是另一回事。
    feed = CursorFeed({PAGE: PLAIN_PAGE, "/jobs/1": DETAIL_PAGE, "/jobs/2": DETAIL_PAGE})

    report = await _run(db_session, feed)

    assert report.reconcile is not None
    layers = {layer["layer"]: layer["detail"] for layer in report.reconcile.layers}
    assert layers["termination"] == "已翻到列表最后一页"


async def test_the_report_carries_what_the_transport_said(db_session):
    """传输层说的话（这里伪造的是"渲染后被截断"）必须出现在报告的「读取方式」里。

    真实站点上踩到过：那一页渲染后的 DOM 有 6.8 MB，其中 5.8 MB 是内联 CSS，字节上限**从头截**
    之后正文一个链接都不剩。抽取层当然读不出来，于是报告写"这一页没有可辨认的站内链接"——
    **一句关于页面的假话**：页面里明明有 18 个岗位链接，问题出在取回那一步。

    传输层当时其实是说了的（"渲染后的页面超过上限已截断"），是这一路的两个环节把它丢了。
    所以这条用例守的是：**取回层的说明要一路走到用户看得见的地方**。
    """
    feed = PageFeed(
        {PAGE: OPAQUE_PAGE},
        details={PAGE: "渲染后的页面超过上限已截断，内容可能不完整"},
    )

    report = await _run(db_session, feed, extractor=None)

    assert report.collected == 0
    assert any("已截断" in note for note in report.extraction_notes), report.extraction_notes
    # 抽取层那句也要在：两句话说的是两件事（怎么读的 / 取回时发生了什么）。
    assert any("没有配置" in note for note in report.extraction_notes)
