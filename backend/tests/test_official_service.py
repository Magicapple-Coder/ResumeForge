"""官网源服务的端到端链路（**离线**，用假传输层跑真实适配器）。

覆盖"给一个公司域名 → 识别 → 采集 → 落入暂存区 → 拿到对账结论"这条完整路径，
以及两个必须在服务层被执行、而不能留给调用方自觉的规则：

- 采集前必须先过 robots；
- **被 robots 拒绝也要落一条记录**——它是结论，不是错误。
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.models.material import CandidateJob
from app.models.official import (
    BLOCK_FORBIDDEN,
    BLOCK_NONE,
    BLOCK_RATE_LIMIT,
    RUN_DONE,
    RUN_FAILED,
    RUN_RUNNING,
    RUN_STOPPED,
    VERDICT_COMPLETE,
    VERDICT_INCOMPLETE,
    VERDICT_UNKNOWN,
    OfficialCollectRun,
)
from app.models.profile import utcnow
from app.schemas.setting import LLMConfig
from app.services.llm.base import BaseLLMProvider
from app.services.sites.official.base import (
    FeedHttp,
    FeedJob,
    FeedPage,
    FetchResult,
    JobFeed,
    ProbeContext,
)
from app.services.sites.official.feeds.generic import GenericFeed
from app.services.sites.official.feeds.greenhouse import GreenhouseFeed
from app.services.sites.official.generic.memory import SiteMemory
from app.services.sites.official.registry import FeedRegistry
from app.services.sites.official.service import (
    OfficialError,
    collect_site,
    create_site,
    default_browser_client,
    delete_site,
    domain_of,
    get_site,
    list_runs,
    probe_and_store,
    trend_for,
    verify_run,
)

BOARD_HOST = "boards-api.greenhouse.io"
EU_BOARD_HOST = "boards-api.eu.greenhouse.io"
BOARD_PREFIX = f"https://{BOARD_HOST}"
EU_BOARD_PREFIX = f"https://{EU_BOARD_HOST}"
ROBOTS_URL = "https://boards.greenhouse.io/robots.txt"

ALLOW_ALL_ROBOTS = FetchResult(
    block="", status_code=200, text="User-agent: *\nDisallow:\n", headers={}
)


class RoutingHttp(FeedHttp):
    """按 URL 前缀路由的假传输层。"""

    def __init__(self, routes: dict[str, FetchResult], *, default: FetchResult | None = None):
        self._routes = routes
        self._default = default or FetchResult(block="not_found", status_code=404)
        self.calls: list[str] = []

    async def request(self, method, url, *, params=None, json_body=None, headers=None, max_bytes=None):
        del method, params, json_body, headers, max_bytes
        self.calls.append(url)
        for prefix, result in self._routes.items():
            if url.startswith(prefix):
                return result
        return self._default


def _board(jobs: list[dict], total: int | None = None) -> FetchResult:
    body: dict = {"jobs": jobs}
    if total is not None:
        body["meta"] = {"total": total}
    return FetchResult(block="", status_code=200, text=json.dumps(body), headers={})


@pytest.fixture(autouse=True)
def _public_dns(fake_public_dns):
    """本文件的用例都要走真实的 SSRF 防护，因此都要固定域名解析。"""
    return fake_public_dns


def _registry() -> FeedRegistry:
    registry = FeedRegistry()
    registry.register(GreenhouseFeed())
    return registry


def _job(index: int) -> dict:
    return {
        "id": index,
        "title": f"岗位 {index}",
        "company_name": "示例公司",
        "location": {"name": "北京"},
        "absolute_url": f"https://boards.greenhouse.io/acme/jobs/{index}",
        "content": f"&lt;p&gt;第 {index} 个岗位的职位描述&lt;/p&gt;",
    }


# ===== 源的建立 =====


def test_domain_of_normalises_host(db_session):
    del db_session
    assert domain_of("https://Careers.ACME.com/jobs?x=1") == "careers.acme.com"
    assert domain_of("not a url") == ""


def test_create_site_requires_a_name_and_a_url(db_session):
    with pytest.raises(OfficialError):
        create_site(db_session, company="", careers_url="https://a.example")
    with pytest.raises(OfficialError):
        create_site(db_session, company="示例公司")


def test_create_site_rejects_duplicates(db_session):
    create_site(db_session, company="示例公司", careers_url="https://boards.greenhouse.io/acme")
    with pytest.raises(OfficialError, match="已经在列表里"):
        create_site(db_session, company="示例公司", careers_url="https://boards.greenhouse.io/acme")


def test_delete_site_removes_it_and_its_runs(db_session):
    site = create_site(db_session, company="示例公司", careers_url="https://x.example")
    site_id = site.id
    delete_site(db_session, site_id)
    with pytest.raises(OfficialError):
        get_site(db_session, site_id)
    assert list_runs(db_session, site_id=site_id) == []


# ===== 探测 =====


async def test_probe_recognises_the_system_and_stores_the_evidence(db_session):
    site = create_site(
        db_session, company="示例公司", careers_url="https://boards.greenhouse.io/acme"
    )
    http = RoutingHttp(
        {ROBOTS_URL: ALLOW_ALL_ROBOTS, BOARD_PREFIX: _board([_job(1)])}
    )

    result = await probe_and_store(db_session, site, http=http, registry=_registry())

    assert result.outcome.found is True
    assert site.source_kind == "greenhouse"
    assert site.endpoint.startswith(f"https://{BOARD_HOST}/v1/boards/acme/jobs")
    assert site.confidence == "high"
    # 证据要能展示给用户："为什么认为这家公司用的是这套系统"。
    assert "acme" in site.probe_evidence
    assert site.last_probed_at is not None


async def test_probe_falls_back_to_the_eu_region(db_session):
    """同一家公司只会落在两个区域中的一个，探测要对每个 token 都试两个。"""
    site = create_site(
        db_session, company="示例公司", careers_url="https://boards.greenhouse.io/acme"
    )
    http = RoutingHttp(
        {ROBOTS_URL: ALLOW_ALL_ROBOTS, EU_BOARD_PREFIX: _board([_job(1)])}
    )

    result = await probe_and_store(db_session, site, http=http, registry=_registry())

    assert result.outcome.found is True
    assert EU_BOARD_HOST in site.endpoint


async def test_probe_clears_stale_state_when_nothing_matches(db_session):
    """识别不出来时要**清掉**上一次的结论，否则报告里会写着"已识别：X"而端点是错的。"""
    site = create_site(
        db_session, company="示例公司", careers_url="https://boards.greenhouse.io/acme"
    )
    site.source_kind = "greenhouse"
    site.endpoint = "https://stale.example/jobs"
    db_session.commit()

    http = RoutingHttp({ROBOTS_URL: ALLOW_ALL_ROBOTS})  # 所有接口都 404
    result = await probe_and_store(db_session, site, http=http, registry=_registry())

    assert result.outcome.found is False
    assert site.source_kind == ""
    assert site.endpoint == ""


async def test_probe_records_the_robots_decision(db_session):
    site = create_site(
        db_session, company="示例公司", careers_url="https://boards.greenhouse.io/acme"
    )
    http = RoutingHttp(
        {
            ROBOTS_URL: FetchResult(
                block="", status_code=200, text="User-agent: *\nDisallow: /\n", headers={}
            )
        }
    )

    result = await probe_and_store(db_session, site, http=http, registry=_registry())

    assert site.robots_allowed is False
    assert result.robots is not None and result.robots.allowed is False


# ===== 采集 =====


async def test_collect_end_to_end_reports_a_hard_complete_verdict(db_session):
    """完整链路：识别 → 采集 → 落暂存区 → **已确认为全量**（依据是站点给的总数）。"""
    site = create_site(
        db_session, company="示例公司", careers_url="https://boards.greenhouse.io/acme"
    )
    http = RoutingHttp(
        {ROBOTS_URL: ALLOW_ALL_ROBOTS, BOARD_PREFIX: _board([_job(1), _job(2)], total=2)}
    )
    await probe_and_store(db_session, site, http=http, registry=_registry())

    run = await collect_site(db_session, site, http=http, registry=_registry())

    assert run.status == RUN_DONE
    assert run.verdict == VERDICT_COMPLETE
    assert run.collected == 2
    assert run.stored == 2
    assert run.total_hint == 2
    assert db_session.query(CandidateJob).count() == 2
    assert "全量" in run.headline


async def test_collect_reports_the_exact_gap_with_a_total_anchor(db_session):
    """站点声明 5 条、只拿到 2 条：差 3 条是**确凿的数字**，不是猜测。"""
    site = create_site(
        db_session, company="示例公司", careers_url="https://boards.greenhouse.io/acme"
    )
    http = RoutingHttp(
        {ROBOTS_URL: ALLOW_ALL_ROBOTS, BOARD_PREFIX: _board([_job(1), _job(2)], total=5)}
    )
    await probe_and_store(db_session, site, http=http, registry=_registry())

    run = await collect_site(db_session, site, http=http, registry=_registry())

    assert run.verdict == VERDICT_INCOMPLETE
    assert run.missing == 3


async def test_collect_refuses_when_robots_disallows_and_still_records_it(db_session):
    """被 robots 拒绝：**不采，但照样落一条记录**——用户回看时要能知道原因。"""
    site = create_site(
        db_session, company="示例公司", careers_url="https://boards.greenhouse.io/acme"
    )
    robots_disallow = FetchResult(
        block="", status_code=200, text="User-agent: *\nDisallow: /\n", headers={}
    )
    http = RoutingHttp(
        {ROBOTS_URL: robots_disallow, BOARD_PREFIX: _board([_job(1)])}
    )
    # 先探测（此时招聘页主机的 robots 已经不允许，但接口主机是另一个主机、另有自己的规则，
    # 所以识别仍然完成）——真实流程也是先加源再采集。
    await probe_and_store(db_session, site, http=http, registry=_registry())
    assert site.source_kind == "greenhouse"

    run = await collect_site(db_session, site, http=http, registry=_registry())

    assert db_session.query(CandidateJob).count() == 0
    assert run.status == RUN_DONE, "被拒绝是结论，不是失败"
    assert BLOCK_FORBIDDEN in run.blocks
    assert "不允许采集" in run.headline
    # 点名是哪个主机拒绝的，用户才知道下一步换哪个地址。
    assert "boards.greenhouse.io" in run.headline
    # 一条都没抓到，绝不能报"已确认为全量"。
    assert run.verdict == VERDICT_UNKNOWN


async def test_collect_blocks_the_api_host_by_its_own_robots(db_session):
    """**robots 按主机生效**：招聘页主机允许，但接口主机的 robots 不允许时，接口照样打不出去。

    只查用户给的那个域名的实现会在这里放行——而那正是真正被打的主机。
    """
    api_robots = f"https://{BOARD_HOST}/robots.txt"
    http = RoutingHttp(
        {
            ROBOTS_URL: ALLOW_ALL_ROBOTS,
            api_robots: FetchResult(
                block="", status_code=200, text="User-agent: *\nDisallow: /\n", headers={}
            ),
            BOARD_PREFIX: _board([_job(1)], total=1),
        }
    )
    site = create_site(
        db_session, company="示例公司", careers_url="https://boards.greenhouse.io/acme"
    )

    # 探测阶段接口就被拦下 → 识别不出来（被阻断，不是"没有"）。
    result = await probe_and_store(db_session, site, http=http, registry=_registry())
    assert result.outcome.found is False
    assert result.outcome.state == "blocked"
    assert not any(f"{BOARD_HOST}/v1/boards" in call for call in http.calls)


async def test_collect_without_a_recognised_system_raises(db_session):
    site = create_site(db_session, company="示例公司", careers_url="https://x.example/jobs")
    with pytest.raises(OfficialError, match="还没识别出可采集的招聘系统"):
        await collect_site(db_session, site, http=RoutingHttp({}), registry=_registry())


async def test_collect_records_a_trend_point(db_session):
    """每次采集落一条计数，供趋势离群比对。"""
    site = create_site(
        db_session, company="示例公司", careers_url="https://boards.greenhouse.io/acme"
    )
    http = RoutingHttp(
        {ROBOTS_URL: ALLOW_ALL_ROBOTS, BOARD_PREFIX: _board([_job(1)], total=1)}
    )
    await probe_and_store(db_session, site, http=http, registry=_registry())
    await collect_site(db_session, site, http=http, registry=_registry())
    await collect_site(db_session, site, http=http, registry=_registry())

    assert trend_for(db_session, site.id) == [1, 1]


async def test_collect_stores_the_reconcile_layers_for_the_report_page(db_session):
    """报告页要能逐层展开依据，所以明细必须落库，而不是当场算完就丢。"""
    site = create_site(
        db_session, company="示例公司", careers_url="https://boards.greenhouse.io/acme"
    )
    http = RoutingHttp(
        {ROBOTS_URL: ALLOW_ALL_ROBOTS, BOARD_PREFIX: _board([_job(1)], total=1)}
    )
    await probe_and_store(db_session, site, http=http, registry=_registry())

    run = await collect_site(db_session, site, http=http, registry=_registry())

    detail = run.reconcile_detail
    assert detail["termination"]["state"] == "exhausted"
    assert any(layer["layer"] == "total" for layer in detail["layers"])


# ===== 站点地图（集合对账的输入）=====


SITEMAP_URL = "https://boards.greenhouse.io/sitemap.xml"
ROBOTS_WITH_SITEMAP = FetchResult(
    block="",
    status_code=200,
    text=f"User-agent: *\nDisallow:\nSitemap: {SITEMAP_URL}\n",
    headers={},
)


def _sitemap(locs: list[str]) -> FetchResult:
    body = "".join(f"<url><loc>{loc}</loc></url>" for loc in locs)
    return FetchResult(
        block="",
        status_code=200,
        text=f'<?xml version="1.0"?><urlset>{body}</urlset>',
        headers={},
    )


async def test_sitemap_difference_becomes_unverified_candidates(db_session):
    """站点地图里有、我们没抓到的地址 → **待核实候选**，不是"已确认不全"。

    地图里会有早就招满、URL 却还留着的岗位，两者不逐条访问就分不出来。
    """
    site = create_site(
        db_session, company="示例公司", careers_url="https://boards.greenhouse.io/acme"
    )
    http = RoutingHttp({
        ROBOTS_URL: ROBOTS_WITH_SITEMAP,
        SITEMAP_URL: _sitemap([
            "https://boards.greenhouse.io/acme/jobs/1",
            "https://boards.greenhouse.io/acme/jobs/2",
            "https://boards.greenhouse.io/acme/about",  # 不是岗位页，应当被筛掉
        ]),
        BOARD_PREFIX: _board(
            [dict(_job(1), absolute_url="https://boards.greenhouse.io/acme/jobs/1")], total=1
        ),
    })
    await probe_and_store(db_session, site, http=http, registry=_registry())

    run = await collect_site(db_session, site, http=http, registry=_registry())

    assert run.verdict == VERDICT_UNKNOWN
    candidates = run.reconcile_detail["candidates"]
    assert "https://boards.greenhouse.io/acme/jobs/2" in candidates
    # 非岗位页（about）应当被筛掉，否则候选列表会被整站导航淹没。
    assert all("about" not in url for url in candidates)
    # 这一层参与没参与，报告里要看得出来。
    assert any(layer["layer"] == "sitemap" for layer in run.reconcile_detail["layers"])


async def test_sitemap_covering_everything_does_not_alone_prove_completeness(db_session):
    """覆盖了站点地图全集是正向证据，但地图自己也可能不全——结论仍按其它层定。"""
    site = create_site(
        db_session, company="示例公司", careers_url="https://boards.greenhouse.io/acme"
    )
    http = RoutingHttp({
        ROBOTS_URL: ROBOTS_WITH_SITEMAP,
        SITEMAP_URL: _sitemap(["https://boards.greenhouse.io/acme/jobs/1"]),
        BOARD_PREFIX: _board(
            [dict(_job(1), absolute_url="https://boards.greenhouse.io/acme/jobs/1")], total=1
        ),
    })
    await probe_and_store(db_session, site, http=http, registry=_registry())

    run = await collect_site(db_session, site, http=http, registry=_registry())

    # 总量锚点对上 → 硬结论仍然成立。
    assert run.verdict == VERDICT_COMPLETE
    assert run.evidence == "total"


async def test_unreachable_sitemap_does_not_break_the_collection(db_session):
    """站点地图取不到只是"这一层做不了"，不该影响采集本身。"""
    site = create_site(
        db_session, company="示例公司", careers_url="https://boards.greenhouse.io/acme"
    )
    http = RoutingHttp({
        ROBOTS_URL: ROBOTS_WITH_SITEMAP,  # 声明了 sitemap，但没有对应路由 → 404
        BOARD_PREFIX: _board([_job(1)], total=1),
    })
    await probe_and_store(db_session, site, http=http, registry=_registry())

    run = await collect_site(db_session, site, http=http, registry=_registry())

    assert run.verdict == VERDICT_COMPLETE, "站点地图取不到不该拖累结论"
    layers = {layer["layer"]: layer["detail"] for layer in run.reconcile_detail["layers"]}
    assert "sitemap" in layers, "取不到也要留痕，否则报告里会缺一层而没有解释"
    assert layers["sitemap"]


async def test_no_declared_sitemap_leaves_no_layer(db_session):
    """站点没声明站点地图时不留这一层——没有"这一层没做"这回事，本来就不存在。"""
    site = create_site(
        db_session, company="示例公司", careers_url="https://boards.greenhouse.io/acme"
    )
    http = RoutingHttp({ROBOTS_URL: ALLOW_ALL_ROBOTS, BOARD_PREFIX: _board([_job(1)], total=1)})
    await probe_and_store(db_session, site, http=http, registry=_registry())

    run = await collect_site(db_session, site, http=http, registry=_registry())

    assert all(layer["layer"] != "sitemap" for layer in run.reconcile_detail["layers"])


# ===== 存活校验：把"待核实"变成硬结论 =====


def _verify_page(*, expired: bool = False) -> FetchResult:
    from datetime import datetime, timedelta, timezone

    payload = {
        "@type": "JobPosting",
        "title": "仍在招的岗位",
        "description": "<p>职责</p>",
    }
    if expired:
        payload["validThrough"] = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).isoformat()
    html = (
        "<html><head>"
        f'<script type="application/ld+json">{json.dumps(payload, ensure_ascii=False)}</script>'
        "</head><body></body></html>"
    )
    return FetchResult(block="", status_code=200, text=html, headers={})


async def _run_with_gap(db_session, gap_route: FetchResult):
    """造一次"站点地图里有、没抓到"的采集，返回 (站点, 运行记录, http)。"""
    site = create_site(
        db_session, company="示例公司", careers_url="https://boards.greenhouse.io/acme"
    )
    http = RoutingHttp({
        ROBOTS_URL: ROBOTS_WITH_SITEMAP,
        SITEMAP_URL: _sitemap([
            "https://boards.greenhouse.io/acme/jobs/1",
            "https://boards.greenhouse.io/acme/jobs/2",
        ]),
        BOARD_PREFIX: _board([_job(1)], total=1),
        "https://boards.greenhouse.io/acme/jobs/2": gap_route,
    })
    await probe_and_store(db_session, site, http=http, registry=_registry())
    run = await collect_site(db_session, site, http=http, registry=_registry())
    assert run.reconcile_detail["candidates"] == ["https://boards.greenhouse.io/acme/jobs/2"]
    return site, run, http


async def test_verifying_a_live_candidate_confirms_the_shortfall(db_session):
    """核实出仍在招 → 确凿的漏抓，结论升级为"已确认不全"。"""
    _, run, http = await _run_with_gap(db_session, _verify_page())

    updated = await verify_run(db_session, run.id, http=http)

    assert updated.verdict == VERDICT_INCOMPLETE
    assert updated.missing == 1
    assert "仍在招聘" in updated.headline or "仍在招" in updated.headline


async def test_verifying_all_as_gone_upgrades_to_complete(db_session):
    """差额**全部**核实为已下架 → 差额被完全解释掉，这才是硬结论。"""
    _, run, http = await _run_with_gap(db_session, _verify_page(expired=True))

    updated = await verify_run(db_session, run.id, http=http)

    assert updated.verdict == VERDICT_COMPLETE
    assert "下架" in updated.headline


async def test_unverifiable_candidate_leaves_the_verdict_unknown(db_session):
    """核实不了（取不到）→ 结论停在"无法确认"，并把它留在候选里。"""
    _, run, http = await _run_with_gap(
        db_session, FetchResult(block="rate_limit", status_code=429, detail="限流")
    )

    updated = await verify_run(db_session, run.id, http=http)

    assert updated.verdict == VERDICT_UNKNOWN
    assert updated.reconcile_detail["candidates"] == ["https://boards.greenhouse.io/acme/jobs/2"]


async def test_verification_details_are_recorded_for_the_report(db_session):
    """逐条核实结果要留痕：用户得看到"哪个地址、核出了什么"。"""
    _, run, http = await _run_with_gap(db_session, _verify_page())

    updated = await verify_run(db_session, run.id, http=http)

    entries = updated.reconcile_detail["verifications"]
    assert len(entries) == 1
    assert entries[0]["url"].endswith("/jobs/2")
    assert entries[0]["state"] == "live"
    assert entries[0]["label"], "分类的中文一并存下来，前端不自己维护映射"


async def test_verifying_a_run_without_candidates_is_a_user_error(db_session):
    site = create_site(
        db_session, company="示例公司", careers_url="https://boards.greenhouse.io/acme"
    )
    http = RoutingHttp({ROBOTS_URL: ALLOW_ALL_ROBOTS, BOARD_PREFIX: _board([_job(1)], total=1)})
    await probe_and_store(db_session, site, http=http, registry=_registry())
    run = await collect_site(db_session, site, http=http, registry=_registry())

    with pytest.raises(OfficialError, match="没有待核实"):
        await verify_run(db_session, run.id, http=http)


async def test_verification_replays_the_stored_input(db_session):
    """重算必须用**原来的账目**：把存储的输入丢掉再算，会让别的层凭空消失。"""
    _, run, http = await _run_with_gap(db_session, _verify_page(expired=True))
    stored = run.reconcile_detail["input"]
    assert stored["total_hint"] == 1
    assert stored["collected"] == 1

    updated = await verify_run(db_session, run.id, http=http)

    # 总量锚点仍然在结论里（它来自存储的输入，而不是被重算丢掉）。
    assert updated.reconcile_detail["input"]["total_hint"] == 1


# ===== 后台执行与停止 =====


class _SlowFeed(JobFeed):
    """多页、每页都要等一下的适配器——用来制造"还在跑"的窗口。"""

    key = "slow"
    display_name = "慢适配器"

    def probe_candidates(self, ctx: ProbeContext) -> list:  # pragma: no cover - 不走探测
        del ctx
        return []

    async def fetch_page(self, http: FeedHttp, target, *, cursor: str = "") -> FeedPage:
        del http, target
        await asyncio.sleep(0.05)
        page_number = int(cursor or "0")
        return FeedPage(
            jobs=[
                FeedJob(
                    title=f"岗位 {page_number}",
                    url=f"https://slow.example/jobs/{page_number}",
                    description="职位描述",
                )
            ],
            has_more=page_number < 20,
            cursor=str(page_number + 1),
        )


class _AllowAllHttp(FeedHttp):
    async def request(self, method, url, *, params=None, json_body=None, headers=None,
                      max_bytes=None):
        del method, params, json_body, headers, max_bytes
        if url.endswith("/robots.txt"):
            return FetchResult(
                block=BLOCK_NONE, status_code=200, text="User-agent: *\nDisallow:\n", headers={}
            )
        return FetchResult(block="not_found", status_code=404)


async def _wait_until(predicate, *, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("条件没有在超时前成立")


@pytest.fixture
def slow_site(db_session, monkeypatch):
    """一个"能采、但采得慢"的站点，配上它自己的注册表与传输层。"""
    registry = FeedRegistry()
    registry.register(_SlowFeed())
    monkeypatch.setattr(
        "app.services.sites.official.service.get_feed_registry", lambda: registry
    )
    monkeypatch.setattr(
        "app.services.sites.official.service.default_http_factory",
        lambda db=None: _AllowAllHttp(),
    )

    site = create_site(db_session, company="慢公司", careers_url="https://slow.example/jobs")
    site.source_kind = "slow"
    site.endpoint = "https://slow.example/jobs"
    site.min_interval_seconds = 0
    db_session.commit()
    return site


async def test_start_collection_returns_immediately(db_session, slow_site):
    """**接口立刻返回**：多页站点同步走完会把 HTTP 请求挂住，界面只能干等。"""
    from app.services.sites.official import service as official_service

    started = official_service.start_collection(db_session, slow_site)

    assert started.status == RUN_RUNNING
    assert started.finished_at is None


async def test_a_running_collection_can_be_stopped(db_session, slow_site):
    """停止是**协作式**的：采集器在下一个检查点自己停下来，账目仍然完整。

    这条路径串起了三样东西——运行器的停止标记、采集器的检查点、服务层把结果收尾成
    "已停止"而不是"失败"。
    """
    from app.services.sites.official import service as official_service
    from app.services.sites.official.runner import get_official_runner

    started = official_service.start_collection(db_session, slow_site)
    runner = get_official_runner()

    def progressed() -> bool:
        """后台任务在**自己的会话**里写这行记录，这里必须丢掉缓存再看。"""
        try:
            db_session.expire_all()
            return official_service.get_run(db_session, started.id).pages >= 1
        except Exception:  # noqa: BLE001 - 读写竞争是暂时的，下一轮再看
            return False

    await _wait_until(progressed)  # 确实跑起来了

    official_service.request_stop(db_session, started.id)
    await _wait_until(lambda: not runner.is_running(started.id))

    db_session.expire_all()
    final = official_service.get_run(db_session, started.id)
    assert final.status == RUN_STOPPED
    assert final.collected >= 1, "停下来之前抓到的岗位仍然有效"
    assert final.finished_at is not None, "停止也要把记录收尾，不能停在采集中"


async def test_stopping_a_finished_collection_is_a_user_error(db_session, slow_site):
    """已经结束的采集再点停止 = 用户操作有误，要明确说出来而不是假装成功。"""
    from app.services.sites.official import service as official_service
    from app.services.sites.official.runner import get_official_runner

    started = official_service.start_collection(db_session, slow_site)
    runner = get_official_runner()
    await _wait_until(lambda: not runner.is_running(started.id))

    with pytest.raises(OfficialError, match="已经结束"):
        official_service.request_stop(db_session, started.id)


async def test_a_second_collection_for_the_same_site_is_refused(db_session, slow_site):
    """同一家公司同时只跑一次：两次并发采集既互相抢限速，也会让报告对不上号。"""
    from app.services.sites.official import service as official_service
    from app.services.sites.official.runner import get_official_runner

    started = official_service.start_collection(db_session, slow_site)
    try:
        with pytest.raises(OfficialError, match="进行中"):
            official_service.start_collection(db_session, slow_site)
    finally:
        official_service.request_stop(db_session, started.id)
        await _wait_until(lambda: not get_official_runner().is_running(started.id))


async def test_orphaned_runs_are_failed_on_restart(db_session, slow_site):
    """应用重启后，"采集中"的记录是幽灵——那个任务早就随进程消失了。"""
    from app.services.sites.official import service as official_service

    started = official_service.start_collection(db_session, slow_site)
    official_service.request_stop(db_session, started.id)
    await _wait_until(lambda: not official_service.get_official_runner().is_running(started.id))

    # 伪造一条"停在采集中"的记录（真实场景里它是上次崩溃留下的）。
    zombie = OfficialCollectRun(site_id=slow_site.id, status=RUN_RUNNING, started_at=utcnow())
    db_session.add(zombie)
    db_session.commit()

    cleaned = official_service.fail_orphaned_runs(db_session)

    assert cleaned == 1
    db_session.refresh(zombie)
    assert zombie.status == RUN_FAILED
    assert "重启" in zombie.error


# ===== 趋势离群（一张以前只写不读的表）=====


def _history_run(
    db_session,
    site,
    *,
    collected: int,
    status: str = RUN_DONE,
    blocks: list[str] | None = None,
) -> OfficialCollectRun:
    """直接造一条历史运行记录——趋势只关心账目，不需要真跑一次采集。"""
    run = OfficialCollectRun(
        site_id=site.id,
        status=status,
        started_at=utcnow(),
        collected=collected,
        blocks=blocks if blocks is not None else [BLOCK_NONE],
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    return run


def test_trend_needs_history_before_it_says_anything(db_session):
    from app.services.sites.official import service as official_service

    site = create_site(db_session, company="示例公司", careers_url="https://x.example/jobs")
    latest = _history_run(db_session, site, collected=3)

    signal = official_service.trend_signal_for(db_session, latest)

    assert signal.state == "insufficient"
    assert signal.baseline is None


def test_trend_detects_a_drop_against_the_site_history(db_session):
    """**这就是单次对账看不见的病**：今天报"已确认为全量"，而它上周还有 40 条。"""
    from app.services.sites.official import service as official_service

    site = create_site(db_session, company="示例公司", careers_url="https://x.example/jobs")
    for count in (40, 42, 38):
        _history_run(db_session, site, collected=count)
    latest = _history_run(db_session, site, collected=3)

    signal = official_service.trend_signal_for(db_session, latest)

    assert signal.state == "dropped"
    assert signal.baseline == 40
    assert "不一定是漏抓" in signal.detail


def test_blocked_runs_are_excluded_from_the_baseline(db_session):
    """一次被限流的采集不该把基线拉低——它的 0 是"我们没拿到"，不是"没有岗位"。

    设成"历史里有被阻断的、本次是一次真实测量"，才对准要测的那条规则。
    """
    from app.services.sites.official import service as official_service

    site = create_site(db_session, company="示例公司", careers_url="https://x.example/jobs")
    for count in (40, 40, 42):
        _history_run(db_session, site, collected=count)
    _history_run(db_session, site, collected=0, blocks=[BLOCK_RATE_LIMIT])
    latest = _history_run(db_session, site, collected=3)  # 本次是真实测量

    signal = official_service.trend_signal_for(db_session, latest)

    assert signal.baseline == 40, "被阻断的那条不该进基线"
    assert signal.state == "dropped"


def test_a_blocked_run_is_not_compared_against_history(db_session):
    """**本次**就没拿到有效结果时，不该说"明显少于近期"。

    条数低的原因我们**是知道的**（被拦了），而"明显少于近期、可能是公司关掉了岗位"
    会邀请用户往错的方向想。如实说"这次没有拿到可比的结果"。
    """
    from app.services.sites.official import service as official_service

    site = create_site(db_session, company="示例公司", careers_url="https://x.example/jobs")
    for count in (40, 40, 42):
        _history_run(db_session, site, collected=count)
    blocked = _history_run(db_session, site, collected=0, blocks=[BLOCK_RATE_LIMIT])

    signal = official_service.trend_signal_for(db_session, blocked)

    assert signal.state == "unmeasured"
    assert signal.baseline is None
    assert "被阻断或已停止" in signal.detail


def test_trend_only_looks_at_earlier_runs(db_session):
    """只看**此前**的历史：把后来的采集算进来，"这次异常吗"就没有意义了。"""
    from app.services.sites.official import service as official_service

    site = create_site(db_session, company="示例公司", careers_url="https://x.example/jobs")
    for count in (40, 40, 40):
        _history_run(db_session, site, collected=count)
    latest = _history_run(db_session, site, collected=3)
    _history_run(db_session, site, collected=99)  # 后来的，不该影响对 latest 的判断

    signal = official_service.trend_signal_for(db_session, latest)

    assert signal.baseline == 40
    assert signal.state == "dropped"


def test_trend_for_returns_only_measurements(db_session):
    from app.services.sites.official import service as official_service

    site = create_site(db_session, company="示例公司", careers_url="https://x.example/jobs")
    for count in (12, 0, 15):
        status = RUN_DONE if count else RUN_STOPPED
        _history_run(db_session, site, collected=count, status=status)

    # 三次里只有被停止的那条不算测量；12 与 15 都保留，且顺序由旧到新。
    assert official_service.trend_for(db_session, site.id) == [12, 15]


async def test_collect_lists_runs_newest_first(db_session):
    site = create_site(
        db_session, company="示例公司", careers_url="https://boards.greenhouse.io/acme"
    )
    http = RoutingHttp(
        {ROBOTS_URL: ALLOW_ALL_ROBOTS, BOARD_PREFIX: _board([_job(1)], total=1)}
    )
    await probe_and_store(db_session, site, http=http, registry=_registry())
    first = await collect_site(db_session, site, http=http, registry=_registry())
    second = await collect_site(db_session, site, http=http, registry=_registry())

    runs = list_runs(db_session, site_id=site.id)
    assert [run.id for run in runs][:2] == [second.id, first.id]


# ===== 配方与模型（阶段 2）=====

GENERIC_PAGE = "https://careers.example.com/jobs"
GENERIC_ROBOTS = "https://careers.example.com/robots.txt"

# 探测得出来（有像岗位页的链接），但**默认配方读不出标题**（锚文本是操作文案），
# 于是轮到模型——而且模型读出的标题（在 h3 里）确实在页面上，可以归纳成配方。
LEARNABLE_PAGE = """<ul>
<li class="row"><h3>大模型应用开发工程师</h3><a class="act" href="/jobs/1">查看详情</a></li>
<li class="row"><h3>算法工程师</h3><a class="act" href="/jobs/2">查看详情</a></li>
</ul>"""


def _generic_registry() -> FeedRegistry:
    registry = FeedRegistry()
    registry.register(GenericFeed())
    return registry


class _ScriptedProvider(BaseLLMProvider):
    def __init__(self, reply: str):
        super().__init__(LLMConfig(base_url="http://fake", model="fake-model"))
        self.reply = reply
        self.calls = 0

    async def chat(self, messages: list[dict]) -> str:
        del messages
        self.calls += 1
        return self.reply

    async def stream_chat(self, messages: list[dict]):  # pragma: no cover - 未用到
        yield ""


def _jobs_reply(*pairs: tuple[int, str]) -> str:
    return json.dumps(
        {"jobs": [{"index": index, "title": title} for index, title in pairs]},
        ensure_ascii=False,
    )


def _listing_http() -> RoutingHttp:
    return RoutingHttp(
        {
            GENERIC_ROBOTS: ALLOW_ALL_ROBOTS,
            GENERIC_PAGE: FetchResult(
                block=BLOCK_NONE, status_code=200, text=LEARNABLE_PAGE, headers={}
            ),
        }
    )


async def test_a_learned_recipe_is_stored_on_the_site(db_session, monkeypatch):
    """**归纳出来的配方要落库**——不然"为模型只付一次钱"只是句空话。"""
    from app.services.sites.official import service as official_service
    from app.services.sites.official.generic.llm_extract import ListingExtractor

    provider = _ScriptedProvider(
        _jobs_reply((1, "大模型应用开发工程师"), (2, "算法工程师"))
    )
    monkeypatch.setattr(
        official_service, "default_listing_extractor", lambda db: ListingExtractor(provider)
    )

    site = create_site(db_session, company="示例公司", careers_url=GENERIC_PAGE)
    http = _listing_http()
    await probe_and_store(db_session, site, http=http, registry=_generic_registry())
    run = await collect_site(db_session, site, http=http, registry=_generic_registry())

    assert run.collected == 2
    assert run.llm_calls == 1
    assert site.recipe, "配方没写回源"
    assert site.recipe_version
    assert SiteMemory.from_blob(site.recipe).listing is not None


async def test_the_second_collection_reuses_the_stored_recipe(db_session, monkeypatch):
    """第二次采集应当零模型调用——配方已经在源上了。"""
    from app.services.sites.official import service as official_service
    from app.services.sites.official.generic.llm_extract import ListingExtractor

    provider = _ScriptedProvider(
        _jobs_reply((1, "大模型应用开发工程师"), (2, "算法工程师"))
    )
    monkeypatch.setattr(
        official_service, "default_listing_extractor", lambda db: ListingExtractor(provider)
    )

    site = create_site(db_session, company="示例公司", careers_url=GENERIC_PAGE)
    http = _listing_http()
    await probe_and_store(db_session, site, http=http, registry=_generic_registry())
    await collect_site(db_session, site, http=http, registry=_generic_registry())
    second = await collect_site(db_session, site, http=http, registry=_generic_registry())

    assert second.collected == 2
    assert second.llm_calls == 0
    assert provider.calls == 1


async def test_without_a_model_the_run_says_so_instead_of_pretending(db_session):
    """没配模型时如实说明，而不是假装试过了。"""
    site = create_site(db_session, company="示例公司", careers_url=GENERIC_PAGE)
    http = _listing_http()
    await probe_and_store(db_session, site, http=http, registry=_generic_registry())
    run = await collect_site(db_session, site, http=http, registry=_generic_registry())

    extraction = run.reconcile_detail["extraction"]
    assert extraction["llm_calls"] == 0
    assert any("没有配置" in note for note in extraction["methods"])
    assert not site.recipe


def test_the_extractor_is_none_when_no_model_is_configured(db_session):
    """没配模型不是故障，只是这一级用不了——返回 ``None`` 让上层如实说明。"""
    from app.services.sites.official.service import default_listing_extractor

    assert default_listing_extractor(db_session) is None


def test_the_extractor_is_built_from_the_user_model_config(db_session, monkeypatch):
    """用用户当前那份模型配置，不另立一套——用户在哪里配过，这里就用哪一个。"""
    from app.schemas.setting import LLMConfig
    from app.services import settings_service
    from app.services.sites.official.service import default_listing_extractor

    settings_service.save_llm_config(
        db_session, LLMConfig(base_url="http://fake", model="fake-model", api_key="sk-test")
    )

    assert default_listing_extractor(db_session) is not None


def test_the_run_reports_the_model_calls_it_made(db_session):
    """报告里要能查到花了多少次模型调用——用户自付 key，这一项必须可查。"""
    from app.services.sites.official import service as official_service
    from app.services.sites.official.collector import OfficialCollectReport

    site = create_site(db_session, company="示例公司", careers_url="https://x.example/jobs")
    report = OfficialCollectReport(llm_calls=3, recipes_learned=1)
    run = OfficialCollectRun(site_id=site.id, status=RUN_RUNNING, started_at=utcnow())
    db_session.add(run)
    db_session.flush()

    official_service._apply_report(run, report)

    assert run.llm_calls == 3
    assert run.reconcile_detail["extraction"]["llm_calls"] == 3
    assert run.reconcile_detail["extraction"]["recipes_learned"] == 1


# ===== 渲染升级的取浏览器入口（阶段 3 之后）=====
# 这一节守的是一个**只在真实站点上才跑得到**的失败：这条路只在"页面确认要渲染"时才走到，
# 而离线用例默认不渲染，所以它曾经带着一个写错的模块路径上线——两千多个用例全绿，
# 真实采集一按就 500。教训不是"小心点"，而是：**可选能力的入口必须有无条件的用例走一遍**。


def test_the_browser_entry_point_actually_reaches_the_manager(db_session, monkeypatch):
    """调用它本身就是用例：写错模块路径的话，这一句会抛 ModuleNotFoundError。

    **断言的是"假管理器有没有被问到"，不是"返回 None"**。第一版写成断言返回值，于是：
    路径照样是错的 → 导入抛错 → 被 ``except`` 吞掉 → 也返回 ``None`` → 用例绿。
    一个只在"错误发生"和"正常降级"恰好同形时才存在的假绿测试，比没有测试更糟。

    用假的管理器而不是真的去探测端口：这条用例要守的是**导入能不能解析**，
    不该依赖跑它的机器上有没有浏览器在运行。
    """

    class Stopped:
        def __init__(self) -> None:
            self.asked = False

        def is_running(self) -> bool:
            self.asked = True
            return False

    manager = Stopped()
    monkeypatch.setattr("app.services.apply.get_browser_manager", lambda _db: manager)

    assert default_browser_client(db_session) is None
    assert manager.asked, (
        "取浏览器的入口没走到管理器，多半是懒导入的模块路径解析不了（被 except 吞掉了）"
    )


def test_a_broken_browser_entry_point_does_not_fail_the_whole_collect(db_session, monkeypatch):
    """渲染升级是**可选**能力：它自己坏掉，只该让这次采集少一种读法。

    原来那条导入写在 ``try`` 外面，于是"取不到浏览器"这个已被预期的降级情形，
    变成了把整次采集炸成 500。这里把导入逼到失败，断言它退化成 ``None``。
    """
    import sys
    import types

    # 用一个缺少该符号的同名模块顶掉真正的 apply 包 → `from ...apply import ...` 抛 ImportError。
    monkeypatch.setitem(sys.modules, "app.services.apply", types.ModuleType("app.services.apply"))

    assert default_browser_client(db_session) is None
