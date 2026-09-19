"""站点健康度测试：纯判据（哪种失败算"改版"、哪种不算）、读库归因、以及 API 端点。

立场：把"采集悄悄抓不到东西"的静默失败变成**看得见、且不误报**的 degraded 标记。最容易错的
两件事——把环境/用户侧问题（需登录、验证码、超时、真没搜到）误算成"站点改版"，以及在样本
不足时报警——都在这里逐条钉住。
"""
from __future__ import annotations

import pytest

from app.models.apply import (
    FAILURE_CAPTCHA_REQUIRED,
    FAILURE_LOGIN_REQUIRED,
    FAILURE_NETWORK_TIMEOUT,
    FAILURE_SELECTOR_INVALID,
    FAILURE_UNKNOWN,
    TASK_KIND_COLLECT,
    ApplyTask,
)
from app.models.job import Job
from app.services.apply.collector import Collector
from app.services.apply.task_runner import TaskRunner
from app.services.browser.cdp_client import CdpError
from app.services.site_health import (
    MIN_SAMPLES_FOR_DEGRADED,
    RECENT_COLLECT_WINDOW,
    STATUS_DEGRADED,
    STATUS_OK,
    evaluate_site_health,
    recent_collect_summaries,
    site_health_overview,
)
from app.services.sites.base import SearchPage, SearchResult, SiteFailure

# 复用既有替身与运行器辅助：采集/运行器路径的替身散落在别处已是仓库惯例
# （``test_collect_backfill`` 也这样 import），另一份实现只会与真流程漂移。
from test_apply_collect_guard import CollectAdapter, FakeCdp, _collect_task, _registry, _wait
from test_collector import FakeCollectAdapter, _FakeClock, _config


def _summary(
    *,
    status: str = "completed",
    failure_category: str = "",
    succeeded: int = 0,
    detail_missing: int = 0,
    created_at: str = "2024-01-01T00:00:00",
) -> dict:
    return {
        "status": status,
        "failure_category": failure_category,
        "succeeded": succeeded,
        "detail_missing": detail_missing,
        "created_at": created_at,
    }


# ===== 纯判据：算作"站点可能改版"的信号 =====


def test_selector_failure_marks_the_site_degraded():
    """选择器失效（页面结构变化）是"改版"最直接的证据——有样本、出现一次即报警。"""
    health = evaluate_site_health(
        [
            _summary(status="completed", succeeded=3),
            _summary(status="failed", failure_category=FAILURE_SELECTOR_INVALID),
        ]
    )

    assert health.status == STATUS_DEGRADED
    assert health.selector_failures == 1
    assert any("改版" in reason for reason in health.reasons)


def test_success_with_mostly_empty_detail_marks_the_site_degraded():
    """"能采到列表、却读不出详情"是本功能最该捕获的漂移——任务显示成功，JD 却全是空的。"""
    health = evaluate_site_health(
        [
            _summary(status="completed", succeeded=8, detail_missing=8),
            _summary(status="completed", succeeded=4, detail_missing=0),
        ]
    )

    assert health.status == STATUS_DEGRADED
    assert health.detail_drift_runs == 1
    assert any("详情" in reason for reason in health.reasons)


# ===== 纯判据：明确**不算**的信号（防误报）=====


@pytest.mark.parametrize(
    "category",
    [FAILURE_LOGIN_REQUIRED, FAILURE_CAPTCHA_REQUIRED, FAILURE_NETWORK_TIMEOUT],
)
def test_environment_and_user_side_failures_are_not_degraded(category):
    """需登录 / 验证码 / 超时是**环境或用户侧**问题，把它们算成"站点改版"会天天误报。"""
    health = evaluate_site_health(
        [
            _summary(status="failed", failure_category=category),
            _summary(status="completed", succeeded=2, detail_missing=0),
        ]
    )

    assert health.status == STATUS_OK
    assert health.reasons == []


def test_genuinely_empty_result_is_not_degraded():
    """真的没搜到（succeeded=0）不是漂移：采集器"成功但没新增"是正常结果。"""
    health = evaluate_site_health(
        [
            _summary(status="completed", succeeded=0),
            _summary(status="completed", succeeded=0),
        ]
    )

    assert health.status == STATUS_OK


def test_partial_detail_missing_is_not_degraded():
    """只有部分详情为空（未过半）不算漂移——单条偶发抓不到是正常的。"""
    health = evaluate_site_health(
        [
            _summary(status="completed", succeeded=8, detail_missing=2),
            _summary(status="completed", succeeded=10, detail_missing=4),
        ]
    )

    assert health.status == STATUS_OK
    assert health.detail_drift_runs == 0


