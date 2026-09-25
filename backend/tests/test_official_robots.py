"""``robots.txt`` 的取回与放行判定。

守一条取向：**读不到规则时不许假定可以抓**。把"站点正在故障"当成"站点允许"，等于在站点
最不希望被压上爬虫的时候加压；而误判成不允许只是让用户少一次采集，代价小得多。
"""
from __future__ import annotations

import pytest

from app.models.official import BLOCK_FORBIDDEN, BLOCK_NETWORK, BLOCK_NONE
from app.services.sites.official.base import FeedHttp, FetchResult
from app.services.sites.official.robots import (
    ROBOTS_ABSENT,
    ROBOTS_ALLOWED,
    ROBOTS_DISALLOWED,
    ROBOTS_UNREADABLE,
    RobotsAwareHttp,
    check_robots,
    decision_from_text,
    robots_url_for,
)


class FakeHttp(FeedHttp):
    def __init__(self, result: FetchResult):
        self._result = result
        self.calls: list[str] = []

    async def request(
        self, method, url, *, params=None, json_body=None, headers=None, max_bytes=None
    ) -> FetchResult:
        del method, params, json_body, headers, max_bytes
        self.calls.append(url)
        return self._result


# ===== 地址推导 =====


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://acme.com/careers/jobs", "https://acme.com/robots.txt"),
        ("https://acme.com:8443/careers", "https://acme.com:8443/robots.txt"),
        ("http://jobs.acme.com/", "http://jobs.acme.com/robots.txt"),
        ("not a url", ""),
        ("", ""),
    ],
)
def test_robots_url_for(url, expected):
    assert robots_url_for(url) == expected


# ===== 规则判定 =====


def test_open_site_is_allowed():
    decision = decision_from_text("User-agent: *\nDisallow:\n", "https://acme.com/jobs")
    assert decision.allowed is True
    assert decision.status == ROBOTS_ALLOWED


def test_disallowed_path_is_refused():
    text = "User-agent: *\nDisallow: /careers\n"
    decision = decision_from_text(text, "https://acme.com/careers/jobs")
    assert decision.allowed is False
    assert decision.status == ROBOTS_DISALLOWED
    assert "robots.txt" in decision.detail


def test_disallow_is_path_scoped():
    """只禁了 /careers，别的路径仍然可抓——不做"一禁全禁"的过度反应。"""
    text = "User-agent: *\nDisallow: /careers\n"
    assert decision_from_text(text, "https://acme.com/about").allowed is True


def test_empty_rules_mean_allowed():
    """内容为空的 robots.txt 是"没有限制"，与"读不到文件"不同。"""
    decision = decision_from_text("", "https://acme.com/jobs")
    assert decision.allowed is True


def test_crawl_delay_is_parsed():
    text = "User-agent: *\nCrawl-delay: 5\nDisallow:\n"
    decision = decision_from_text(text, "https://acme.com/jobs")
    assert decision.crawl_delay == 5.0


def test_crawl_delay_absent_is_none():
    decision = decision_from_text("User-agent: *\nDisallow:\n", "https://acme.com/jobs")
    assert decision.crawl_delay is None


def test_sitemaps_are_collected_for_later_cross_checking():
    """sitemap 在本项目里用于**事后集合对账**，不是发现入口——所以要解析出来存好。"""
    text = (
        "Sitemap: https://acme.com/sitemap.xml\n"
        "# 注释行不算\n"
        "sitemap: https://acme.com/jobs-sitemap.xml\n"
        "User-agent: *\nDisallow:\n"
    )
    decision = decision_from_text(text, "https://acme.com/jobs")
    assert decision.sitemaps == (
        "https://acme.com/sitemap.xml",
        "https://acme.com/jobs-sitemap.xml",
    )


def test_sitemap_like_text_inside_a_rule_is_not_mistaken_for_a_directive():
    text = "User-agent: *\nDisallow: /sitemap\n"
    assert decision_from_text(text, "https://acme.com/jobs").sitemaps == ()


# ===== 取回 =====


async def test_absent_file_is_treated_as_allowed():
    """404 表示"站点没有声明限制"，这是协议默认语义，不是我们放宽标准。"""
    http = FakeHttp(FetchResult(block="not_found", status_code=404))
    decision = await check_robots(http, "https://acme.com/jobs")
    assert decision.allowed is True
    assert decision.status == ROBOTS_ABSENT


async def test_unreadable_file_is_treated_as_disallowed():
    """5xx / 网络失败 → 保守视为不允许。

    "读不到规则就当作没有规则"会把站点故障期变成被加压的窗口。
    """
    for result in (
        FetchResult(block=BLOCK_NETWORK, status_code=0, detail="连接失败"),
        FetchResult(block="unknown", status_code=503, detail="服务端错误"),
    ):
        decision = await check_robots(FakeHttp(result), "https://acme.com/jobs")
        assert decision.allowed is False, result
        assert decision.status == ROBOTS_UNREADABLE


