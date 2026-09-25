"""腾讯校园招聘适配器：公开接口形状与岗位字段映射。"""
from __future__ import annotations

import json

from app.models.official import BLOCK_NONE, BLOCK_SOFT
from app.services.sites.official.base import FeedHttp, FeedTarget, FetchResult, ProbeContext
from app.services.sites.official.feeds.tencent import (
    API_ENDPOINT,
    DETAIL_ENDPOINT,
    TencentFeed,
)


class FakeHttp(FeedHttp):
    def __init__(self, result: FetchResult):
        self.result = result
        self.calls: list[dict] = []

    async def request(self, method, url, *, params=None, json_body=None, headers=None, max_bytes=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "params": params,
                "json_body": json_body,
                "headers": headers,
                "max_bytes": max_bytes,
            }
        )
        return self.result


def _result(payload: dict) -> FetchResult:
    return FetchResult(block=BLOCK_NONE, status_code=200, text=json.dumps(payload), headers={})


def _position(post_id: str = "1282707395466077184") -> dict:
    return {
        "id": 22441,
        "positionTitle": "Agent开发工程师",
        "position": 784,
        "positionFamily": 2,
        "projectId": 1,
        "projectName": "应届毕业生",
        "recruitLabelName": "应届毕业生",
        "workCities": "深圳总部 北京 上海",
        "postId": post_id,
    }


def test_probe_only_claims_the_real_tencent_board():
    feed = TencentFeed()

    target = feed.probe_candidates(ProbeContext(careers_url="https://join.qq.com/post.html"))[0].target
    assert target.endpoint == API_ENDPOINT
    # 探测的样本大小不能污染正式采集时保存的 source params。
    assert target.params == {"project_id": "1"}
    assert feed.probe_candidates(ProbeContext(careers_url="https://example.com/post.html")) == []


async def test_position_api_page_maps_jobs_total_and_detail_targets():
    feed = TencentFeed()
    http = FakeHttp(_result({"status": 0, "data": {"positionList": [_position()], "count": 101}}))

    page = await feed.fetch_page(
        http,
        FeedTarget("tencent", API_ENDPOINT, params={"project_id": "1", "page_size": "50"}),
    )

    assert page.block == BLOCK_NONE
    assert page.total_hint == 101
    assert page.has_more is True
    assert page.cursor == "2"
    assert page.jobs[0].title == "Agent开发工程师"
    assert page.jobs[0].location == "深圳总部 北京 上海"
    assert page.jobs[0].job_type == "应届毕业生"
    assert page.jobs[0].url.endswith("postId=1282707395466077184")
    assert page.next_targets[0].endpoint == DETAIL_ENDPOINT
    assert page.next_targets[0].params == {"kind": "detail", "post_id": "1282707395466077184"}
    assert http.calls[0]["json_body"]["pageIndex"] == 1
    assert http.calls[0]["json_body"]["pageSize"] == 50


async def test_position_detail_maps_description_and_requirements():
    feed = TencentFeed()
    http = FakeHttp(
        _result(
            {
                "status": 0,
                "data": {
                    "title": "Agent开发工程师",
                    "postId": "1282707395466077184",
                    "desc": "负责智能Agent系统开发",
                    "request": "熟练掌握 Python",
                    "workCityList": ["深圳总部", "北京"],
                    "projectName": "应届毕业生",
                },
            }
        )
    )

    page = await feed.fetch_page(
        http,
        FeedTarget(
            "tencent",
            DETAIL_ENDPOINT,
            params={"kind": "detail", "post_id": "1282707395466077184"},
            depth=1,
        ),
    )

    assert page.jobs[0].description == "负责智能Agent系统开发"
    assert page.jobs[0].requirements == "熟练掌握 Python"
    assert page.jobs[0].location == "深圳总部、北京"
    assert http.calls[0]["params"] == {"postId": "1282707395466077184"}


async def test_position_api_shape_change_is_reported_as_soft_block():
    feed = TencentFeed()
    http = FakeHttp(_result({"status": 0, "data": {"items": []}}))

    page = await feed.fetch_page(http, FeedTarget("tencent", API_ENDPOINT))

    assert page.block == BLOCK_SOFT
    assert "结构异常" in page.detail
