"""采集编排离线测试：翻页、去重、限速、可暂停、未映射条件记录。"""
import pytest

from app.models.apply import TASK_KIND_COLLECT, ApplyTask
from app.models.job import Job
from app.schemas.apply import CollectConfigIn
from app.services.apply.collector import Collector
from app.services.apply.task_runner import TaskStopped
from app.services.sites.base import (
    ApplyOutcome,
    CollectQuery,
    RiskProfile,
    SearchPage,
    SearchResult,
    SiteAdapter,
)


class _FakeClock:
    """每次读表都大步前进，让限速循环立即结束（离线测试不真等）。"""

    def __init__(self) -> None:
        self._t = 0.0

    def __call__(self) -> float:
        self._t += 100.0
        return self._t


class FakeCollectAdapter(SiteAdapter):
    key = "fake"
    display_name = "示例站点"
    hosts = ("example.com",)

    def __init__(self, pages: list[SearchPage]) -> None:
        self._pages = pages
        self.searched_pages: list[int] = []

    def risk_profile(self) -> RiskProfile:
        return RiskProfile(key=self.key)

    def collect_search(self, client, query: CollectQuery, page: int) -> SearchPage:
        self.searched_pages.append(page)
        return self._pages[min(page - 1, len(self._pages) - 1)]

    def open_apply(self, client, job):  # pragma: no cover - 采集不用
        raise AssertionError("采集不应调用投递")

    def fill_and_submit(self, client, data, greeting) -> ApplyOutcome:  # pragma: no cover
        raise AssertionError("采集不应调用投递")

    def fetch_job_detail(self, client, url):  # type: ignore[override]
        return {"description": "岗位详情正文", "requirements": "任职要求正文"}


def _task(db_session) -> ApplyTask:
    task = ApplyTask(kind=TASK_KIND_COLLECT, status="running", total=20, config={})
    db_session.add(task)
    db_session.commit()
    return task


def _config(**overrides) -> CollectConfigIn:
    data = {
        "keywords": ["后端"],
        "city": "北京",
        "per_task_limit": 10,
        "interval_seconds": 1,
        "interval_jitter_seconds": 0,
    }
    data.update(overrides)
    return CollectConfigIn(**data)


def test_collector_pages_and_saves_jobs(db_session):
    pages = [
        SearchPage(
            results=[
                SearchResult(title="后端开发", company="A公司", url="https://example.com/1"),
                SearchResult(title="数据开发", company="B公司", url="https://example.com/2"),
            ],
            page=1,
            has_next=True,
        ),
        SearchPage(
            results=[SearchResult(title="算法工程", company="C公司", url="https://example.com/3")],
            page=2,
            has_next=False,
        ),
    ]
    adapter = FakeCollectAdapter(pages)
    task = _task(db_session)

    report = Collector().run(
        session=db_session,
        task=task,
        client=object(),
        adapter=adapter,
        config=_config(),
        checkpoint=lambda: None,
        sleeper=lambda _seconds: None,
        clock=_FakeClock(),
    )

    assert report.collected == 3
    assert report.pages == 2
    assert adapter.searched_pages == [1, 2]
    assert db_session.query(Job).count() == 3
    saved = db_session.query(Job).filter(Job.source_url == "https://example.com/1").one()
    assert saved.source == "示例站点"
    assert saved.recognition_source == "岗位采集"
    assert saved.requirements == "任职要求正文"
    assert task.processed == 3 and task.succeeded == 3


def test_collector_dedupes_existing_jobs(db_session):
    db_session.add(Job(title="后端开发", company="A公司", source_url="https://example.com/1"))
    db_session.commit()
    pages = [
        SearchPage(
            results=[
                SearchResult(title="后端开发", company="A公司", url="https://example.com/1"),
                SearchResult(title="新岗位", company="D公司", url="https://example.com/9"),
            ],
            has_next=False,
        )
    ]
    task = _task(db_session)

    report = Collector().run(
        session=db_session,
        task=task,
        client=object(),
        adapter=FakeCollectAdapter(pages),
        config=_config(),
        checkpoint=lambda: None,
        sleeper=lambda _seconds: None,
        clock=_FakeClock(),
    )

    assert report.collected == 1
    assert report.skipped == 1
    assert db_session.query(Job).count() == 2


def test_collector_records_unmapped_conditions(db_session):
    pages = [
        SearchPage(
            results=[SearchResult(title="后端开发", company="A公司", url="https://example.com/1")],
            has_next=False,
            unmapped_conditions=["薪资", "学历"],
        )
    ]
    task = _task(db_session)

    Collector().run(
        session=db_session,
        task=task,
        client=object(),
        adapter=FakeCollectAdapter(pages),
        config=_config(salary_min=20, education="本科"),
        checkpoint=lambda: None,
        sleeper=lambda _seconds: None,
        clock=_FakeClock(),
    )

    assert set(task.config.get("unmapped_conditions", [])) == {"薪资", "学历"}


def test_collector_stops_when_checkpoint_signals_stop(db_session):
    calls = {"count": 0}

    def checkpoint() -> None:
        calls["count"] += 1
        if calls["count"] >= 2:  # 用户点停止：下一步骤前抛出
            raise TaskStopped()

    pages = [
        SearchPage(
            results=[SearchResult(title="后端开发", company="A公司", url="https://example.com/1")],
            has_next=True,
        )
    ]
    task = _task(db_session)

    with pytest.raises(TaskStopped):
        Collector().run(
            session=db_session,
            task=task,
            client=object(),
            adapter=FakeCollectAdapter(pages),
            config=_config(),
            checkpoint=checkpoint,
            sleeper=lambda _seconds: None,
            clock=_FakeClock(),
        )