def test_exactly_half_detail_missing_is_not_degraded():
    """恰好一半不算"超过一半"——阈值是严格大于，边界不误报。

    这里**必须放两条样本**：只有 1 条时"样本 < 2 恒为 ok"的闸门会先返回，即使把判据写成
    `>=`（恰好在边界误报）这条用例也照样绿——那样它只是"看起来在测边界"，实际什么都没测。
    带上第 2 条正常样本，`detail_drift_runs` 才会真正被边界值驱动。
    """
    health = evaluate_site_health(
        [
            _summary(status="completed", succeeded=4, detail_missing=2),  # 恰好一半
            _summary(status="completed", succeeded=10, detail_missing=0),
        ]
    )

    assert health.sampled == 2
    assert health.detail_drift_runs == 0
    assert health.status == STATUS_OK


def test_just_over_half_detail_missing_is_degraded():
    """刚过一半就报警：3 条里 2 条详情缺失（2 > 1.5）——从**另一侧**钉住同一个边界，
    保证阈值既不是"大于等于"、也不是"远远超过"才报。"""
    health = evaluate_site_health(
        [
            _summary(status="completed", succeeded=3, detail_missing=2),
            _summary(status="completed", succeeded=10, detail_missing=0),
        ]
    )

    assert health.detail_drift_runs == 1
    assert health.status == STATUS_DEGRADED


def test_the_window_only_looks_at_the_latest_five_collections():
    """窗口只取最近 5 次：第 6 次（更早的 selector_invalid）必须被排除。

    不设窗口，上周那次改版造成的失败会长期压着标记不放，"这周已经修好"也不会消失——
    用户很快就不再相信这个标记。
    """
    recent_five = [_summary(status="completed", succeeded=3) for _ in range(5)]
    older_sixth = _summary(status="failed", failure_category=FAILURE_SELECTOR_INVALID)

    health = evaluate_site_health([*recent_five, older_sixth])

    assert health.sampled == RECENT_COLLECT_WINDOW == 5
    assert health.selector_failures == 0
    assert health.status == STATUS_OK


def test_a_user_stopped_run_does_not_count_toward_detail_drift():
    """用户中途停止的采集只反映用户行为，其残缺统计不得算成站点漂移。"""
    health = evaluate_site_health(
        [
            _summary(status="stopped", succeeded=1, detail_missing=1),
            _summary(status="completed", succeeded=3, detail_missing=0),
        ]
    )

    assert health.status == STATUS_OK


# ===== 纯判据：样本不足时不报警 =====


def test_a_single_run_never_alarms_even_when_it_looks_bad():
    """样本不足（只有 1 次记录）时宁可不报，也不要制造噪声。"""
    health = evaluate_site_health([_summary(status="failed", failure_category=FAILURE_SELECTOR_INVALID)])

    assert health.status == STATUS_OK
    assert health.reasons == []
    assert health.sampled == 1


def test_no_runs_is_ok():
    health = evaluate_site_health([])

    assert health.status == STATUS_OK
    assert health.sampled == 0
    assert MIN_SAMPLES_FOR_DEGRADED >= 2


def test_evaluate_tolerates_broken_summaries():
    """摘要字段可能来自被改坏的 JSON——判据必须容错，绝不能因此抛异常。"""
    health = evaluate_site_health(
        [
            {"status": "completed", "succeeded": "坏值", "detail_missing": None},
            {"status": "completed", "succeeded": 5, "detail_missing": 0},
        ]
    )

    assert health.status == STATUS_OK


# ===== 读库：按站点归因 =====


def _task(
    db_session,
    *,
    site_key: str | None = "boss",
    status: str = "completed",
    succeeded: int = 0,
    detail_missing: int = 0,
    failure_category: str = "",
    backfill: bool = False,
) -> ApplyTask:
    config: dict = {}
    if site_key is not None:
        config["site_key"] = site_key
    if detail_missing:
        config["detail_missing"] = detail_missing
    if failure_category:
        config["failure_category"] = failure_category
    if backfill:
        config["backfill_job_ids"] = [1]
    task = ApplyTask(kind=TASK_KIND_COLLECT, status=status, succeeded=succeeded, config=config)
    db_session.add(task)
    db_session.commit()
    return task