async def test_fetched_rules_are_applied():
    http = FakeHttp(
        FetchResult(
            block=BLOCK_NONE,
            status_code=200,
            text="User-agent: *\nDisallow: /careers\n",
        )
    )
    decision = await check_robots(http, "https://acme.com/careers/jobs")
    assert decision.allowed is False
    assert decision.status == ROBOTS_DISALLOWED


async def test_robots_is_fetched_from_the_site_root():
    http = FakeHttp(FetchResult(block="not_found", status_code=404))
    await check_robots(http, "https://acme.com/careers/jobs?team=ai")
    assert http.calls == ["https://acme.com/robots.txt"]


async def test_unparsable_target_is_unreadable_not_crash():
    http = FakeHttp(FetchResult(block=BLOCK_NONE, status_code=200, text=""))
    decision = await check_robots(http, "not a url")
    assert decision.allowed is False
    assert decision.status == ROBOTS_UNREADABLE
    assert http.calls == []


# ===== 装在传输层上的闸门 =====


class RoutedHttp(FeedHttp):
    """按 URL 前缀路由，记录每一次请求。"""

    def __init__(self, routes: dict[str, FetchResult]):
        self._routes = routes
        self.calls: list[str] = []

    async def request(self, method, url, *, params=None, json_body=None, headers=None, max_bytes=None):
        del method, params, json_body, headers, max_bytes
        self.calls.append(url)
        for prefix, result in self._routes.items():
            if url.startswith(prefix):
                return result
        return FetchResult(block=BLOCK_NONE, status_code=200, text="", headers={})


def _allow_robots() -> FetchResult:
    return FetchResult(block=BLOCK_NONE, status_code=200, text="User-agent: *\nDisallow:\n")


async def test_gate_blocks_disallowed_hosts_per_host():
    """**robots 按主机生效**：只查用户给的那个域名，就会漏掉真正被打的接口主机。

    这条用一个"招聘页主机允许、接口主机不允许"的站点把差别摆出来。
    """
    http = RoutedHttp(
        {
            "https://careers.example/robots.txt": _allow_robots(),
            "https://api.example/robots.txt": FetchResult(
                block=BLOCK_NONE, status_code=200, text="User-agent: *\nDisallow: /\n"
            ),
            "https://api.example/v1/jobs": FetchResult(block=BLOCK_NONE, status_code=200, text="[]"),
        }
    )
    gate = RobotsAwareHttp.wrap(http)

    allowed = await gate.request("GET", "https://careers.example/jobs")
    blocked = await gate.request("GET", "https://api.example/v1/jobs")

    assert allowed.ok is True
    assert blocked.block == BLOCK_FORBIDDEN
    assert "robots.txt" in blocked.detail
    assert "https://api.example/v1/jobs" not in [
        call for call in http.calls if call.endswith("/v1/jobs")
    ], "被 robots 拒绝的请求一个字节都不该发出去"


async def test_gate_queries_robots_once_per_host():
    """robots.txt 是主机级的，一次采集里同一个主机只查一次。"""
    http = RoutedHttp(
        {
            "https://careers.example/robots.txt": _allow_robots(),
            "https://careers.example/": FetchResult(block=BLOCK_NONE, status_code=200, text="ok"),
        }
    )
    gate = RobotsAwareHttp.wrap(http)

    await gate.request("GET", "https://careers.example/a")
    await gate.request("GET", "https://careers.example/b")
    await gate.request("GET", "https://careers.example/c")

    robots_calls = [call for call in http.calls if call.endswith("/robots.txt")]
    assert len(robots_calls) == 1


async def test_gate_wrapping_is_idempotent():
    """**幂等是必需的**：嵌套一层本类会导致取 robots.txt 自身时又去查它自己的 robots。

    那不是"慢一点"，而是无限递归。
    """
    http = RoutedHttp({"https://careers.example/robots.txt": _allow_robots()})
    once = RobotsAwareHttp.wrap(http)
    twice = RobotsAwareHttp.wrap(once)

    assert twice is once
    # 包两层也不会递归到栈溢出。
    assert (await twice.request("GET", "https://careers.example/jobs")).ok is True


async def test_gate_treats_a_failing_robots_fetch_as_disallowed():
    """读不到规则时保守拒绝——与直接调 check_robots 的取向一致。"""
    http = RoutedHttp(
        {"https://careers.example/robots.txt": FetchResult(block="network", status_code=0)}
    )
    gate = RobotsAwareHttp.wrap(http)

    result = await gate.request("GET", "https://careers.example/jobs")
    assert result.block == BLOCK_FORBIDDEN
