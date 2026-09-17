"""岗位采集编排：翻页、去重、限速、可暂停，把结果落进既有 ``job`` 表。

为什么单独成模块：采集是"几步 CDP 调用 + 落库"的**站点无关流程**，站点特有的选择器
都在适配器里；这里只负责"翻页节奏、去重、别把自己搞崩"。

两条与任务运行器共享的纪律：
- 每一个 CDP 步骤前都调用 ``checkpoint()``（用户点停止要真的停得下来，暂停要真的等）；
- 采集条件里**无法映射到站点查询参数**的部分（薪资/经验/学历…）要如实记录，
  供界面显示「未生效」，绝不静默忽略。
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from sqlalchemy.orm import Session

from ...models.job import JOB_STATUS_OPEN, Job
from ...models.profile import utcnow
from ...schemas.apply import CollectConfigIn
from ..sites.base import CollectQuery, SearchResult, SiteAdapter, SiteFailure

logger = logging.getLogger(__name__)

# 采集来源标注（写进既有 Job 列，无需迁移）：来源站点名 + 识别来源。
COLLECT_RECOGNITION_SOURCE = "岗位采集"
MAX_COLLECT_PAGES = 30


@dataclass
class CollectReport:
    """一次采集的统计结果。"""

    collected: int = 0
    skipped: int = 0
    pages: int = 0
    unmapped_conditions: list[str] = field(default_factory=list)


class Collector:
    """采集编排器（翻页 + 去重 + 限速 + 可暂停）。"""

    def __init__(self, *, max_pages: int = MAX_COLLECT_PAGES) -> None:
        self._max_pages = max_pages

    def run(
        self,
        *,
        session: Session,
        task: Any,
        client: Any,
        adapter: SiteAdapter,
        config: CollectConfigIn,
        checkpoint: Callable[[], None],
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> CollectReport:
        report = CollectReport()
        limit = config.per_task_limit
        query = CollectQuery(
            keywords=list(config.keywords),
            city=config.city,
            salary_min=config.salary_min,
            experience=config.experience,
            education=config.education,
        )
        unmapped: set[str] = set()

        page = 1
        while report.collected < limit and page <= self._max_pages:
            checkpoint()
            page_query = replace(query, page=page)
            page_result = adapter.collect_search(client, page_query, page)
            report.pages += 1
            unmapped.update(page_result.unmapped_conditions)

            for result in page_result.results:
                if report.collected >= limit:
                    break
                checkpoint()
                if not result.url:
                    continue
                if self._find_existing(session, result) is not None:
                    report.skipped += 1
                    continue
                detail = self._fetch_detail(adapter, client, result)
                job = self._build_job(adapter, result, detail)
                session.add(job)
                session.flush()
                report.collected += 1
                self._update_task_progress(session, task, report)
                self._pace(
                    config.interval_seconds, config.interval_jitter_seconds, checkpoint, sleeper, clock
                )

            if not page_result.has_next:
                break
            page += 1
            self._pace(
                config.interval_seconds, config.interval_jitter_seconds, checkpoint, sleeper, clock
            )

        report.unmapped_conditions = sorted(unmapped)
        if report.unmapped_conditions:
            task.config = {
                **(task.config or {}),
                "unmapped_conditions": report.unmapped_conditions,
            }
        task.processed = report.collected
        task.succeeded = report.collected
        task.skipped = report.skipped
        session.commit()
        return report

    # ===== 内部步骤 =====

    def _find_existing(self, session: Session, result: SearchResult) -> Job | None:
        """去重（第一道闸）：同一投递链接，或同一公司下的同名岗位，都算重复。"""
        if result.url:
            existing = session.query(Job).filter(Job.source_url == result.url).first()
            if existing is not None:
                return existing
        if result.company and result.title:
            existing = (
                session.query(Job)
                .filter(Job.company == result.company, Job.title == result.title)
                .first()
            )
            if existing is not None:
                return existing
        return None

    def _fetch_detail(self, adapter: SiteAdapter, client: Any, result: SearchResult) -> dict[str, Any]:
        """尽力抓取岗位详情；失败不影响主流程（列表信息已经够用）。"""
        fetch = getattr(adapter, "fetch_job_detail", None)
        if fetch is None:
            return {}
        try:
            return fetch(client, result.url) or {}
        except SiteFailure as exc:
            logger.warning("采集岗位详情失败（不影响主流程）：%s", exc.detail)
            return {}

    def _build_job(
        self, adapter: SiteAdapter, result: SearchResult, detail: dict[str, Any]
    ) -> Job:
        return Job(
            title=result.title or str(detail.get("job_title", "")),
            company=result.company or str(detail.get("company", "")),
            location=result.location,
            salary=result.salary,
            description=str(detail.get("description", "")),
            requirements=str(detail.get("requirements", "")),
            source=result.source or adapter.display_name,
            source_url=result.url,
            recognition_source=COLLECT_RECOGNITION_SOURCE,
            status=JOB_STATUS_OPEN,
            created_at=utcnow(),
            updated_at=utcnow(),
        )

    @staticmethod
    def _update_task_progress(session: Session, task: Any, report: CollectReport) -> None:
        task.processed = report.collected
        task.succeeded = report.collected
        task.skipped = report.skipped
        session.commit()

    @staticmethod
    def _pace(
        interval: int,
        jitter: int,
        checkpoint: Callable[[], None],
        sleeper: Callable[[float], None],
        clock: Callable[[], float],
    ) -> None:
        total = max(0, interval)
        if jitter:
            total += random.uniform(0, jitter)
        end = clock() + total
        while True:
            checkpoint()
            remaining = end - clock()
            if remaining <= 0:
                return
            sleeper(min(0.2, remaining))


__all__ = ["COLLECT_RECOGNITION_SOURCE", "MAX_COLLECT_PAGES", "CollectReport", "Collector"]