def test_recent_summaries_only_include_the_requested_site(db_session):
    _task(db_session, site_key="boss", succeeded=3)
    _task(db_session, site_key="other", succeeded=9)

    summaries = recent_collect_summaries(db_session, "boss")

    assert len(summaries) == 1
    assert summaries[0]["succeeded"] == 3


def test_recent_summaries_exclude_backfill_and_unfinished_runs(db_session):
    """补详情任务是用户点名的一次性修补，账目不同，不进健康度；未结束的任务也不进。"""
    _task(db_session, site_key="boss", succeeded=1)
    _task(db_session, site_key="boss", backfill=True)
    _task(db_session, site_key="boss", status="running")

    summaries = recent_collect_summaries(db_session, "boss")

    assert len(summaries) == 1


def test_recent_summaries_exclude_legacy_tasks_without_a_site_key(db_session):
    """旧任务没有 site_key（本功能之前采集的），不应被误算到任何站点。"""
    _task(db_session, site_key=None, succeeded=5)

    assert recent_collect_summaries(db_session, "boss") == []


def test_overview_reports_each_registered_site(db_session):
    """默认注册表里 BOSS 是唯一站点；没有样本时是 ok。"""
    overview = site_health_overview(db_session)

    assert [item.site_key for item in overview] == ["boss"]
    assert overview[0].display_name == "BOSS直聘"
    assert overview[0].status == STATUS_OK


def test_overview_becomes_degraded_from_recorded_failures(db_session):
    """端到端：记录层写下的 failure_category 能被读库层正确归因成 degraded。"""
    _task(db_session, site_key="boss", status="completed", succeeded=2)
    _task(
        db_session,
        site_key="boss",
        status="failed",
        failure_category=FAILURE_SELECTOR_INVALID,
    )

    overview = site_health_overview(db_session)

    assert overview[0].status == STATUS_DEGRADED
    assert overview[0].selector_failures == 1


# ===== API 端点 =====


def test_site_health_endpoint_returns_the_overview(client, db_session):
    _task(db_session, site_key="boss", status="completed", succeeded=1)
    _task(
        db_session,
        site_key="boss",
        status="failed",
        failure_category=FAILURE_SELECTOR_INVALID,
    )

    response = client.get("/api/collect/site-health")

    assert response.status_code == 200
    body = response.json()
    assert [site["site_key"] for site in body["sites"]] == ["boss"]
    site = body["sites"][0]
    assert site["status"] == STATUS_DEGRADED
    assert site["display_name"] == "BOSS直聘"
    assert site["reasons"]  # 原因来自后端，前端只展示
    assert site["recent"]  # 最近几次的统计明细


def test_site_health_route_is_registered():
    """把路由名与对外路径绑死：改名会让前端静默打到 404。"""
    from app.application import create_app

    assert "/api/collect/site-health" in set(create_app().openapi()["paths"])


def test_site_health_endpoint_is_ok_and_not_an_error_on_a_fresh_database(client):
    """全新库（一条采集任务都没有）：必须 200 且不报 degraded——绝不能 500。

    首次启动的用户点开投递台就会打到这个接口，"没有数据"是正常状态、不是错误。
    """
    response = client.get("/api/collect/site-health")

    assert response.status_code == 200
    body = response.json()
    assert [site["site_key"] for site in body["sites"]] == ["boss"]
    site = body["sites"][0]
    assert site["status"] == STATUS_OK
    assert site["sampled"] == 0
    assert site["reasons"] == []


def test_site_health_endpoint_reports_ok_without_reasons(client, db_session):
    """ok 态的返回形状：状态为 ok、原因为空、样本数如实——前端据此不渲染告警。"""
    _task(db_session, site_key="boss", status="completed", succeeded=5)
    _task(db_session, site_key="boss", status="completed", succeeded=3)

    site = client.get("/api/collect/site-health").json()["sites"][0]

    assert site["status"] == STATUS_OK
    assert site["reasons"] == []
    assert site["sampled"] == 2


# ===== 读库层：脏数据的健壮性（一个脏批次不该让整个投递台崩）=====


