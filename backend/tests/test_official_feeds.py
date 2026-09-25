"""招聘系统适配器与站源探测。

守两条性质：

1. **探测不许把"这家公司不用这套系统"读成"它在用、只是没在招"**——那会让对账报告
   "0 条，已确认为全量"，是这套机制里最坏的一类错误；
2. **用户亲眼给过的招聘页地址例外**：那一刻 0 岗位是真实答案，如实报告比退回猜测有用。
"""
from __future__ import annotations

import json

import pytest

from app.models.official import (
    BLOCK_NONE,
    BLOCK_NOT_FOUND,
    BLOCK_RATE_LIMIT,
    BLOCK_SOFT,
)
from app.services.sites.official.base import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    FeedHttp,
    FetchResult,
    ProbeContext,
)
from app.services.sites.official.feeds.greenhouse import (
    GreenhouseFeed,
    extract_board_token,
    parse_board_payload,
)
from app.services.sites.official.urls import host_label
from app.services.sites.official.probe import (
    PROBE_BLOCKED,
    PROBE_HIT,
    PROBE_NOT_FOUND,
    probe_site,
)
from app.services.sites.official.registry import FeedRegistry


class FakeHttp(FeedHttp):
    """按 URL 前缀路由的假传输层。记录调用次数，用于断言"没有多余请求"。"""

    def __init__(self, routes: dict[str, FetchResult], *, default: FetchResult | None = None):
        self._routes = routes
        self._default = default or FetchResult(block=BLOCK_NOT_FOUND, status_code=404)
        self.calls: list[str] = []

    async def request(
        self, method, url, *, params=None, json_body=None, headers=None, max_bytes=None
    ) -> FetchResult:
        del method, params, json_body, headers, max_bytes
        self.calls.append(url)
        for prefix, result in self._routes.items():
            if url.startswith(prefix):
                return result
        return self._default


def _board_payload(jobs: list[dict], total: int | None = None) -> FetchResult:
    body: dict = {"jobs": jobs}
    if total is not None:
        body["meta"] = {"total": total}
    return FetchResult(
        block=BLOCK_NONE, status_code=200, text=json.dumps(body), headers={}
    )


# ===== token 提取与域名推测 =====


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://boards.greenhouse.io/acme", "acme"),
        ("https://job-boards.greenhouse.io/acme/jobs/123", "acme"),
        ("https://boards.greenhouse.io/embed/job_board?for=acme", "acme"),
        ("https://boards.greenhouse.io/", ""),
        ("https://careers.example.com/jobs", ""),
        ("not a url", ""),
    ],
)
def test_extract_board_token(url, expected):
    assert extract_board_token(url) == expected


@pytest.mark.parametrize(
    ("domain", "expected"),
    [
        ("acme.com", "acme"),
        ("www.acme.com", "acme"),
        ("careers.acme.com", "acme"),
        ("acme.co.uk", "acme"),
        ("jobs.acme.io", "acme"),
        ("", ""),
    ],
)
def test_host_label(domain, expected):
    """探测与公司发现共用这一份实现（在 ``urls`` 里）。"""
    assert host_label(domain) == expected


# ===== 响应解析 =====


def test_parse_payload_unescapes_html_entities_in_description():
    """接口给的正文是**被转义过的 HTML**，不先反转义就会把标记原样写进岗位描述。"""
    payload = {
        "jobs": [
            {
                "id": 1,
                "title": "大模型应用开发工程师",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
                "location": {"name": "北京"},
                "content": "&lt;p&gt;负责大模型应用的设计与落地&lt;/p&gt;",
            }
        ],
        "meta": {"total": 1},
    }
    parsed = parse_board_payload(payload)
    assert parsed is not None
    jobs, total = parsed
    assert total == 1
    assert jobs[0].title == "大模型应用开发工程师"
    assert jobs[0].location == "北京"
    assert "负责大模型应用的设计与落地" in jobs[0].description
    assert "&lt;" not in jobs[0].description
    assert jobs[0].external_id == "1"


def test_short_description_paragraphs_are_not_dropped():
    """短段落必须保留。

    搜索层的正文抽取器带一条"短于 20 字符当作导航丢弃"的启发式——那是为在整页里*找*正文
    而设的。直接套用会把"熟悉 Python。"这样的短要求整段吃掉，而岗位描述恰恰是最不能丢的。
    """
    payload = {
        "jobs": [
            {
                "id": 1,
                "title": "岗位",
                "content": "&lt;p&gt;熟悉 Python。&lt;/p&gt;&lt;p&gt;有责任心。&lt;/p&gt;",
            }
        ]
    }
    jobs, _ = parse_board_payload(payload)
    assert "熟悉 Python。" in jobs[0].description
    assert "有责任心。" in jobs[0].description


def test_description_paragraphs_stay_on_separate_lines():
    """职责与要求必须分行：全部拼成一行会让边界糊在一起。"""
    payload = {
        "jobs": [
            {
                "id": 1,
                "title": "岗位",
                "content": "&lt;h3&gt;岗位职责&lt;/h3&gt;&lt;p&gt;负责模型落地&lt;/p&gt;",
            }
        ]
    }
    jobs, _ = parse_board_payload(payload)
    assert "岗位职责" in jobs[0].description
    assert "负责模型落地" in jobs[0].description
    assert "\n" in jobs[0].description


