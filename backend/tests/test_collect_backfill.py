"""「补齐详情」离线测试：只补空 JD、跳过回收站/无链接/不存在的岗位、进度口径、停止语义。

立场：证明它**按设计工作**（尤其是两条容易静默失效的性质——"抓不到时绝不写入空值"、
"补到 JD 后必须重算技能标签"），而不是确认某个函数存在。

复用 ``test_collector`` 已有的假适配器与辅助（``FakeCollectAdapter`` / ``_FakeClock`` /
``_config`` / ``_task``）：补详情走的是与搜索采集同一套"站点无关流程"，替身也该是同一套。

只在内存/临时库里跑，不联网、不起真浏览器、不真等限速。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from app.models.apply import TASK_KIND_COLLECT, ApplyTask
from app.models.job import Job
from app.schemas.apply import DEFAULT_COLLECT_PER_TASK_LIMIT, CollectConfigIn
from app.services import trash
from app.services.apply.collector import Collector
from app.services.apply.task_runner import TaskRunner, TaskStopped
from app.services.sites.base import FilterResolution, SearchPage, SiteFailure
from test_collector import FakeCollectAdapter, _FakeClock, _config, _task

# 一段含明显技能词的 JD：补到正文后若没重算标签，这里就没有 "Python"，标签相关的搜索会失效。
BACKFILLED_DETAIL = {
    "description": "负责后端服务开发，熟悉 Python 与 Kubernetes 的部署。",
    "requirements": "熟悉 Python，具备良好的工程习惯。",
}


class _DetailAdapter(FakeCollectAdapter):
    """按需返回详情 / 抛 SiteFailure 的适配器，并记录被取过详情的 URL。

    ``fetched`` 让"只补空"这类用例能**反证**：已经有描述的岗位根本没打开详情页。
    """

    def __init__(self, detail=None, *, fail: bool = False) -> None:
        super().__init__([])  # 补详情模式不走搜索翻页，pages 无意义
        self._detail = BACKFILLED_DETAIL if detail is None else detail
        self._fail = fail
        self.fetched: list[str] = []

    def fetch_job_detail(self, client, url):  # type: ignore[override]
        self.fetched.append(url)
        if self._fail:
            raise SiteFailure("selector_invalid", "详情页没抓到")
        return self._detail


def _empty_job(db_session, **overrides) -> Job:
    """一条 JD 为空、带投递链接的岗位——正是"补齐详情"要处理的历史形态。"""
    data = {
        "title": "后端开发",
        "company": "A公司",
        "description": "",
        "requirements": "",
        "source_url": "https://example.com/job/1",
    }
    data.update(overrides)
    job = Job(**data)
    db_session.add(job)
    db_session.commit()
    return job


def _run(db_session, task, adapter, ids, *, checkpoint=None):
    return Collector().run(
        session=db_session,
        task=task,
        client=object(),
        adapter=adapter,
        config=_config(),
        checkpoint=checkpoint if checkpoint is not None else (lambda: None),
        sleeper=lambda _seconds: None,
        clock=_FakeClock(),
        backfill_job_ids=ids,
    )


class _FilterRecordingAdapter(_DetailAdapter):
    """记录站点筛选有没有被解析过。

    "补详情模式不该解析站点筛选"这条只能靠**没被调用**来证明——它没有可观察的副作用，
    只能反证（同 ``_DetailAdapter.fetched`` 的思路）。
    """

    def __init__(self, detail=None, *, fail: bool = False, pages=None) -> None:
        super().__init__(detail, fail=fail)
        if pages is not None:
            self._pages = pages
        self.filter_calls = 0

    def prepare_collect_filters(self, selected, client=None):  # type: ignore[override]
        self.filter_calls += 1
        return FilterResolution()


def test_backfill_never_resolves_site_filters(db_session):
    """补详情是按用户点名的岗位逐个打开，不走搜索——筛选条件在这里没有任何作用。

    照解析一遍的代价不只是白读一次清单：浏览器停在岗位详情页时，适配器会为了读筛选栏
    **再开一次搜索页**，而用户只是想把几条旧岗位的 JD 补回来。
    """
    job = _empty_job(db_session)
    task = _task(db_session)
    adapter = _FilterRecordingAdapter()

    report = _run(db_session, task, adapter, [job.id])

    assert report.backfilled == 1
    assert adapter.filter_calls == 0, "补详情模式不该解析站点筛选条件"


def test_search_collect_still_resolves_site_filters(db_session):
    """正向的一半：搜索采集**必须**解析（否则站点侧筛选永远不生效）。"""
    task = _task(db_session)
    # 给一页空结果即可：本用例只问"有没有去解析筛选条件"，不关心采到什么。
    adapter = _FilterRecordingAdapter(pages=[SearchPage(results=[], page=1, has_next=False)])
    collector = Collector()
    collector.run(
        session=db_session,
        task=task,
        client=object(),
        adapter=adapter,
        config=_config(filters={"degree": "203"}),
        checkpoint=lambda: None,
        sleeper=lambda _seconds: None,
        clock=_FakeClock(),
    )
    assert adapter.filter_calls == 1


# ===== 采集器：补详情的判定与副作用 =====


def test_backfill_skips_jobs_that_already_have_a_description(db_session):
    """已有描述的岗位不被覆盖、连详情页都不打开，并如实计入 ``backfill_skipped``。

    "只补空"是这条功能的纪律：用户可能已经手工补过或改过 JD，自动流程不该覆盖他的劳动成果。
    覆盖与"多打开一次最慢的详情页"都是可避免的浪费。
    """
    job = _empty_job(db_session, description="我手工写的正文", requirements="我手工写的要求")
    task = _task(db_session)
    adapter = _DetailAdapter()

    report = _run(db_session, task, adapter, [job.id])

    assert job.description == "我手工写的正文"  # 一字未动
    assert job.requirements == "我手工写的要求"
    assert report.backfilled == 0
    assert report.backfill_skipped == 1
    assert adapter.fetched == []  # 已有描述 → 不必再取详情


def test_backfill_writes_the_jd_and_recomputes_keywords(db_session):
    """补到 JD 后必须**重算技能标签**，并刷新 ``updated_at``。

    只写正文、不重算标签，是那种"看起来补上了、搜索和匹配却仍按空标签走"的静默错误：
    页面显示了 JD，用户却搜不到这个岗位、匹配分析也读不到技能。这条断言就是为了钉住它。
    """
    job = _empty_job(db_session)
    # 把 updated_at 拨到过去，才能证明补齐确实刷新了它（而不是"值恰好没变"）。
    # 用**无时区** datetime：仓库的 utcnow() 是无时区 UTC（models/profile.py），列也不保留时区，
    # 拿 aware 字面量去比 naive 读回值会直接 TypeError——错误在测试这一侧，不是实现。
    job.updated_at = datetime(2000, 1, 1)
    db_session.commit()
    task = _task(db_session)

    report = _run(db_session, task, _DetailAdapter(), [job.id])

    assert report.backfilled == 1
    assert job.description.startswith("负责后端服务开发")
    assert job.requirements.startswith("熟悉 Python")
    names = {tag["name"] for tag in job.keywords}
    assert names, "补到 JD 却没有解析出任何技能标签"
    assert "Python" in names
    assert job.updated_at > datetime(2000, 1, 1)


@pytest.mark.parametrize("detail", [None, {}], ids=["抛 SiteFailure", "返回空字典"])
def test_backfill_leaves_the_jd_untouched_when_the_detail_still_cannot_be_fetched(db_session, detail):
    """仍然抓不到（页面改版 / 需登录 / 岗位已下线）→ 如实算跳过，且**绝不写入空值或占位符**。

    若把它计成成功、或写一个 ``""`` / ``None`` / "暂无" 上去，用户会以为补到了，而 JD 其实还是空。
    所以断言 description 恒等于原来的空串，而不是"没报错就算过"。
    """
    job = _empty_job(db_session)
    task = _task(db_session)
    adapter = _DetailAdapter(fail=True) if detail is None else _DetailAdapter(detail={})

    report = _run(db_session, task, adapter, [job.id])

    assert report.backfilled == 0
    assert report.backfill_skipped == 1
    assert adapter.fetched == [job.source_url]  # 确实尝试过打开详情页
    assert job.description == ""  # 不是 None，也不是占位符
    assert job.requirements == ""
    assert not job.keywords


def test_backfill_skips_jobs_in_the_trash(db_session):
    """回收站里的岗位不该被后台动作碰到——删了就是删了，补齐不该把它"复活"成有内容的样子。"""
    job = _empty_job(db_session)
    trash.soft_delete(db_session, "job", job)
    db_session.commit()
    task = _task(db_session)
    adapter = _DetailAdapter()

    report = _run(db_session, task, adapter, [job.id])

    assert report.backfilled == 0
    assert report.backfill_skipped == 1
    assert adapter.fetched == []
    assert job.description == ""


def test_backfill_skips_unknown_job_ids(db_session):
    """点名里混进一个不存在的 id：跳过、不报错——一个坏 id 不该让整批补详情崩掉。"""
    task = _task(db_session)

    report = _run(db_session, task, _DetailAdapter(), [999999])

    assert report.backfilled == 0
    assert report.backfill_skipped == 1


def test_backfill_skips_jobs_without_a_source_url(db_session):
    """没有投递链接就没有补详情的入口——补详情的唯一入口就是那个地址，只能如实跳过。"""
    job = _empty_job(db_session, source_url="")
    task = _task(db_session)
    adapter = _DetailAdapter()

    report = _run(db_session, task, adapter, [job.id])

    assert report.backfilled == 0
    assert report.backfill_skipped == 1
    assert adapter.fetched == []
    assert job.description == ""


def test_backfill_progress_counts_matches_the_backfill_ledger(db_session):
    """进度口径：补详情模式下 ``task.processed`` / ``succeeded`` 必须是补到的条数、
    ``skipped`` 必须是跳过的条数。

    界面按 ``已处理 {processed}/{total}`` 显示进度（``ApplyProgressPanel``）。若收尾时被
    改写回搜索口径（collected/skipped），补详情任务跑完会显示 ``已处理 0/N``——用户以为它
    没跑或白跑。这条断言把"两套模式的进度口径"钉死。
    """
    ok = _empty_job(db_session, source_url="https://example.com/job/1")
    blank = _empty_job(db_session, source_url="")  # 无链接 → 跳过
    task = _task(db_session)

    report = _run(db_session, task, _DetailAdapter(), [ok.id, blank.id])

    assert report.backfilled == 1 and report.backfill_skipped == 1
    assert task.processed == 1
    assert task.succeeded == 1
    assert task.skipped == 1


def test_backfill_writes_the_ledger_into_task_config(db_session):
    """补到几条、跳过几条要写进 ``task.config``：收尾文案（``_backfill_message``）与投递台的
    采集记录都读它。不写这两个数，用户只看到"任务完成"，不知道到底补上没有。"""
    ok = _empty_job(db_session, source_url="https://example.com/job/1")
    blank = _empty_job(db_session, source_url="")
    task = _task(db_session)

    _run(db_session, task, _DetailAdapter(), [ok.id, blank.id])

    assert task.config["backfilled"] == 1
    assert task.config["backfill_skipped"] == 1


def test_backfill_does_not_mix_in_the_search_detail_ledger(db_session):
    """补详情模式**不**写 ``detail_missing``：它是搜索采集的漂移账目，两套口径刻意分开，
    否则用户一次"点名补详情"会把站点的漂移计数搅乱。"""
    ok = _empty_job(db_session, source_url="https://example.com/job/1")
    task = _task(db_session)

    _run(db_session, task, _DetailAdapter(), [ok.id])

    assert "detail_missing" not in (task.config or {})


def test_backfill_checks_the_stop_signal_between_jobs(db_session):
    """每轮都 ``checkpoint()``——用户点「停止」才停得下来（否则按下去会没反应）。

    在第 2 次检查点抛 ``TaskStopped``：第 1 个岗位已补到、第 2 个必须原封不动，证明停止是在
    两轮**之间**生效，而不是等整批跑完。
    """
    first = _empty_job(db_session, source_url="https://example.com/job/1")
    second = _empty_job(db_session, source_url="https://example.com/job/2")
    task = _task(db_session)
    calls = {"n": 0}

    def checkpoint() -> None:
        calls["n"] += 1
        if calls["n"] >= 2:
            raise TaskStopped()

    with pytest.raises(TaskStopped):
        _run(db_session, task, _DetailAdapter(), [first.id, second.id], checkpoint=checkpoint)

    assert calls["n"] == 2
    assert first.description.startswith("负责后端服务开发")
    assert second.description == ""
    assert second.requirements == ""


# ===== 任务运行器：配置还原、目标 id 读取、收尾文案 =====


def _collect_task_with_snapshot(db_session) -> ApplyTask:
    """一个"补详情"任务的配置快照：既带用户设的采集参数，也带只属于这次任务的目标 id。"""
    task = ApplyTask(
        kind=TASK_KIND_COLLECT,
        status="running",
        total=2,
        config={"per_task_limit": 7, "interval_seconds": 5, "backfill_job_ids": [1, 2]},
    )
    db_session.add(task)
    db_session.commit()
    return task


def test_load_config_keeps_user_settings_when_it_ignores_task_only_keys(db_session):
    """``ignore=("backfill_job_ids",)`` 让"只属于这次任务的编排字段"不污染配置还原，
    用户设的 ``per_task_limit`` / 限速必须原样保留。"""
    task = _collect_task_with_snapshot(db_session)

    config = TaskRunner._load_config(task, CollectConfigIn, ignore=("backfill_job_ids",))

    assert config.per_task_limit == 7
    assert config.interval_seconds == 5


def test_load_config_reverts_to_defaults_when_task_only_keys_are_not_ignored(db_session):
    """反证 ``ignore=`` 不是可有可无的：``CollectConfigIn`` 是 ``extra="forbid"``，
    多一个 ``backfill_job_ids`` 就会让整份快照 ``model_validate`` 失败，兜底**静默退回全默认值**
    ——用户设的限速一起丢，而且不报错。

    这条钉住那个坑：以后谁删掉 ``ignore=`` 参数，这里会立刻变红，而不是让限速在运行时悄悄失效。
    """
    task = _collect_task_with_snapshot(db_session)

    config = TaskRunner._load_config(task, CollectConfigIn)  # 故意不传 ignore

    assert config.per_task_limit == DEFAULT_COLLECT_PER_TASK_LIMIT  # 7 被静默丢弃
    assert config.per_task_limit != 7


def _collect_task_with_sample_flag(db_session) -> ApplyTask:
    """一个"保存站点原文"任务的配置快照：既带用户设的采集参数，也带一次性的开关。"""
    task = ApplyTask(
        kind=TASK_KIND_COLLECT,
        status="running",
        total=1,
        config={"per_task_limit": 7, "backfill_job_ids": [], "save_site_samples": True},
    )
    db_session.add(task)
    db_session.commit()
    return task


def test_load_config_ignores_the_one_off_sample_flag(db_session):
    """``save_site_samples`` 与 ``backfill_job_ids`` 同属"只属于这次任务"的一次性键，还原配置时
    必须一起 ignore——否则 ``extra="forbid"`` 会让整份快照静默退回默认值，用户设的参数一起丢。"""
    task = _collect_task_with_sample_flag(db_session)

    config = TaskRunner._load_config(
        task, CollectConfigIn, ignore=("backfill_job_ids", "save_site_samples")
    )

    assert config.per_task_limit == 7


def test_load_config_reverts_to_defaults_when_sample_flag_is_not_ignored(db_session):
    """反证：漏掉 ``save_site_samples`` 的 ignore，采样开关就会把整份配置打回默认值。"""
    task = _collect_task_with_sample_flag(db_session)

    config = TaskRunner._load_config(task, CollectConfigIn, ignore=("backfill_job_ids",))

    assert config.per_task_limit == DEFAULT_COLLECT_PER_TASK_LIMIT


def test_backfill_job_ids_reads_and_normalizes_the_snapshot(db_session):
    """目标 id 从 ``task.config`` 读出并做宽松的 int 归一：快照被外部改坏一个值，
    不该让整批补详情崩掉（真正"该不该补"的判断在采集器里）。"""
    assert TaskRunner._backfill_job_ids(
        ApplyTask(kind=TASK_KIND_COLLECT, config={"backfill_job_ids": [1, "2", "坏值", None]})
    ) == [1, 2]
    # 非补详情任务（没有这个键）→ 空列表。
    assert TaskRunner._backfill_job_ids(ApplyTask(kind=TASK_KIND_COLLECT, config={})) == []


def test_backfill_message_reports_full_success():
    """全部补齐：说清补到几条，且不该出现"跳过"字样（没有跳过就别提）。"""
    message = TaskRunner._backfill_message({"backfilled": 3, "backfill_skipped": 0})

    assert "已为 3 条岗位补齐职位描述" in message
    assert "跳过" not in message


def test_backfill_message_reports_partial_skips():
    """部分跳过：补到的与跳过的都要说，且给出"为什么跳过"的三种成因。"""
    message = TaskRunner._backfill_message({"backfilled": 2, "backfill_skipped": 1})

    assert "已为 2 条岗位补齐职位描述" in message
    assert "另有 1 条跳过" in message
    assert "已有描述" in message and "仍然抓不到" in message


def test_backfill_message_says_nothing_was_backfilled():
    """一条都没补上：必须如实说明并给出下一步（确认岗位仍在线后重试），
    绝不能只说"完成"让用户以为补上了。"""
    message = TaskRunner._backfill_message({"backfilled": 0, "backfill_skipped": 2})

    assert "没有补到新的职位描述" in message
    assert "2 条岗位已跳过" in message
    assert "重试" in message


# ===== 站点筛选的账目必须出现在收尾文案里（2026-09-21）=====
#
# 后端把「哪几条站点筛选生效 / 哪几条没能生效」写进了 task.config。写进去不等于说出去：
# 收尾文案是用户最先看到的一句话（**完成通知里带的也是它**），漏掉就等于静默失效。


def test_message_reports_site_filters_that_did_not_take_effect():
    task = ApplyTask(
        kind=TASK_KIND_COLLECT,
        succeeded=4,
        config={"site_filter_unapplied": ["公司规模"], "site_filter_applied": ["学历要求：本科"]},
    )
    message = TaskRunner._collect_message(task)
    assert "公司规模" in message
    assert "没能生效" in message


def test_message_points_at_site_filters_when_nothing_came_back():
    """一条都没采到、站点筛选又开着时，默认文案会把人往"改关键词"上引——该提的是筛选条件。"""
    task = ApplyTask(
        kind=TASK_KIND_COLLECT,
        succeeded=0,
        config={"site_filter_applied": ["学历要求：本科", "融资阶段：A轮"]},
    )
    message = TaskRunner._collect_message(task)
    assert "学历要求：本科" in message and "融资阶段：A轮" in message
    assert "没有找到匹配的岗位" in message


def test_message_does_not_mention_site_filters_when_none_were_used():
    """没配站点筛选时文案保持原样——不能凭空多出一句让人以为自己筛过的话。"""
    task = ApplyTask(kind=TASK_KIND_COLLECT, succeeded=0, config={})
    message = TaskRunner._collect_message(task)
    assert "招聘网站的条件" not in message


def test_backfill_dispatch_does_not_change_search_mode_message():
    """补详情文案是**另一个模式**的：只有 config 里带 ``backfill_job_ids`` 时才走它。
    搜索采集的文案不能被改写——否则"已暂存 N 个岗位"会被换成驴唇不对马嘴的补详情说法。"""
    search = ApplyTask(kind=TASK_KIND_COLLECT, succeeded=3)
    search_message = TaskRunner._collect_message(search)
    assert "已暂存 3 个岗位" in search_message
    assert "补齐职位描述" not in search_message

    backfill = ApplyTask(kind=TASK_KIND_COLLECT, config={"backfill_job_ids": [1], "backfilled": 3})
    assert "已为 3 条岗位补齐职位描述" in TaskRunner._collect_message(backfill)


# ===== 跨模块回归：技能标签只有一份重算实现 =====


def test_create_and_update_recompute_keywords_through_the_same_path(db_session):
    """新建、更新、补齐三处都走同一个 ``refresh_job_keywords``，行为必须一致：
    标签始终是"按当前 JD 重算"，而不是"追加"或"只算一次"。"""
    from app.schemas.job import JobCreate, JobUpdate
    from app.services.job.job_service import create_job_record, update_job_record

    job = create_job_record(
        db_session, JobCreate(title="后端", company="A", description="使用 Python 开发服务。")
    )
    assert "Python" in {tag["name"] for tag in job.keywords}

    updated = update_job_record(
        db_session, job, JobUpdate(description="维护 Kubernetes 集群。")
    )
    names = {tag["name"] for tag in updated.keywords}
    assert "Kubernetes" in names
    assert "Python" not in names  # 重算而非追加：旧 JD 里的标签应当消失


def test_keyword_recompute_has_a_single_public_entry_point():
    """静态守卫：除 ``job_service`` 自身外，没有别的模块直接调用私有的 ``_keywords_for``。

    绕过 ``refresh_job_keywords`` 自己算一份，就是"补了 JD 却没更新标签"这类漂移的入口。
    用源码扫描把"目前只有一处实现"钉住；将来多一处调用会在这里变红。
    """
    import pathlib

    app_dir = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = [
        path.relative_to(app_dir).as_posix()
        for path in app_dir.rglob("*.py")
        if "_keywords_for" in path.read_text(encoding="utf-8") and path.name != "job_service.py"
    ]
    assert offenders == []
