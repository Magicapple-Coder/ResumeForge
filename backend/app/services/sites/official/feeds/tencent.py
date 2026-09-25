"""腾讯校园招聘（``join.qq.com``）的公开岗位接口适配器。

腾讯的 ``post.html`` 是 Vue 空壳页，岗位列表和详情都通过公开 JSON 接口获取。通用网页
抽取只能看到导航链接，因此会把这个地址误判成"页面可读但没有岗位"；这里直接走站点自己的
查询契约，并把接口返回的岗位总数交给对账层。
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from .....models.official import BLOCK_NONE, BLOCK_SOFT
from ..base import (
    CONFIDENCE_HIGH,
    FeedHttp,
    FeedJob,
    FeedPage,
    FeedTarget,
    JobFeed,
    ProbeContext,
    ProbeHit,
)

KEY = "tencent"
DISPLAY_NAME = "腾讯校园招聘"
BOARD_HOSTS = ("join.qq.com", "www.join.qq.com")
API_ENDPOINT = "https://join.qq.com/api/v1/position/searchPosition"
DETAIL_ENDPOINT = "https://join.qq.com/api/v1/jobDetails/getJobDetailsByPostId"
PROJECT_ID = "1"  # 当前校园招聘页默认展示的「应届毕业生」项目。
PAGE_SIZE = 50
MAX_BYTES = 8_000_000


def _is_board_url(url: str) -> bool:
    try:
        return (urlsplit(url).hostname or "").casefold() in BOARD_HOSTS
    except ValueError:
        return False


def _position_url(post_id: str) -> str:
    return f"https://join.qq.com/jobdesc.html?postId={post_id}"


def _as_text(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _parse_position(raw: Any) -> FeedJob | None:
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("positionTitle") or raw.get("title") or "").strip()
    post_id = str(raw.get("postId") or raw.get("post_id") or "").strip()
    if not title or not post_id:
        return None
    return FeedJob(
        title=title,
        location=_as_text(raw.get("workCities") or raw.get("workCityList")),
        url=_position_url(post_id),
        job_type=str(raw.get("recruitLabelName") or raw.get("projectName") or "").strip(),
        external_id=post_id,
        extra={
            "id": raw.get("id"),
            "position": raw.get("position"),
            "position_family": raw.get("positionFamily"),
            "project_id": raw.get("projectId"),
            "project_name": raw.get("projectName"),
            "position_source": raw.get("positionSource"),
        },
    )


def _parse_detail(raw: Any, post_id: str) -> FeedJob | None:
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or "").strip()
    if not title:
        return None
    return FeedJob(
        title=title,
        location=_as_text(raw.get("workCityList") or raw.get("workCity")),
        url=_position_url(post_id),
        description=str(raw.get("desc") or "").strip(),
        requirements=str(raw.get("request") or "").strip(),
        job_type=str(raw.get("recruitLabelName") or raw.get("projectName") or "").strip(),
        external_id=post_id,
        extra={"project_id": raw.get("projectId"), "position_family": raw.get("fid")},
    )


class TencentFeed(JobFeed):
    key = KEY
    display_name = DISPLAY_NAME
    board_hosts = BOARD_HOSTS
    provides_total = True
    empty_entry_is_conclusive = True
    paginates = True

    def probe_candidates(self, ctx: ProbeContext) -> list[ProbeHit]:
        if not _is_board_url(ctx.careers_url):
            return []
        return [
            ProbeHit(
                target=FeedTarget(
                    feed_key=KEY,
                    endpoint=API_ENDPOINT,
                    # 探测不应把"一条样本"的页大小持久化，否则正式采集会永远一页一条地跑完整个职位板。
                    params={"project_id": PROJECT_ID},
                ),
                confidence=CONFIDENCE_HIGH,
                evidence="你提供的招聘页地址是腾讯校园招聘页面，直接读取其公开岗位接口",
            )
        ]

    async def fetch_page(
        self, http: FeedHttp, target: FeedTarget, *, cursor: str = ""
    ) -> FeedPage:
        if target.params.get("kind") == "detail":
            return await self._fetch_detail(http, target)

        page_index = int(cursor or target.params.get("page_index", "1"))
        page_size = int(target.params.get("page_size", str(PAGE_SIZE)))
        result = await http.request(
            "POST",
            target.endpoint,
            json_body={
                "projectId": int(target.params.get("project_id", PROJECT_ID)),
                "keyword": "",
                "bgList": [],
                "workCountryType": 1,
                "workCityList": [],
                "recruitCityList": [],
                "positionFidList": [],
                "pageIndex": page_index,
                "pageSize": page_size,
            },
            headers={"Referer": "https://join.qq.com/post.html"},
            max_bytes=MAX_BYTES,
        )
        if not result.ok:
            return FeedPage(block=result.block, status_code=result.status_code, detail=result.detail)

        payload = result.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(payload, dict) or payload.get("status") != 0 or not isinstance(data, dict):
            return FeedPage(
                block=BLOCK_SOFT,
                status_code=result.status_code,
                detail="腾讯岗位接口返回结构异常，可能接口已改版",
            )

        raw_jobs = data.get("positionList")
        total = data.get("count")
        if not isinstance(raw_jobs, list) or not isinstance(total, int):
            return FeedPage(
                block=BLOCK_SOFT,
                status_code=result.status_code,
                detail="腾讯岗位接口返回结构异常：没有返回岗位列表或总数，可能接口已改版",
            )

        jobs = [job for raw in raw_jobs if (job := _parse_position(raw)) is not None]
        has_more = page_index * page_size < total
        next_targets = [
            FeedTarget(
                feed_key=KEY,
                endpoint=DETAIL_ENDPOINT,
                params={"kind": "detail", "post_id": job.external_id},
                depth=1,
            )
            for job in jobs
        ]
        return FeedPage(
            jobs=jobs,
            total_hint=total,
            has_more=has_more,
            cursor=str(page_index + 1) if has_more else "",
            next_targets=next_targets,
            block=BLOCK_NONE,
            status_code=result.status_code,
        )

    async def _fetch_detail(self, http: FeedHttp, target: FeedTarget) -> FeedPage:
        post_id = target.params.get("post_id", "").strip()
        if not post_id:
            return FeedPage(block=BLOCK_SOFT, detail="腾讯岗位详情缺少 postId")
        result = await http.request(
            "GET",
            target.endpoint,
            params={"postId": post_id},
            headers={"Referer": "https://join.qq.com/post.html"},
            max_bytes=MAX_BYTES,
        )
        if not result.ok:
            return FeedPage(block=result.block, status_code=result.status_code, detail=result.detail)
        payload = result.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        job = _parse_detail(data, post_id) if isinstance(payload, dict) and payload.get("status") == 0 else None
        if job is None:
            return FeedPage(
                block=BLOCK_SOFT,
                status_code=result.status_code,
                detail="腾讯岗位详情接口返回结构异常，可能接口已改版",
            )
        return FeedPage(jobs=[job], block=BLOCK_NONE, status_code=result.status_code)


__all__ = [
    "API_ENDPOINT",
    "BOARD_HOSTS",
    "DETAIL_ENDPOINT",
    "KEY",
    "PAGE_SIZE",
    "TencentFeed",
]
