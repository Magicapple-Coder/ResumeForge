"""官网采集编排：翻页、去重、限速、中断，以及对账结论。

其中 ``test_already_known_jobs_still_count_as_collected`` 守的是最容易误报的一条——
命中大量重复时，报告绝不能说"漏抓"，因为那些岗位**确实被这一次采集抓到了**。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.models.job import Job
from app.models.material import CandidateJob
from app.models.official import (
    BLOCK_NONE,
    BLOCK_RATE_LIMIT,
    VERDICT_COMPLETE,
    VERDICT_INCOMPLETE,
    VERDICT_UNKNOWN,
)
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
    MAX_FETCH_DEPTH,
    CollectCancelled,
    OfficialCollector,
)
from app.services.sites.official.reconcile import (
    TERMINATION_JOB_LIMIT,
    classify_termination,
    input_from_dict,
    input_to_dict,
)


class ScriptedFeed(JobFeed):
    """按脚本返回页面，记录每次请求用的游标与**取过哪些地址**。"""

    key = "scripted"
    display_name = "脚本适配器"
    provides_total = True

    def __init__(self, pages: list[FeedPage]):
        self._pages = pages
        self.cursors: list[str] = []
        self.requested: list[str] = []

    def probe_candidates(self, ctx: ProbeContext) -> list:  # pragma: no cover - 采集不走探测
        del ctx
        return []

    async def fetch_page(self, http: FeedHttp, target, *, cursor: str = "") -> FeedPage:
        del http
        self.cursors.append(cursor)
        self.requested.append(target.endpoint)
        index = min(len(self.cursors) - 1, len(self._pages) - 1)
        return self._pages[index]


class UnusedHttp(FeedHttp):
    async def request(self, method, url, **kwargs) -> FetchResult:  # pragma: no cover
        raise AssertionError("脚本适配器不该走到传输层")


@dataclass
class FakeSite:
    company: str = "示例公司"
    endpoint: str = "https://api.example/jobs"
    params: dict = field(default_factory=dict)
    min_interval_seconds: int = 0
    max_per_hour: int = 120


class FakeClock:
    """注入的时钟与睡眠：限速逻辑要能在毫秒级验证，而不是真的等十几秒。"""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _job(index: int, **overrides) -> FeedJob:
    payload = {
        "title": f"岗位 {index}",
        "company": "示例公司",
        "url": f"https://careers.example/jobs/{index}",
        "description": f"这是第 {index} 个岗位的职位描述",
    }
    payload.update(overrides)
    return FeedJob(**payload)


def _page(jobs: list[FeedJob], **overrides) -> FeedPage:
    payload = {"jobs": jobs, "block": BLOCK_NONE, "has_more": False, "cursor": ""}
    payload.update(overrides)
    return FeedPage(**payload)


async def _run(feed: JobFeed, session, site: FakeSite | None = None, **kwargs):
    collector_kwargs = ("max_pages", "max_jobs")
    collector = OfficialCollector(
        **{k: v for k, v in kwargs.items() if k in collector_kwargs}
    )
    run_kwargs = {k: v for k, v in kwargs.items() if k not in collector_kwargs}
    return await collector.run(
        session=session,
        site=site or FakeSite(),
        feed=feed,
        http=UnusedHttp(),
        **run_kwargs,
    )


# ===== 正常路径 =====


async def test_collects_stages_and_reconciles_as_complete(db_session):
    feed = ScriptedFeed([_page([_job(1), _job(2)], total_hint=2)])

    report = await _run(feed, db_session)

    assert report.collected == 2
    assert report.stored == 2
    assert report.reconcile is not None
    assert report.reconcile.verdict == VERDICT_COMPLETE
    assert db_session.query(CandidateJob).count() == 2


async def test_staged_candidates_are_marked_as_official_source(db_session):
    feed = ScriptedFeed([_page([_job(1)])])
    await _run(feed, db_session)

    candidate = db_session.query(CandidateJob).one()
    assert candidate.title == "岗位 1"
    assert candidate.source_url == "https://careers.example/jobs/1"
    assert "职位描述" in candidate.description


async def test_empty_board_is_reconciled_complete_with_zero(db_session):
    """真的没有岗位时，"0 条"配合总数 0 是一个**已确认**的结论，不是"无法确认"。"""
    feed = ScriptedFeed([_page([], total_hint=0)])

    report = await _run(feed, db_session)

    assert report.collected == 0
    assert report.reconcile is not None
    assert report.reconcile.verdict == VERDICT_COMPLETE


# ===== 去重与账目口径 =====


async def test_already_known_jobs_still_count_as_collected(db_session):
    """**核心口径**：已在库里的岗位仍然算"抓到了"，只是不算"新入库"。

    用入库条数去对总数，会把"命中大量重复"误报成"漏抓了大量岗位"——一个让用户白跑一趟的
    假警报。所以对账比的是 ``collected``。
    """
    db_session.add(
        Job(title="岗位 1", company="示例公司", source_url="https://careers.example/jobs/1")
    )
    db_session.commit()
    feed = ScriptedFeed([_page([_job(1), _job(2)], total_hint=2)])

    report = await _run(feed, db_session)

    assert report.collected == 2, "已在库里的岗位也必须计入'抓到'"
    assert report.stored == 1
    assert report.skipped == 1
    assert report.reconcile is not None
    assert report.reconcile.verdict == VERDICT_COMPLETE, "重复不该被误报成漏抓"


async def test_existing_candidate_is_backfilled_from_a_job_detail(db_session):
    """重复采集命中旧候选时，详情页返回的 JD 仍要回填。"""
    db_session.add(
        CandidateJob(
            title="岗位 1",
            company="示例公司",
            source_url="https://careers.example/jobs/1",
            description="",
            requirements="",
        )
    )
    db_session.commit()

    listing = _page(
        [_job(1, description="")],
        next_targets=[FeedTarget("scripted", "https://careers.example/jobs/1", depth=1)],
    )
    detail = _page(
        [
            _job(
                1,
                description="详情页职位描述",
                requirements="详情页任职要求",
            )
        ]
    )
    report = await _run(ScriptedFeed([listing, detail]), db_session)

    candidate = db_session.query(CandidateJob).one()
    assert candidate.description == "详情页职位描述"
    assert candidate.requirements == "详情页任职要求"
    assert report.collected == 1
    assert report.stored == 0
    assert report.skipped == 2
    assert report.detail_missing == 0


def test_generic_detail_page_does_not_create_related_job_candidates():
    feed = ScriptedFeed([])
    feed.supports_recipes = True
    target = FeedTarget("generic", "https://careers.example/jobs/1", depth=1)
    page = _page(
        [
            _job(1, url=target.endpoint),
            _job(2, url="https://careers.example/jobs/2"),
        ],
        body="正文仍应保留给当前岗位",
    )

    filtered = OfficialCollector._restrict_generic_detail_jobs(page, target, feed)

    assert [job.title for job in filtered.jobs] == ["岗位 1"]
    assert filtered.body == page.body
    assert filtered.next_targets == []


async def test_duplicates_within_one_run_are_not_double_counted(db_session):
    """同一次采集里翻页重叠导致的重复，只算一条。"""
    feed = ScriptedFeed([_page([_job(1), _job(1)], total_hint=1)])

    report = await _run(feed, db_session)

    assert report.collected == 1
    assert report.skipped == 1


async def test_job_already_in_staging_is_skipped(db_session):
    feed = ScriptedFeed([_page([_job(1)], total_hint=1)])
    await _run(feed, db_session)
    db_session.commit()

    feed2 = ScriptedFeed([_page([_job(1)], total_hint=1)])
    report = await _run(feed2, db_session)

    assert report.collected == 1
    assert report.stored == 0
    assert db_session.query(CandidateJob).count() == 1, "暂存区堆出了重复候选"


# ===== 翻页 =====


async def test_pagination_follows_the_cursor(db_session):
    feed = ScriptedFeed(
        [
            _page([_job(1)], has_more=True, cursor="page-2"),
            _page([_job(2)], has_more=False),
        ]
    )

    report = await _run(feed, db_session)

    assert feed.cursors == ["", "page-2"]
    assert report.collected == 2
    assert report.pages == 2


async def test_has_more_without_cursor_is_not_treated_as_the_end(db_session):
    """站点说"还有下一页"却没给游标：我们无法继续，**这不算抓到底了**。"""
    feed = ScriptedFeed([_page([_job(1)], has_more=True, cursor="")])

    report = await _run(feed, db_session)

    assert report.pages == 1
    assert report.last_has_more is True
    assert report.stopped_reason
    assert report.reconcile is not None
    assert report.reconcile.verdict == VERDICT_UNKNOWN


async def test_reaching_the_page_limit_is_not_the_end(db_session):
    feed = ScriptedFeed([_page([_job(index)], has_more=True, cursor=f"c{index}") for index in range(5)])

    report = await _run(feed, db_session, max_pages=2)

    assert report.pages == 2
    assert report.reached_page_limit is True
    assert report.reconcile is not None
    assert report.reconcile.verdict != VERDICT_COMPLETE


# ===== 队列：列表页 → 详情页 =====


async def test_next_targets_are_followed(db_session):
    """列表页不带岗位、只派发详情页地址，这是普通公司招聘页的形状。"""
    listing = _page(
        [],
        next_targets=[
            FeedTarget(feed_key="scripted", endpoint="https://x.example/jobs/1", depth=1),
            FeedTarget(feed_key="scripted", endpoint="https://x.example/jobs/2", depth=1),
        ],
    )
    detail_one = _page([_job(1, url="https://x.example/jobs/1")])
    detail_two = _page([_job(2, url="https://x.example/jobs/2")])
    feed = ScriptedFeed([listing, detail_one, detail_two])

    report = await _run(feed, db_session)

    assert report.collected == 2
    assert report.pages == 3, "1 次列表页 + 2 次详情页"
    assert report.reconcile is not None
    assert report.reconcile.verdict != VERDICT_INCOMPLETE


async def test_dispatcher_pages_do_not_pollute_the_count_ledger(db_session):
    """派发地址的那一次没有条数可比，记进账目会凭空造出"页面自称 0 条"的假漂移。"""
    listing = _page([], next_targets=[FeedTarget("scripted", "https://x.example/jobs/1", depth=1)])
    feed = ScriptedFeed([listing, _page([_job(1)])])

    report = await _run(feed, db_session)

    # 只有详情页那次进了账目。
    assert report.page_counts == [(1, None)]


async def test_depth_limit_skips_the_deep_link_without_stopping(db_session):
    """比自己预期更深的地址**只是不跟进**，采集要继续。

    这一条曾经写反过：越深的地址被记进了 ``stopped_reason``，而那个字段的语义是"整次采集
    就此中止"。于是一个详情页里的"相关岗位"链接就足以让采集停在第一页，报告里只说"层级超过
    上限"，看起来像站点的问题。深度上限要防的是**无限递归**（自身链接成环），防它的办法是
    不跟进那一个链接，不是不采了。
    """
    listing = _page(
        [],
        next_targets=[
            FeedTarget("scripted", "https://x.example/deeper", depth=MAX_FETCH_DEPTH + 1),
            FeedTarget("scripted", "https://x.example/ok", depth=1),
        ],
    )
    feed = ScriptedFeed([listing, _page([_job(99)])])

    report = await _run(feed, db_session)

    assert "https://x.example/deeper" not in feed.requested, "超深的地址不该被取"
    assert "https://x.example/ok" in feed.requested, "其余地址要继续取，不该就此中止"
    assert report.deep_links_skipped == 1
    assert report.stopped_reason == "", "跳过深链不是中止"
    assert report.collected == 1


async def test_the_same_target_is_never_fetched_twice(db_session):
    """站点自身链接成环时，同一个地址不能被反复取。"""
    listing = _page(
        [],
        next_targets=[
            FeedTarget("scripted", "https://x.example/a", depth=1),
            FeedTarget("scripted", "https://x.example/a", depth=1),
        ],
    )
    feed = ScriptedFeed([listing, _page([_job(1)])])

    report = await _run(feed, db_session)

    assert report.pages == 2, "重复地址只取一次"
    assert feed.cursors == ["", ""]


async def test_entry_page_is_not_refetched_when_a_detail_links_back(db_session):
    """详情页指回入口是极常见的站点结构，入口不该因此被取第二次。"""
    site = FakeSite(endpoint="https://careers.example/jobs")
    entry = _page(
        [],
        next_targets=[
            FeedTarget("scripted", "https://careers.example/jobs/1", depth=1),
            # 指回入口本身——地址与入口**完全一致**，这才验得到判重。
            FeedTarget("scripted", site.endpoint, depth=1),
        ],
    )
    feed = ScriptedFeed([entry, _page([_job(1)])])

    report = await _run(feed, db_session, site=site)

    assert report.pages == 2, "入口被重复取了一次"


async def test_queue_running_dry_is_the_end(db_session):
    """队列走空是唯一不需要额外信号即可成立的终止条件。"""
    feed = ScriptedFeed([_page([_job(1)])])

    report = await _run(feed, db_session)

    assert report.reached_page_limit is False
    assert report.stopped_reason == ""
    assert report.reconcile is not None
    assert report.reconcile.termination is not None
    assert report.reconcile.termination.state == "exhausted"


# ===== 阻断 =====


async def test_blocked_page_stops_pagination_and_is_recorded(db_session):
    feed = ScriptedFeed(
        [
            _page([_job(1)], has_more=True, cursor="c2", total_hint=10),
            _page([], block=BLOCK_RATE_LIMIT, detail="站点限流"),
        ]
    )

    report = await _run(feed, db_session)

    assert report.pages == 2, "被阻断后不该继续翻页"
    assert report.blocked is True
    assert report.stopped_reason == "站点限流"
    assert report.reconcile is not None
    assert report.reconcile.verdict == VERDICT_INCOMPLETE, "声明 10 条只拿到 1 条"
    assert report.reconcile.missing == 9


# ===== 限速 =====


async def test_throttle_uses_the_stricter_of_site_and_crawl_delay(db_session):
    """站点声明的 crawl-delay 与本地画像取**较大者**：站点划的底线不能被我们的默认值覆盖。"""
    feed = ScriptedFeed([_page([_job(1)], has_more=True, cursor="c2"), _page([_job(2)])])
    clock = FakeClock()

    await _run(
        feed,
        db_session,
        site=FakeSite(min_interval_seconds=2),
        crawl_delay_seconds=5,
        clock=clock,
        sleeper=clock.sleep,
    )

    # 两次请求之间等的是 5（较大者），不是 2。
    assert clock.slept == [5.0]


async def test_local_interval_applies_when_site_declares_no_delay(db_session):
    feed = ScriptedFeed([_page([_job(1)], has_more=True, cursor="c2"), _page([_job(2)])])
    clock = FakeClock()

    await _run(
        feed,
        db_session,
        site=FakeSite(min_interval_seconds=3),
        crawl_delay_seconds=None,
        clock=clock,
        sleeper=clock.sleep,
    )

    assert clock.slept == [3.0]


# ===== 中断与漂移 =====


async def test_cancellation_stops_cleanly_and_reconciles(db_session):
    """用户点停止：干净地停下来并给出对账（此时必然是"没走完"）。"""
    feed = ScriptedFeed([_page([_job(index)], has_more=True, cursor=f"c{index}") for index in range(5)])
    calls = {"count": 0}

    def checkpoint() -> None:
        calls["count"] += 1
        if calls["count"] > 4:
            raise CollectCancelled

    report = await _run(feed, db_session, checkpoint=checkpoint)

    assert report.stopped_reason == "已停止"
    assert report.reconcile is not None
    assert report.reconcile.verdict != VERDICT_COMPLETE


async def test_detail_missing_is_counted_for_empty_descriptions(db_session):
    """正文为空是站点漂移唯一留下的痕迹——不计数就完全看不见。"""
    feed = ScriptedFeed([_page([_job(1, description=""), _job(2)])])

    report = await _run(feed, db_session)

    assert report.stored == 2, "缺 JD 也仍然要暂存：标题/公司/链接都已拿到"
    assert report.detail_missing == 1


async def test_structure_drift_turns_the_verdict_uncertain(db_session):
    """一整页只解析出 1 条、页面却写着 5 条：选择器开始失效，结论必须降级。"""
    feed = ScriptedFeed([_page([_job(1)], claimed_count=5, total_hint=None)])

    report = await _run(feed, db_session)

    assert report.reconcile is not None
    assert report.reconcile.verdict == VERDICT_UNKNOWN


async def test_no_anchor_no_claimed_counts_is_unknown(db_session):
    feed = ScriptedFeed([_page([_job(1)])])

    report = await _run(feed, db_session)

    assert report.total_hint is None
    assert report.reconcile is not None
    assert report.reconcile.verdict == VERDICT_UNKNOWN


# ===== 同一条岗位的两次取回（合并与计数）=====


async def test_a_summary_then_a_full_version_of_the_same_job_counts_once(db_session):
    """**同一页里先读到无地址的摘要、再读到带地址的完整版，是一条岗位。**

    这是"两边至少有一边没有地址就走标题"那一支的原始动机。若地址对不上就直接放弃合并，
    这条会被计两次：站点说 2 条、真实岗位 1 条，报告就会宣称「已确认为全量：站点声明的
    2 条岗位全部抓到」——而暂存区里只有一条。
    """
    summary = _job(0, url="", description="")
    full = _job(0)
    feed = ScriptedFeed([_page([summary, full])])

    report = await _run(feed, db_session)

    assert report.collected == 1, "同一条岗位被计了两次"
    assert report.stored == 1
    # 摘要版先落库，完整版的正文要补进去。
    staged = db_session.query(CandidateJob).one()
    assert staged.description == "这是第 0 个岗位的职位描述"


def test_conflicting_records_are_never_merged_by_title_alone():
    """**只靠标题认的时候，字段一冲突就不合并。**

    两条没有地址、同标题同公司、但地点不同的记录，是两个岗位；合并会让其中一条彻底消失，
    还会把它家的字段补到另一家那行上——那正是"只补空"这条规则最不能出的错。

    （注意：同标题同公司的岗位最终**仍会被项目全局的去重规则** ``find_job_by_identity`` 合并，
    那是全应用统一的口径、不属于本模块。这里守的是**本模块自己**那道合并判据。）
    """
    from types import SimpleNamespace

    from app.services.sites.official.collector import StagedIndex

    index = StagedIndex()
    # 真实流程里这里是一条已落库的候选记录（有 location 等字段），用一个最小替身即可。
    index.add(
        FeedJob(title="算法工程师", company="示例公司", location="北京"),
        SimpleNamespace(location="北京", posted_at="", job_type="", salary=""),
    )

    conflicting = FeedJob(title="算法工程师", company="示例公司", location="上海")
    assert index.find(conflicting) is None

    # 地点缺一边时不冲突：那多半就是同一条（先读到摘要、再读到完整版）。
    assert index.find(FeedJob(title="算法工程师", company="示例公司")) is not None


def test_two_postings_without_urls_are_counted_separately(db_session):
    """计数键里要带上能区分两条岗位的字段，不能只用标题。

    只用标题当键时，第二条会被当成"这一轮已经数过"直接跳过——**既不落库也不计数**，
    而报告还会说"只抓到 1 条、站点声明 2 条"，凭空造出一句漏抓警报。
    """
    from app.services.sites.official.collector import StagedIndex

    first = FeedJob(title="算法工程师", company="示例公司", location="北京")
    second = FeedJob(title="算法工程师", company="示例公司", location="上海")

    assert StagedIndex.key_for(first) != StagedIndex.key_for(second)
    # 反过来：同一条重复出现时键必须相同，否则同一次采集里会重复计数。
    assert StagedIndex.key_for(first) == StagedIndex.key_for(
        FeedJob(title="算法工程师", company="示例公司", location="北京")
    )


async def test_a_sitemap_on_another_host_is_not_compared(db_session):
    """**站点地图按站点自己的主机取，而岗位地址常常在另一个主机上**（招聘系统托管）。

    用户填 ``acme.com/careers``、探测识别出托管在某招聘系统的职位板，抓到的地址全在
    ``boards.…`` 上。两个集合永远不相交，差额于是等于**整张地图**：报告会写"N 个岗位页
    没抓到"，核实完还会升级成"已确认不全"——而实际一条都没漏。

    两个地址空间对不上时，这一层没有可比对的依据，如实说明比硬比强。
    """
    feed = ScriptedFeed([_page([_job(1), _job(2)], total_hint=2)])
    expected = frozenset({"https://acme.example/jobs/1", "https://acme.example/jobs/2"})

    report = await _run(feed, db_session, expected_urls=expected)

    assert report.reconcile_input is not None
    assert report.reconcile_input.enumerated_total == 0, "不同主机的地址不该拿去对账"
    assert report.reconcile_input.candidates == frozenset()
    assert report.sitemap_note and "没法比对" in report.sitemap_note
    # 总数契约还在，结论仍然成立。
    assert report.reconcile is not None
    assert report.reconcile.verdict == VERDICT_COMPLETE


async def test_a_sitemap_on_the_same_host_is_still_compared(db_session):
    """同一主机时照常对账——上面的放宽不能把这一层整个关掉。"""
    feed = ScriptedFeed([_page([_job(1)], total_hint=2)])
    expected = frozenset({"https://careers.example/jobs/9"})

    report = await _run(feed, db_session, expected_urls=expected)

    assert report.reconcile_input is not None
    assert report.reconcile_input.enumerated_total == 1
    assert report.sitemap_note == ""


# ===== 用户设的条数上限 =====
# 岗位上万条的站点一次翻不完（实测一家：每页都要开浏览器，30 页接近十分钟），用户只能手动
# 点停止——拿到的报告是「已停止」，也就没法与历史对比。所以允许他这次只抓前 N 条。


async def test_the_job_limit_stops_the_crawl_once_it_is_reached(db_session):
    """抓够就停，并且**账目是完整的**：这一页已经拿到的岗位全部入账。"""
    feed = ScriptedFeed([_page([_job(index)], has_more=True, cursor=f"c{index}") for index in range(5)])

    report = await _run(feed, db_session, max_jobs=2)

    assert report.collected == 2
    assert report.hit_job_limit == 2
    assert report.pages < 5, "抓够了就不该继续取后面的页面"
    assert report.reconcile is not None
    assert report.reconcile.verdict != VERDICT_COMPLETE


async def test_the_job_limit_is_reported_as_the_users_own_limit(db_session):
    """**必须与「达到页数上限」分开说**：一个是工具的边界、一个是用户的决定。

    混成一句的代价不是措辞难看：这句话会指着一个确实存在的设置（页数上限），而用户会去翻它，
    翻完发现跟自己填的那个数对不上——他填的是条数，而这句说的是页数。
    """
    feed = ScriptedFeed([_page([_job(index)], has_more=True, cursor=f"c{index}") for index in range(5)])

    report = await _run(feed, db_session, max_jobs=2)

    assert report.reconcile_input is not None
    assert report.reconcile_input.job_limit == 2
    assert report.reconcile is not None
    termination = report.reconcile.termination
    assert termination.state == TERMINATION_JOB_LIMIT
    # 数字要出现在句子里：用户填的就是它，对不上他会以为没生效。
    assert "2 条" in termination.detail
    assert "页数上限" not in termination.detail


async def test_the_job_limit_survives_a_replay(db_session):
    """存活校验之后是拿**存下来的账目原样重算**的，所以那个数字必须进得了账目。

    不存它的话，重算出来的话会退化成另一句（或干脆变成"页数上限"）——同一份账目两个说法。
    """
    feed = ScriptedFeed([_page([_job(index)], has_more=True, cursor=f"c{index}") for index in range(5)])
    report = await _run(feed, db_session, max_jobs=2)
    assert report.reconcile_input is not None

    restored = input_from_dict(input_to_dict(report.reconcile_input))
    again = classify_termination(
        blocks=restored.blocks,
        reached_page_limit=restored.reached_page_limit,
        job_limit=restored.job_limit,
        last_has_more=restored.last_has_more,
        cancelled=restored.cancelled,
        paginates=restored.paginates,
    )

    assert again == report.reconcile.termination


async def test_no_job_limit_keeps_the_old_behaviour(db_session):
    """不填时一切照旧——只有那个页数纪律在管。"""
    feed = ScriptedFeed([_page([_job(1)], total_hint=1)])

    report = await _run(feed, db_session)

    assert report.hit_job_limit is None
    assert report.reconcile_input is not None
    assert report.reconcile_input.job_limit == 0


# ===== 详情页正文回填 =====
# 通用路径的四级抽取里只有结构化数据带正文，而"没有结构化数据、JD 就摆在页面上"的站点是多数。
# 于是列表页给出的岗位只有标题，正文要靠**详情页自己**那一页的正文补上。


def _detail_body_page(**overrides) -> FeedPage:
    payload = {
        "jobs": [],
        "block": BLOCK_NONE,
        "body": "1、负责平台广告策略的制定与迭代，结合行业数据与客户诉求给出可执行的方案。",
        "body_requirements": "1、本科及以上学历，五年以上相关行业经验；2、沟通能力强。",
        "has_more": False,
        "cursor": "",
    }
    payload.update(overrides)
    return FeedPage(**payload)


async def test_job_limit_still_fetches_selected_detail_page(db_session):
    """一页岗位很多时，只入账预算内的岗位，但仍要取被选岗位的详情页。"""
    jobs = [_job(index, description="") for index in range(1, 51)]
    targets = [
        FeedTarget("scripted", job.url, depth=1)
        for job in jobs
    ]
    listing = _page(
        jobs,
        total_hint=906,
        has_more=True,
        cursor="page-2",
        next_targets=targets,
    )
    feed = ScriptedFeed([listing, _detail_body_page(), _page([_job(999)])])

    report = await _run(feed, db_session, max_jobs=1)

    assert report.collected == 1
    assert report.stored == 1
    assert report.detail_missing == 0
    assert report.total_hint == 906
    assert report.hit_job_limit == 1
    assert report.pages == 2, "只取当前岗位的详情，不翻下一页或其它岗位"
    assert feed.requested == ["https://api.example/jobs", "https://careers.example/jobs/1"]
    assert feed.cursors == ["", ""]
    candidate = db_session.query(CandidateJob).one()
    assert candidate.description.startswith("1、负责平台广告策略")
    assert report.reconcile is not None
    assert report.reconcile.verdict == VERDICT_INCOMPLETE
    assert report.reconcile.missing == 905


async def test_the_detail_page_body_fills_the_staged_job(db_session):
    """列表页给标题、详情页给正文，合成**一条**有正文的岗位。

    这就是这一级存在的理由：不补的话采到的岗位只有标题，而下游的技能标签、岗位匹配、
    简历定制全都拿正文当输入——它们会安静地产出一个基于空文本的结果。
    """
    # 列表页给标题、并把详情页地址派发出去——**没有这一步详情页压根不会被取**，
    # 而真实通用路径正是这么走的（默认配方读出的岗位链接同时进 jobs 与 next_targets）。
    listing = _page(
        [_job(1, url="https://x.example/jobs/1", description="")],
        next_targets=[FeedTarget("scripted", "https://x.example/jobs/1", depth=1)],
    )
    feed = ScriptedFeed([listing, _detail_body_page()])

    report = await _run(feed, db_session)

    candidate = db_session.query(CandidateJob).one()
    assert candidate.description.startswith("1、负责平台广告策略")
    assert "本科及以上学历" in candidate.requirements
    # 那一笔「没有正文」要退回去——不退的话报告会一直说缺正文，而它已经有了。
    assert report.detail_missing == 0
    assert db_session.query(CandidateJob).count() == 1, "回填不该多出一条候选"


async def test_filling_the_body_does_not_disturb_the_ledger(db_session):
    """回填只补字段，**不改账目**：它既不是一次新的取回，也不是一条新的岗位。"""
    # 列表页给标题、并把详情页地址派发出去——**没有这一步详情页压根不会被取**，
    # 而真实通用路径正是这么走的（默认配方读出的岗位链接同时进 jobs 与 next_targets）。
    listing = _page(
        [_job(1, url="https://x.example/jobs/1", description="")],
        next_targets=[FeedTarget("scripted", "https://x.example/jobs/1", depth=1)],
    )
    feed = ScriptedFeed([listing, _detail_body_page()])

    report = await _run(feed, db_session)

    assert report.collected == 1
    assert report.stored == 1
    assert report.skipped == 0
    assert report.pages == 2, "回填不产生取回"


async def test_a_page_that_is_nobody_s_job_leaves_no_trace(db_session):
    """地址对不上任何一条岗位的页面（列表页、栏目页）**什么都不做**。

    这是"按地址回填"这条设计的全部安全性所在：它只可能命中已有记录，不会凭空造一条。
    改成"造一条 FeedJob 交给去重"就会在这里多出一行没有标题的候选。
    """
    # 列表页给标题、并把详情页地址派发出去——**没有这一步详情页压根不会被取**，
    # 而真实通用路径正是这么走的（默认配方读出的岗位链接同时进 jobs 与 next_targets）。
    # 派发出去的是**另一个地址**，而它带回了正文——那页不属于任何一条已暂存的岗位。
    listing = _page(
        [_job(1, url="https://x.example/jobs/1", description="")],
        next_targets=[FeedTarget("scripted", "https://x.example/other", depth=1)],
    )
    feed = ScriptedFeed([listing, _detail_body_page()])

    report = await _run(feed, db_session)

    assert db_session.query(CandidateJob).count() == 1
    candidate = db_session.query(CandidateJob).one()
    assert candidate.description == ""
    assert report.detail_missing == 1, "没补上就该如实记着"


async def test_an_existing_body_is_not_overwritten_by_the_page(db_session):
    """已经有正文时**不覆盖**：结构化数据那条路给的是作者声明的字段，优先级更高。"""
    listing = _page([_job(1, url="https://x.example/jobs/1", description="作者声明的职位描述")])
    feed = ScriptedFeed([listing, _detail_body_page()])

    await _run(feed, db_session)

    candidate = db_session.query(CandidateJob).one()
    assert candidate.description == "作者声明的职位描述"


# ===== 同一条岗位的两种地址写法 =====
# 站点自己在页面里给出的链接常常带跟踪参数，而列表页给的是干净地址。判重不去掉它们的话，
# **同一条岗位会被当成两条**：备选岗位里多一行重复记录，collected 也跟着多计。


async def test_tracking_params_do_not_make_two_jobs_out_of_one(db_session):
    """实测形态：列表页给 ``…/detail``，详情页的「相关职位」链接给 ``…/detail?recomId=…``。"""
    listing = _page(
        [_job(1, url="https://x.example/position/1/detail", description="")],
        # **必须派发，否则第二个页面压根不会被取**——那样这条用例就成了"只采了一页"的
        # 平凡通过，测不出任何东西。
        next_targets=[
            FeedTarget("scripted", "https://x.example/position/1/detail", depth=1)
        ],
    )
    detail = _detail_body_page(
        jobs=[
            _job(
                9,
                url="https://x.example/position/1/detail?recomId=abc&sourceJobId=1",
                title="相关推荐里的同一个岗位",
            )
        ]
    )
    feed = ScriptedFeed([listing, detail])

    report = await _run(feed, db_session)

    assert db_session.query(CandidateJob).count() == 1, "同一条岗位堆出了两行"
    assert report.collected == 1, "同一条岗位被数了两次——对账拿这个数去比总数的"


async def test_the_query_string_is_kept_when_it_carries_the_identity(db_session):
    """**不能一概去掉查询串**：有些站点把岗位 id 放在查询参数里（``?jobId=123``）。

    全去掉会把整站岗位压成一条——比重复严重得多，而且看起来像"这个站只有一个岗位"。
    """
    # 标题不同是刻意的：判重规则里有一条"同一公司下的同名岗位算同一条"
    # （``find_by_job_identity``），那条与查询串无关，混进来会盖住这里要测的东西。
    feed = ScriptedFeed(
        [
            _page(
                [
                    _job(0, title="后端工程师", url="https://x.example/job?jobId=1"),
                    _job(0, title="前端工程师", url="https://x.example/job?jobId=2"),
                ]
            )
        ]
    )

    report = await _run(feed, db_session)

    assert report.collected == 2
    assert db_session.query(CandidateJob).count() == 2


def test_urls_without_tracking_params_are_left_untouched():
    """没有跟踪参数时**原样返回**：重建查询串会改动写法（编码、顺序），大多数地址不该被顺手改写。"""
    from app.services.sites.official.collector import _normalize_url

    assert _normalize_url("https://x.example/job?jobId=1&b=2") == "https://x.example/job?jobid=1&b=2"
    assert _normalize_url("https://X.example/jobs/1/") == "https://x.example/jobs/1"


async def test_a_previous_run_s_leftover_row_also_gets_its_body(db_session):
    """**上一轮就落在库里的候选也要能补上正文**。

    只认本轮新落的记录时，这一级就只在"第一次采这家公司"有用——而重新采一家早就采过的公司
    恰恰是最常见的用法（第一次没配好、采了一半、或者当时还没有这一级）。那时用户会看到
    "采是采了，正文一条都没有"，而每一页的正文其实都已经取回来了。

    实测现场就是这样：库里 52 条候选、0 条有正文，因为它们全是上一轮落的。
    """
    # 上一轮落的行：地址里带着跟踪参数（"去掉跟踪参数"那条规则生效之前落的就是这样）。
    db_session.add(
        CandidateJob(
            # 标题与列表页给出的那条一致（判重会因此认出"这条采过了"），
            # 但**地址写法不同**：跟踪参数是早期落的行才会有的。
            title="岗位 1",
            company="示例公司",
            source_url="https://x.example/jobs/1?recomId=abc",
            description="",
            source="官网采集",
        )
    )
    db_session.commit()
    feed = ScriptedFeed(
        [
            _page(
                [_job(1, url="https://x.example/jobs/1", description="")],
                next_targets=[FeedTarget("scripted", "https://x.example/jobs/1", depth=1)],
            ),
            _detail_body_page(),
        ]
    )

    await _run(feed, db_session)

    # **不要在这里 ``expire_all()``**：回填是改在会话里、还没 flush 的改动，而 expire 会把
    # 未落库的修改直接丢掉——表现成"正文没补上"，而代码其实是对的。（需要它的场景是后台任务
    # 用了另一个会话；这里没有。）
    row = db_session.query(CandidateJob).one()
    assert row.description.startswith("1、负责平台广告策略")
    assert db_session.query(CandidateJob).count() == 1, "回填不该多出一行"