def test_parse_payload_without_jobs_array_is_a_protocol_break():
    """没有 ``jobs`` 数组**不是**"这家公司没在招"——真的没在招会给出 ``"jobs": []``。

    混为一谈的后果是：一次接口改版会被读成"0 个岗位，已确认为全量"。
    """
    assert parse_board_payload({"error": "something"}) is None
    assert parse_board_payload([1, 2, 3]) is None
    assert parse_board_payload(None) is None


def test_parse_payload_with_empty_jobs_is_a_valid_empty_board():
    parsed = parse_board_payload({"jobs": [], "meta": {"total": 0}})
    assert parsed == ([], 0)


def test_parse_payload_does_not_invent_titles():
    payload = {"jobs": [{"id": 1, "title": ""}, {"id": 2, "title": "有效岗位"}]}
    jobs, _ = parse_board_payload(payload)
    assert [job.title for job in jobs] == ["有效岗位"]


def test_posted_at_uses_first_published_not_updated_at():
    """发布时间只用明确的"首次发布"。拿修改时间当发布时间会让旧岗位看起来是新的。"""
    payload = {
        "jobs": [
            {
                "id": 1,
                "title": "岗位",
                "first_published": "2024-01-15T00:00:00-05:00",
                "updated_at": "2026-09-01T00:00:00-05:00",
            }
        ]
    }
    jobs, _ = parse_board_payload(payload)
    assert jobs[0].posted_at == "2024-01-15T00:00:00-05:00"


# ===== 取回 =====


async def test_fetch_page_returns_jobs_and_total_hint():
    feed = GreenhouseFeed()
    http = FakeHttp(
        {"https://boards-api.greenhouse.io": _board_payload([{"id": 1, "title": "岗位"}], total=1)}
    )
    target = feed.probe_candidates(
        ProbeContext(careers_url="https://boards.greenhouse.io/acme")
    )[0].target

    page = await feed.fetch_page(http, target)

    assert page.block == BLOCK_NONE
    assert page.total_hint == 1
    assert len(page.jobs) == 1
    # 这套接口一次返回全部，所以"没有下一页"是契约，不是数出来的。
    assert page.has_more is False


async def test_fetch_page_maps_non_json_body_to_soft_block():
    """能拿到正文却解析不出 JSON：多半是被 WAF 换成了错误页，而不是"这里没有岗位"。"""
    feed = GreenhouseFeed()
    http = FakeHttp(
        {
            "https://boards-api.greenhouse.io": FetchResult(
                block=BLOCK_NONE,
                status_code=200,
                text="<html><body>Access Denied</body></html>",
                headers={},
            )
        }
    )
    target = feed.probe_candidates(ProbeContext(domain="acme.com"))[0].target

    page = await feed.fetch_page(http, target)

    assert page.block == BLOCK_SOFT
    assert "网页" in page.detail


async def test_fetch_page_propagates_transport_block():
    feed = GreenhouseFeed()
    http = FakeHttp(
        {"https://boards-api.greenhouse.io": FetchResult(block=BLOCK_RATE_LIMIT, detail="限流")}
    )
    target = feed.probe_candidates(ProbeContext(domain="acme.com"))[0].target

    page = await feed.fetch_page(http, target)

    assert page.block == BLOCK_RATE_LIMIT


# ===== 候选推导 =====


def test_candidates_are_ordered_by_confidence():
    feed = GreenhouseFeed()
    candidates = feed.probe_candidates(
        ProbeContext(
            company="示例",
            domain="guessed.com",
            careers_url="https://boards.greenhouse.io/acme",
            homepage_html='<a href="https://job-boards.greenhouse.io/other">招聘</a>',
        )
    )

    confidences = [candidate.confidence for candidate in candidates]
    assert confidences[0] == CONFIDENCE_HIGH
    assert CONFIDENCE_MEDIUM in confidences
    assert CONFIDENCE_LOW in confidences
    # 三个线索给出三个不同的 token，每个两个区域
    assert len({candidate.target.endpoint for candidate in candidates}) == 6


def test_candidates_deduplicate_the_same_token():
    """同一个 token 从不同线索得到时只保留一次（按最先出现、即置信度最高的那条）。"""
    feed = GreenhouseFeed()
    candidates = feed.probe_candidates(
        ProbeContext(
            domain="acme.com",
            careers_url="https://boards.greenhouse.io/acme",
            homepage_html='<a href="https://boards.greenhouse.io/acme">招聘</a>',
        )
    )
    assert len({candidate.target.endpoint for candidate in candidates}) == 2
    assert all(candidate.confidence == CONFIDENCE_HIGH for candidate in candidates)


def test_candidates_always_zero_when_no_clues():
    feed = GreenhouseFeed()
    assert feed.probe_candidates(ProbeContext()) == []


