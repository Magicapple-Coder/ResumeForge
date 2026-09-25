"""存活校验：某个岗位页现在还在不在招。

这组用例的重心是**判据的不对称性**。把「还在招」误判成「已下架」会让对账宣称"已确认为全量"，
而实际上漏了岗位——那是本功能最坏的结果。所以 ``GONE`` 只认两种结构化证据（404/410、
``validThrough`` 已过期），其余一律 ``UNKNOWN``，其中最要紧的是**被站点拦住时绝不能判下架**：
我们并不知道那边是什么。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.models.official import BLOCK_NONE, BLOCK_RATE_LIMIT, BLOCK_UNKNOWN
from app.services.sites.official.base import FeedHttp, FetchResult
from app.services.sites.official.verify import (
    MAX_VERIFY_PER_RUN,
    VERIFIED_GONE,
    VERIFIED_LIVE,
    VERIFIED_UNKNOWN,
    is_expired,
    verify_all,
    verify_job_url,
)

URL = "https://acme.example/jobs/1"


class FakeHttp(FeedHttp):
    def __init__(self, result: FetchResult):
        self._result = result
        self.calls: list[str] = []

    async def request(self, method, url, *, params=None, json_body=None, headers=None,
                      max_bytes=None):
        del method, params, json_body, headers, max_bytes
        self.calls.append(url)
        return self._result


def _page(**posting_overrides) -> FetchResult:
    payload = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "大模型应用开发工程师",
        "description": "<p>职责</p>",
    }
    payload.update(posting_overrides)
    html = (
        "<html><head>"
        f'<script type="application/ld+json">{json.dumps(payload, ensure_ascii=False)}</script>'
        "</head><body></body></html>"
    )
    return FetchResult(block=BLOCK_NONE, status_code=200, text=html, headers={})


# ===== 时间解析 =====


def test_expired_with_z_suffix():
    """``Z`` 后缀在 Python 3.10 的 ``fromisoformat`` 上不被接受，要先归一化。

    本项目支持 3.10–3.13，所以这条在 3.10 上会失败、在 3.11+ 上通过——正是需要一条用例
    钉住的地方。
    """
    past = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert is_expired(past) is True


def test_future_is_not_expired():
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    assert is_expired(future) is False


def test_naive_timestamp_is_understood_as_utc():
    past = (datetime.now(timezone.utc) - timedelta(days=1)).replace(tzinfo=None).isoformat()
    assert is_expired(past) is True


@pytest.mark.parametrize("value", [None, "", "不是时间", 123, {}, "2026-13-45"])
def test_unparsable_valid_through_is_not_treated_as_expired(value):
    """**解析不出来就不判下架**：那是危险方向。"""
    assert is_expired(value) is False


# ===== 单条校验 =====


async def test_404_means_gone():
    result = await verify_job_url(FakeHttp(FetchResult(block="not_found", status_code=404)), URL)
    assert result.state == VERIFIED_GONE
    assert "404" in result.detail


async def test_410_means_gone():
    result = await verify_job_url(FakeHttp(FetchResult(block="not_found", status_code=410)), URL)
    assert result.state == VERIFIED_GONE


async def test_blocked_page_is_unknown_never_gone():
    """**最要紧的一条**：被拦住时我们并不知道那边是什么，绝不能因此判它下架。

    判成下架会让对账宣称"已确认为全量"，而实际上可能整批岗位都还在招。
    """
    for block, status in (
        (BLOCK_RATE_LIMIT, 429),
        (BLOCK_UNKNOWN, 503),
        ("network", 0),
        ("timeout", 0),
        ("captcha", 200),
    ):
        result = await verify_job_url(
            FakeHttp(FetchResult(block=block, status_code=status, detail="被拦")), URL
        )
        assert result.state == VERIFIED_UNKNOWN, block
        assert result.conclusive is False


async def test_live_posting_is_recognised():
    result = await verify_job_url(FakeHttp(_page()), URL)
    assert result.state == VERIFIED_LIVE
    assert "大模型应用开发工程师" in result.detail


async def test_expired_posting_is_gone():
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    result = await verify_job_url(FakeHttp(_page(validThrough=past)), URL)
    assert result.state == VERIFIED_GONE
    assert "有效期" in result.detail


async def test_future_valid_through_is_still_live():
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    result = await verify_job_url(FakeHttp(_page(validThrough=future)), URL)
    assert result.state == VERIFIED_LIVE


async def test_200_without_postings_is_unknown():
    """200 但不是岗位页（被重定向到列表页、或结构不认识）→ **判不出来**。

    这类"看起来还在但不是岗位页"正是靠文案判据会误判的地方，所以这里如实返回未知。
    """
    http = FakeHttp(
        FetchResult(block=BLOCK_NONE, status_code=200, text="<html><body>招聘首页</body></html>")
    )
    result = await verify_job_url(http, URL)
    assert result.state == VERIFIED_UNKNOWN
    assert "读不到岗位" in result.detail


async def test_empty_url_is_unknown_without_a_request():
    http = FakeHttp(_page())
    result = await verify_job_url(http, "   ")
    assert result.state == VERIFIED_UNKNOWN
    assert http.calls == [], "空地址不该白打一次请求"


# ===== 批量 =====


async def test_batch_is_capped():
    """核实是抽查不是补抓：待核实候选可能上千条，逐条访问等于对站点发起一次扫描。"""
    http = FakeHttp(_page())
    urls = [f"https://acme.example/jobs/{index}" for index in range(100)]

    results = await verify_all(http, urls)

    assert len(results) == MAX_VERIFY_PER_RUN
    assert len(http.calls) == MAX_VERIFY_PER_RUN


async def test_batch_is_serial():
    """串行：并发会给站点一瞬间的压力峰值，而被限流的代价是全部返回"无法判断"。"""
    order: list[str] = []

    class Ordered(FakeHttp):
        async def request(self, method, url, **kwargs):
            order.append("start")
            result = await super().request(method, url, **kwargs)
            order.append("end")
            return result

    await verify_all(Ordered(_page()), [f"https://acme.example/jobs/{i}" for i in range(3)])

    assert order == ["start", "end", "start", "end", "start", "end"]