@pytest.mark.parametrize("bad_config", [["列表"], "字符串", 123], ids=["列表", "字符串", "整数"])
def test_read_layer_tolerates_a_corrupted_non_dict_config(db_session, bad_config):
    """``task.config`` 是从库里读出来的 JSON，可能是脏的（不是 dict）。

    不能因为一条脏批次就让 ``GET /api/collect/site-health`` 抛 500——那会把"看不见漂移"直接
    变成"整个投递台报错"。按"读不出来就算它不属于任何站点"处理：跳过这一条，其余照常统计。
    """
    _task(db_session, site_key="boss", succeeded=3)  # 一条正常记录：证明其余仍能被读到
    broken = ApplyTask(kind=TASK_KIND_COLLECT, status="completed", succeeded=1, config=bad_config)
    db_session.add(broken)
    db_session.commit()

    summaries = recent_collect_summaries(db_session, "boss")
    overview = site_health_overview(db_session)

    assert len(summaries) == 1  # 脏的那条被跳过，正常的仍在
    assert overview[0].status == STATUS_OK


def test_a_backfill_batch_never_feeds_the_health_judgement(db_session):
    """补详情批次不进窗口：它是用户点名的一次性修补，账目与正常采集不同，混进来会搅乱判据。"""
    _task(db_session, site_key="boss", status="completed", succeeded=3)
    _task(
        db_session,
        site_key="boss",
        status="failed",
        failure_category=FAILURE_SELECTOR_INVALID,
        backfill=True,
    )

    overview = site_health_overview(db_session)

    assert overview[0].sampled == 1
    assert overview[0].status == STATUS_OK


# ===== 记录层：site_key / failure_category 的取值 =====


def test_collect_site_key_reads_the_selected_site(db_session):
    from app.schemas.apply import ApplyConfigIn
    from app.services.apply import apply_service

    apply_service.save_apply_config(db_session, ApplyConfigIn(site_key="boss"))
    db_session.commit()

    assert TaskRunner._collect_site_key(db_session) == "boss"


def test_collect_site_key_stays_empty_when_it_cannot_be_read(db_session, monkeypatch):
    """配置读取失败 → 留空，**不**回退到"注册表第一个站点"。

    编造一个默认站点会把别站点的问题算到它头上——"站点归因指向错误站点"比"归因不到"更糟，
    用户会照着错误的告警去排查一个根本没问题的站点。
    """

    def boom(_session):
        raise RuntimeError("配置损坏")

    monkeypatch.setattr("app.services.apply.apply_service.get_apply_config", boom)

    assert TaskRunner._collect_site_key(db_session) == ""


def test_collect_site_key_does_not_fall_back_to_the_first_registered_site(db_session, monkeypatch):
    """配置里站点为空串时也留空——不得用 ``adapters[0].key`` 顶上。"""
    from app.schemas.apply import ApplyConfigIn

    monkeypatch.setattr(
        "app.services.apply.apply_service.get_apply_config",
        lambda _session: ApplyConfigIn(site_key=""),
    )

    assert TaskRunner._collect_site_key(db_session) == ""


def test_record_failure_category_falls_back_to_unknown():
    """非 ``SiteFailure`` 的失败路径（无适配器 / 连不上浏览器 / CdpError）没有分类可取，
    必须落 ``unknown`` 而不是留空或 ``None``——留空会让前端/判据去猜。"""
    task = ApplyTask(kind=TASK_KIND_COLLECT, config={})

    TaskRunner._record_failure_category(task, "")

    assert task.config["failure_category"] == FAILURE_UNKNOWN


def test_record_failure_category_keeps_a_real_category():
    """能取到分类时原样保留——健康度靠 ``selector_invalid`` 区分"站点改版"与"环境/用户侧"。"""
    task = ApplyTask(kind=TASK_KIND_COLLECT, config={})

    TaskRunner._record_failure_category(task, FAILURE_SELECTOR_INVALID)

    assert task.config["failure_category"] == FAILURE_SELECTOR_INVALID


# ===== 采集器：detail_missing 的计数口径与写入模式 =====


def _one_result_pages(url: str = "https://example.com/1") -> list[SearchPage]:
    return [
        SearchPage(
            results=[SearchResult(title="后端开发", company="A公司", url=url)],
            has_next=False,
        )
    ]


class _FailingDetailAdapter(FakeCollectAdapter):
    """详情页抛 ``SiteFailure``（采集器内部拿不到详情 → 返回 ``{}``）。"""

    def fetch_job_detail(self, client, url):  # type: ignore[override]
        raise SiteFailure(FAILURE_SELECTOR_INVALID, "详情页没抓到")


