"""采集编排离线测试：翻页、去重、限速、可暂停、未映射条件记录。

**采集不写岗位广场**（用户实测反馈后的产品决定）：采到的东西先落进「备选岗位」暂存区，
由用户勾选后才导入。这里钉住的正是这条边界——`Job` 表在采集阶段必须纹丝不动。
"""
import pytest

from app.models.apply import TASK_KIND_COLLECT, ApplyTask
from app.models.job import Job
from app.models.material import CANDIDATE_JOB_PENDING, CandidateJob
from app.schemas.apply import CollectConfigIn
from app.services.apply.collector import Collector
from app.services.apply.task_runner import TaskStopped
from app.services.candidate_jobs import stage_candidate_job
from app.services.sites.base import (
    ApplyOutcome,
    CollectQuery,
    RiskProfile,
    SearchPage,
    SearchResult,
    SiteAdapter,
    SiteFailure,
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
    # 声明这三项走本地筛选，与真实适配器（BOSS）的契约一致——采集器的筛选是**门控在这份
    # 声明之内**的，测试里不声明就测不到筛选行为。
    post_filter_conditions = ("薪资", "经验", "学历")

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


def test_collector_pages_and_stages_candidates(db_session):
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
    # **关键边界**：采集阶段岗位广场必须还是空的——采到的东西只进暂存区。
    assert db_session.query(Job).count() == 0

    staged = db_session.query(CandidateJob).order_by(CandidateJob.id).all()
    assert [item.title for item in staged] == ["后端开发", "数据开发", "算法工程"]
    first = staged[0]
    assert first.company == "A公司"
    assert first.source == "示例站点"
    assert first.source_url == "https://example.com/1"
    # 详情抓到的 JD 两段各归各位（暂存区也保留这份结构，导入时不必重新切）。
    assert first.description == "岗位详情正文"
    assert first.requirements == "任职要求正文"
    assert first.status == CANDIDATE_JOB_PENDING
    # 批次 id 让人能"按批次回看这次采到了什么"。
    assert first.collect_task_id == task.id
    assert task.processed == 3 and task.succeeded == 3


def test_collector_dedupes_against_both_the_job_board_and_the_staging_area(db_session):
    """去重必须**两张表都看**：只看岗位广场会在暂存区堆出重复候选，只看暂存区会把
    已经在岗位广场里的岗位重新捞回来。"""
    db_session.add(Job(title="后端开发", company="A公司", source_url="https://example.com/1"))
    stage_candidate_job(
        db_session, title="旧候选", company="E公司", source_url="https://example.com/8"
    )
    db_session.commit()

    pages = [
        SearchPage(
            results=[
                SearchResult(title="后端开发", company="A公司", url="https://example.com/1"),
                SearchResult(title="旧候选", company="E公司", url="https://example.com/8"),
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
    assert report.skipped == 2
    # 采集仍然没有往岗位广场写任何东西。
    assert db_session.query(Job).count() == 1
    # 暂存区是"原有 1 条 + 新增 1 条"，没有把已有的那条再存一遍。
    assert db_session.query(CandidateJob).count() == 2
    assert (
        db_session.query(CandidateJob).filter(CandidateJob.title == "新岗位").count() == 1
    )


def test_collector_stages_a_candidate_even_when_the_detail_fetch_fails(db_session):
    """详情抓失败时仍要暂存：标题/公司/城市/薪资/链接都已经拿到了，缺的只是 JD。

    把整条丢掉，等于"因为拿不到详情，连这个岗位都不要了"——而用户在暂存区里恰恰可以
    自己判断这条值不值得导入。
    """

    class _NoDetailAdapter(FakeCollectAdapter):
        def fetch_job_detail(self, client, url):  # type: ignore[override]
            raise SiteFailure("selector_invalid", "详情页没抓到")

    pages = [
        SearchPage(
            results=[
                SearchResult(
                    title="后端开发",
                    company="A公司",
                    location="天津",
                    salary="20-30K",
                    url="https://example.com/1",
                )
            ],
            has_next=False,
        )
    ]
    task = _task(db_session)

    report = Collector().run(
        session=db_session,
        task=task,
        client=object(),
        adapter=_NoDetailAdapter(pages),
        config=_config(),
        checkpoint=lambda: None,
        sleeper=lambda _seconds: None,
        clock=_FakeClock(),
    )

    assert report.collected == 1
    staged = db_session.query(CandidateJob).one()
    assert staged.title == "后端开发"
    assert staged.location == "天津"
    assert staged.salary == "20-30K"
    assert staged.description == ""


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


def test_collector_filters_by_education_and_keeps_what_it_cannot_judge(db_session):
    """填了学历 → 岗位要求高于它的被筛掉，**没写学历的保留**，并把账记清。

    这两件事必须一起做到：只筛不记账，用户不知道漏了多少；为了"筛干净"把没写学历的也
    一起排除，就会悄悄丢掉他真正想要的岗位。
    """
    pages = [
        SearchPage(
            results=[
                SearchResult(
                    title="要求硕士的岗位",
                    company="A公司",
                    url="https://example.com/1",
                    extra={"degree": "硕士"},
                ),
                SearchResult(
                    title="要求大专的岗位",
                    company="B公司",
                    url="https://example.com/2",
                    extra={"degree": "大专"},
                ),
                SearchResult(
                    title="没写学历的岗位",
                    company="C公司",
                    url="https://example.com/3",
                    extra={},
                ),
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
        config=_config(education="本科"),
        checkpoint=lambda: None,
        sleeper=lambda _seconds: None,
        clock=_FakeClock(),
    )

    assert report.filtered == 1
    assert report.collected == 2
    titles = {item.title for item in db_session.query(CandidateJob).all()}
    assert titles == {"要求大专的岗位", "没写学历的岗位"}

    assert task.config["filtered_out"] == 1
    assert task.config["filter_reasons"] == ["学历"]
    # 没写学历的那条被保留，但要如实记为"未能判断"。
    assert task.config["filter_undecided"] == ["学历"]
    assert task.config["filter_undecided_count"] == 1
    assert task.config["filter_applied"] == ["薪资", "经验", "学历"]


def test_collector_reports_an_unparsable_condition_as_unapplied(db_session):
    """用户填了读不懂的学历词 → 如实报「没能用上」，绝不装作筛过了。

    这正是本项目反复出现的"静默失效"：界面标着生效，代码里什么也没做。
    """
    pages = [
        SearchPage(
            results=[
                SearchResult(
                    title="岗位",
                    company="A公司",
                    url="https://example.com/1",
                    extra={"degree": "本科"},
                )
            ],
            has_next=False,
        )
    ]
    task = _task(db_session)

    Collector().run(
        session=db_session,
        task=task,
        client=object(),
        adapter=FakeCollectAdapter(pages),
        config=_config(education="管培生"),
        checkpoint=lambda: None,
        sleeper=lambda _seconds: None,
        clock=_FakeClock(),
    )

    assert task.config["filter_unapplied"] == ["学历"]
    assert task.config["filtered_out"] == 0
    assert db_session.query(CandidateJob).count() == 1


def test_collector_treats_a_trashed_job_as_existing_and_says_so(db_session):
    """**回收站里的岗位也算"已存在"**，并且要单独计数。

    不算已存在的话，"删掉 → 再采集一次"会造出第二条同一岗位，而用户以为自己只是删了一条。
    单独计数则是因为这两种"跳过"对用户的含义完全不同：一种是"早就在库里了"，另一种是
    "你之前删过它"——后者不说清楚，用户会以为删除没生效。
    """
    from app.services import trash

    job = Job(title="删过的岗位", company="A公司", source_url="https://example.com/1")
    db_session.add(job)
    db_session.commit()
    trash.soft_delete(db_session, "job", job)
    db_session.commit()

    pages = [
        SearchPage(
            results=[
                SearchResult(title="删过的岗位", company="A公司", url="https://example.com/1")
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

    assert report.collected == 0
    assert report.skipped == 1
    assert report.skipped_trashed == 1
    assert task.config["skipped_trashed"] == 1
    # 没有新建第二条。
    assert db_session.query(Job).count() == 1


def test_collector_does_not_filter_when_the_adapter_does_not_declare_it(db_session):
    """适配器没声明本地筛选能力时**不筛**——不能拿"缺失的字段"当判断依据去误杀岗位。"""

    class _NoFilterAdapter(FakeCollectAdapter):
        post_filter_conditions = ()

    pages = [
        SearchPage(
            results=[
                SearchResult(
                    title="要求硕士的岗位",
                    company="A公司",
                    url="https://example.com/1",
                    extra={"degree": "硕士"},
                )
            ],
            has_next=False,
        )
    ]
    task = _task(db_session)

    report = Collector().run(
        session=db_session,
        task=task,
        client=object(),
        adapter=_NoFilterAdapter(pages),
        config=_config(education="本科"),
        checkpoint=lambda: None,
        sleeper=lambda _seconds: None,
        clock=_FakeClock(),
    )

    assert report.filtered == 0
    assert report.collected == 1
    # 没有任何条件被本地处理过，就不该写这套账目。
    assert "filtered_out" not in (task.config or {})


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


# ===== 详情缺失：站点漂移唯一留下的痕迹 =====


def test_collector_counts_staged_candidates_whose_detail_is_missing(db_session):
    """能采到列表、却抓不到详情时，任务仍是"成功"的——不把这个数记下来，"站点漂移"就完全
    看不见（历史上"8 条岗位 JD 全空"就是这样发生的）。"""

    class _NoDetailAdapter(FakeCollectAdapter):
        def fetch_job_detail(self, client, url):  # type: ignore[override]
            raise SiteFailure("selector_invalid", "详情页没抓到")

    pages = [
        SearchPage(
            results=[SearchResult(title="后端开发", company="A公司", url="https://example.com/1")],
            has_next=False,
        )
    ]
    task = _task(db_session)

    report = Collector().run(
        session=db_session,
        task=task,
        client=object(),
        adapter=_NoDetailAdapter(pages),
        config=_config(),
        checkpoint=lambda: None,
        sleeper=lambda _seconds: None,
        clock=_FakeClock(),
    )

    assert report.collected == 1
    assert report.detail_missing == 1
    # 收尾时写进 config，供站点健康度识别"详情普遍为空"。
    assert task.config["detail_missing"] == 1


def test_collector_does_not_count_detail_missing_when_details_are_present(db_session):
    """详情正常抓到时 ``detail_missing`` 为 0——健康度不该因为一次正常采集而报警。"""
    pages = [
        SearchPage(
            results=[SearchResult(title="后端开发", company="A公司", url="https://example.com/1")],
            has_next=False,
        )
    ]
    task = _task(db_session)

    report = Collector().run(
        session=db_session,
        task=task,
        client=object(),
        adapter=FakeCollectAdapter(pages),  # 详情返回非空正文
        config=_config(),
        checkpoint=lambda: None,
        sleeper=lambda _seconds: None,
        clock=_FakeClock(),
    )

    assert report.detail_missing == 0
    assert task.config["detail_missing"] == 0