# ===== 探测 =====


def _registry() -> FeedRegistry:
    registry = FeedRegistry()
    registry.register(GreenhouseFeed())
    return registry


async def test_probe_hits_when_board_has_jobs():
    http = FakeHttp(
        {
            "https://boards-api.greenhouse.io/v1/boards/acme/jobs": _board_payload(
                [{"id": 1, "title": "岗位"}]
            )
        }
    )
    outcome = await probe_site(
        http, ProbeContext(domain="acme.com"), registry=_registry()
    )
    assert outcome.state == PROBE_HIT
    assert outcome.found is True
    assert outcome.job_count == 1


async def test_probe_rejects_a_domain_guess_for_an_unrelated_board():
    """公开 Greenhouse demo 板不能因为 token 恰好撞名就归到当前公司。"""
    http = FakeHttp(
        {
            "https://boards-api.greenhouse.io/v1/boards/example/jobs": _board_payload(
                [{"id": 1, "title": "岗位", "company_name": "Democorp"}]
            )
        }
    )
    outcome = await probe_site(
        http,
        ProbeContext(company="Example", domain="example.com"),
        registry=_registry(),
    )
    assert outcome.state == PROBE_NOT_FOUND
    assert any("公司名称" in attempt.detail for attempt in outcome.attempts)


async def test_probe_accepts_a_domain_guess_when_board_company_matches():
    http = FakeHttp(
        {
            "https://boards-api.greenhouse.io/v1/boards/acme/jobs": _board_payload(
                [{"id": 1, "title": "岗位", "company_name": "Acme Corporation"}]
            )
        }
    )
    outcome = await probe_site(
        http,
        ProbeContext(company="Acme", domain="acme.com"),
        registry=_registry(),
    )
    assert outcome.state == PROBE_HIT


async def test_probe_ignores_empty_board_reached_by_guess():
    """**核心防呆**：猜出来的 token 即使端点存在，0 岗位也不算命中。

    有的系统在公司不存在时也返回 200 且总数为 0；认了它，对账就会报"0 条，已确认为全量"。
    """
    http = FakeHttp(
        {"https://boards-api.greenhouse.io/v1/boards/acme/jobs": _board_payload([])}
    )
    outcome = await probe_site(
        http, ProbeContext(domain="acme.com"), registry=_registry()
    )
    assert outcome.state == PROBE_NOT_FOUND


async def test_probe_accepts_empty_board_when_user_pointed_at_it():
    """例外：用户亲眼给的招聘页地址本身就是证据，此时 0 岗位是真实答案。"""
    http = FakeHttp(
        {"https://boards-api.greenhouse.io/v1/boards/acme/jobs": _board_payload([])}
    )
    outcome = await probe_site(
        http,
        ProbeContext(domain="acme.com", careers_url="https://boards.greenhouse.io/acme"),
        registry=_registry(),
    )
    assert outcome.state == PROBE_HIT
    assert outcome.job_count == 0
    assert "没有在招岗位" in outcome.detail


async def test_probe_reports_blocked_rather_than_not_found():
    """被阻断时不许报"未识别"——那是把"没看到"说成"没有"。"""
    http = FakeHttp(
        {}, default=FetchResult(block=BLOCK_RATE_LIMIT, status_code=429, detail="限流")
    )
    outcome = await probe_site(
        http, ProbeContext(domain="acme.com"), registry=_registry()
    )
    assert outcome.state == PROBE_BLOCKED


async def test_probe_respects_attempt_limit_and_admits_truncation():
    """达到尝试上限时如实记下"没试完"，而不是假装已经全部试过。"""
    http = FakeHttp({}, default=FetchResult(block=BLOCK_NOT_FOUND, status_code=404))
    outcome = await probe_site(
        http, ProbeContext(domain="acme.com"), registry=_registry(), max_attempts=1
    )
    assert len(http.calls) == 1
    assert outcome.untried > 0


async def test_a_truncated_probe_says_so_instead_of_concluding():
    """**"试到上限就停了"与"这家公司不用这套系统"是两件事**，而它们会落到同一个状态上。

    不说这一句，用户看到的就是"这家公司不在支持范围内"——一句我们并不知道真假的结论。
    模块自己的注释写着"如实记录被截断，而不是假装已经全部试过了"，这一条就是兑现它。
    """
    http = FakeHttp({}, default=FetchResult(block=BLOCK_NOT_FOUND, status_code=404))
    outcome = await probe_site(
        http, ProbeContext(domain="acme.com"), registry=_registry(), max_attempts=1
    )

    assert outcome.untried > 0
    assert "没来得及试" in outcome.detail
    assert str(outcome.untried) in outcome.detail


async def test_a_complete_probe_does_not_hedge():
    """没被截断时不要加这句废话——**每次都说"可能没试完"等于每次都没说**。"""
    http = FakeHttp({}, default=FetchResult(block=BLOCK_NOT_FOUND, status_code=404))
    outcome = await probe_site(http, ProbeContext(), registry=_registry())

    assert outcome.untried == 0
    assert "没来得及试" not in outcome.detail