class _NoDetailCapabilityAdapter(FakeCollectAdapter):
    """适配器没有详情能力：把 ``fetch_job_detail`` 显式置 ``None``，等价于"从未实现该方法"。

    采集器用 ``getattr(adapter, "fetch_job_detail", None)`` 取能力，取到 ``None`` 时返回 ``{}``。
    这种情况同样算"没拿到详情"——否则一个只采列表、不读详情的站点永远不会被识别成漂移。
    """

    fetch_job_detail = None  # type: ignore[assignment]


def _run_collect(db_session, task, adapter, *, backfill_job_ids=None):
    return Collector().run(
        session=db_session,
        task=task,
        client=object(),
        adapter=adapter,
        config=_config(),
        checkpoint=lambda: None,
        sleeper=lambda _seconds: None,
        clock=_FakeClock(),
        backfill_job_ids=backfill_job_ids,
    )


def test_detail_missing_counts_a_failing_detail_fetch(db_session):
    """详情页抛 ``SiteFailure`` → 计入 ``detail_missing``（本条仍然暂存）。"""
    report = _run_collect(db_session, _task(db_session), _FailingDetailAdapter(_one_result_pages()))

    assert report.collected == 1  # 拿不到详情也要暂存，缺的只是 JD
    assert report.detail_missing == 1


def test_detail_missing_counts_when_the_adapter_has_no_detail_capability(db_session):
    """适配器没有详情能力 → 同样计入 ``detail_missing``。"""
    report = _run_collect(
        db_session, _task(db_session), _NoDetailCapabilityAdapter(_one_result_pages())
    )

    assert report.collected == 1
    assert report.detail_missing == 1


def test_detail_missing_is_zero_when_the_detail_body_is_present(db_session):
    """详情拿到了正文 → 不计缺失，健康度不该因为一次正常采集而报警。"""
    report = _run_collect(db_session, _task(db_session), FakeCollectAdapter(_one_result_pages()))

    assert report.collected == 1
    assert report.detail_missing == 0


def test_detail_missing_ledger_is_written_only_in_search_mode(db_session):
    """``detail_missing`` 只由**搜索采集**写进 ``task.config``；补详情模式不写这个键。

    两套口径刻意分开：补详情有自己的账目（backfilled / backfill_skipped）。若混用，用户一次
    "点名补详情"就会把站点的漂移计数搅乱——健康度于是报出一个与实际采集无关的 degraded。
    """
    search_task = _task(db_session)
    _run_collect(db_session, search_task, _FailingDetailAdapter(_one_result_pages()))
    assert search_task.config["detail_missing"] == 1

    job = Job(title="后端开发", company="A公司", description="", source_url="https://example.com/1")
    db_session.add(job)
    db_session.commit()
    backfill_task = _task(db_session)
    _run_collect(
        db_session,
        backfill_task,
        _FailingDetailAdapter([]),
        backfill_job_ids=[job.id],
    )

    assert "detail_missing" not in (backfill_task.config or {})


# ===== 运行器：非 SiteFailure 的三条失败路径都落明确分类 =====


def _cannot_connect(_config):
    raise RuntimeError("无法连接投递专用浏览器")


class _CdpErrorAdapter(CollectAdapter):
    def collect_search(self, client, query, page):  # type: ignore[override]
        raise CdpError("CDP 连接中断")


def _run_runner(db_session, task, registry, client_factory):
    runner = TaskRunner(
        registry=registry,
        client_factory=client_factory,
        sleeper=lambda _seconds: None,
        clock=_FakeClock(),
        poll_interval=0.01,
    )
    runner.start(task.id)
    _wait(runner)
    runner.shutdown()
    db_session.expire_all()
    return db_session.get(ApplyTask, task.id)


def test_collect_browser_connection_failure_records_unknown(db_session):
    """连不上浏览器（非 ``SiteFailure``）→ ``failure_category`` 落 ``unknown``。"""
    task = _collect_task(db_session)

    stored = _run_runner(
        db_session,
        task,
        _registry(CollectAdapter(page=SearchPage(results=[], has_next=False))),
        _cannot_connect,
    )

    assert stored.status == "failed"
    assert stored.config["failure_category"] == FAILURE_UNKNOWN


def test_collect_cdp_error_records_unknown(db_session):
    """``CdpError`` 路径 → ``failure_category`` 落 ``unknown``。"""
    task = _collect_task(db_session)

    stored = _run_runner(
        db_session,
        task,
        _registry(_CdpErrorAdapter(page=SearchPage(results=[], has_next=False))),
        lambda _config: FakeCdp(),
    )

    assert stored.status == "failed"
    assert stored.config["failure_category"] == FAILURE_UNKNOWN
