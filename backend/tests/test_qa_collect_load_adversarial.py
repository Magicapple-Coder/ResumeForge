"""QA 独立对抗测试（第 1、2 节）：证明"未加载就抓"这个缺陷真的被修掉了。

立场：**证明它能工作，而不是确认它存在**。这些用例不重跑工程师的断言，而是自己构造
"页面还没加载好 → 之后才出现内容"的原始缺陷场景，以及围绕"0 结果"判定的每个边界分支。

关键手法：用一个按脚本回放"就绪探针"的假 CDP 客户端，让前若干次探针返回"空 / 未就绪"，
直到第 N+1 次才吐出真实岗位卡片。原实现在第一次就会 break 并报 0，修复后必须**真的采到**。

只在内存/临时库里跑，不联网、不起真浏览器。
"""
from __future__ import annotations

import json

import pytest

from app.models.apply import FAILURE_LOGIN_REQUIRED, FAILURE_CAPTCHA_REQUIRED, FAILURE_SELECTOR_INVALID
from app.services.browser.cdp_client import CdpClient
from app.services.browser.page_ready import ReadyWait, wait_for_page_state
from app.services.sites.base import CollectQuery, SiteFailure
from app.services.sites.boss import BossAdapter


class ScriptedReadyClient(CdpClient):
    """按脚本回放"就绪探针"状态的假 CDP 客户端。

    - ``readiness`` 是一个状态序列，第 i 次 ``rf:readiness`` 取第 i 个（越界后重复最后一个）；
      用它模拟"页面从空白/加载中逐渐变成有内容"。
    - ``rf:collect`` 固定返回 ``collect_payload``，并记录调用次数。
    - ``rf:url``（导航前记录当前地址）固定返回 ``previous_url``。
    """

    def __init__(self, *, readiness, collect_payload=None, previous_url="about:blank"):
        self._readiness = list(readiness)
        self._collect_payload = collect_payload
        self._previous_url = previous_url
        self._index = 0
        self.readiness_probes = 0
        self.collect_calls = 0
        self.new_tab_calls = 0
        self.navigations: list[str] = []

    def list_targets(self):
        return []

    def new_tab(self, url: str = "about:blank") -> str:
        self.new_tab_calls += 1
        return "tab"

    def navigate(self, url: str, *, timeout=None):
        self.navigations.append(url)
        return {}

    def send(self, method, params=None, *, timeout=None):
        return {}

    def set_file_input(self, selector, files, *, timeout=None):
        return None

    def evaluate(self, expression, *, timeout=None):
        if "rf:url" in expression:
            return {"url": self._previous_url}
        if "rf:readiness" in expression:
            self.readiness_probes += 1
            state = self._readiness[min(self._index, len(self._readiness) - 1)]
            self._index += 1
            return dict(state)
        if "rf:collect" in expression:
            self.collect_calls += 1
            return self._collect_payload
        return None

    def close(self):
        return None


def _adapter(timeout: float = 5.0, poll: float = 0.002) -> BossAdapter:
    return BossAdapter(ready_wait=ReadyWait(timeout=timeout, poll_interval=poll))


QUERY = CollectQuery(keywords=["后端"], city="北京")
REAL_ITEM = {
    "title": "后端开发工程师",
    "company": "示例科技",
    "salary": "20-30K",
    "location": "北京",
    "url": "https://www.zhipin.com/job_detail/1.html",
}


# ===== 第 1 节：原始缺陷场景——"前 N 次空，第 N+1 次才有内容" =====


def test_original_defect_loads_then_actually_collects():
    """原始缺陷：探针前几次都读不到卡片（页面尚未加载好）。修复后必须最终采到，而不是报 0。

    原实现 ``new_tab`` 后立刻 ``evaluate``，在空白文档上得到 ``items: []`` 且
    ``has_next: false``，采集循环第一页就 break，任务却以"完成，新增 0 个"收尾。
    """
    adapter = _adapter()
    target = adapter.build_search_url(QUERY, 1)
    client = ScriptedReadyClient(
        readiness=[
            # 导航刚发起：旧文档（about:blank）还在，读不到卡片。
            {"url": "about:blank", "matched": 0, "ready_state": "loading", "explicitly_empty": False},
            {"url": "about:blank", "matched": 0, "ready_state": "loading", "explicitly_empty": False},
            # 新文档接管，但 SPA 还没渲染出卡片。
            {"url": target, "matched": 0, "ready_state": "loading", "explicitly_empty": False},
            {"url": target, "matched": 0, "ready_state": "interactive", "explicitly_empty": False},
            # 第 5 次才真正看到岗位卡片。
            {"url": target, "matched": 4, "ready_state": "complete", "explicitly_empty": False},
        ],
        collect_payload=json.dumps({"items": [REAL_ITEM], "has_next": False}),
    )

    page = adapter.collect_search(client, QUERY, page=1)

    # 关键断言：真的采到了（原实现这里是空）。
    assert [r.title for r in page.results] == ["后端开发工程师"]
    assert page.has_next is False
    # 导航后确实发生了**多次**探针调用——说明它在等，而不是一次就下结论。
    assert client.readiness_probes >= 5
    # 采集脚本只在就绪后跑一次。
    assert client.collect_calls == 1


def test_collect_waits_for_the_page_instead_of_reading_it_once():
    """反例对照：只探一次就下结论的实现会在这里得到空结果。"""
    adapter = _adapter()
    target = adapter.build_search_url(QUERY, 1)
    client = ScriptedReadyClient(
        readiness=[
            {"url": target, "matched": 0, "ready_state": "loading", "explicitly_empty": False},
            {"url": target, "matched": 2, "ready_state": "complete", "explicitly_empty": False},
        ],
        collect_payload=json.dumps({"items": [REAL_ITEM], "has_next": False}),
    )

    page = adapter.collect_search(client, QUERY, page=1)

    assert page.results and client.readiness_probes >= 2


def test_tiny_timeout_fails_instead_of_silently_returning_zero():
    """反证：把等待超时设得极小 → 必须**失败**，而不是静默返回"采到 0 个"。"""
    adapter = _adapter(timeout=0.0, poll=0.001)
    target = adapter.build_search_url(QUERY, 1)
    client = ScriptedReadyClient(
        readiness=[{"url": target, "matched": 0, "ready_state": "loading", "explicitly_empty": False}],
        collect_payload=json.dumps({"items": [], "has_next": False}),
    )

    with pytest.raises(SiteFailure) as excinfo:
        adapter.collect_search(client, QUERY, page=1)

    assert excinfo.value.category == FAILURE_SELECTOR_INVALID
    # 未就绪就绝不去跑采集脚本（拿不到就不装作拿到了）。
    assert client.collect_calls == 0


# ===== 第 2 节：攻击"0 结果"判定边界 =====


def test_loaded_but_empty_without_marker_is_a_failure_not_a_success():
    """页面已 complete、无内容、无"无结果"标志 → 必须失败（不得当成功）。"""
    adapter = _adapter()
    target = adapter.build_search_url(QUERY, 1)
    client = ScriptedReadyClient(
        readiness=[
            {"url": target, "matched": 0, "ready_state": "complete", "explicitly_empty": False}
        ],
        collect_payload=json.dumps({"items": [], "has_next": False}),
    )

    with pytest.raises(SiteFailure) as excinfo:
        adapter.collect_search(client, QUERY, page=1)

    assert excinfo.value.category == FAILURE_SELECTOR_INVALID
    assert client.collect_calls == 0


def test_genuinely_empty_search_is_a_legal_empty_page():
    """真的搜不到（页面明确呈现"无结果"）→ 合法返回空，不报错。"""
    adapter = _adapter()
    target = adapter.build_search_url(QUERY, 1)
    client = ScriptedReadyClient(
        readiness=[
            {"url": target, "matched": 0, "ready_state": "complete", "explicitly_empty": True}
        ]
    )

    page = adapter.collect_search(client, QUERY, page=1)

    assert page.results == []
    assert page.has_next is False


def test_empty_result_message_differs_from_failure_message():
    """合法空页与失败在**任务文案**上必须能区分（用户要能一眼看懂发生了什么）。"""
    from app.models.apply import ApplyTask
    from app.services.apply.task_runner import TaskRunner

    empty_msg = TaskRunner._collect_message(ApplyTask(kind="collect", succeeded=0))
    result_msg = TaskRunner._collect_message(ApplyTask(kind="collect", succeeded=7))

    assert "没有找到匹配的岗位" in empty_msg
    # 文案说的是"已暂存"而不是"已新增"：采集**不写岗位广场**，岗位要用户勾选后才导入。
    # 措辞必须与真实行为一致，否则用户会去岗位广场找一个还没被导入的岗位。
    assert "已暂存 7 个岗位" in result_msg
    assert "共新增" not in result_msg
    assert empty_msg != result_msg


def test_collect_message_tells_the_user_what_to_do_next():
    """用户反馈过"采集完只知道成功了，不知道下一步该做什么"——文案必须给出下一个动作。

    只说"已完成"等于把"接下来怎么办"留给用户猜；而这一步（勾选 → 导入）恰恰是整条链路里
    最需要人来做决定的地方。
    """
    from app.models.apply import ApplyTask
    from app.services.apply.task_runner import TaskRunner

    message = TaskRunner._collect_message(ApplyTask(kind="collect", succeeded=3))

    assert "本次采集结果" in message
    assert "导入" in message


def test_collect_message_reports_how_many_were_filtered_out():
    """筛掉了多少、因为什么，必须写进文案——否则用户只会觉得"怎么少了几个"。"""
    from app.models.apply import ApplyTask
    from app.services.apply.task_runner import TaskRunner

    task = ApplyTask(
        kind="collect", succeeded=4, config={"filtered_out": 2, "filter_reasons": ["学历"]}
    )
    message = TaskRunner._collect_message(task)

    assert "已暂存 4 个岗位" in message
    assert "另有 2 个不符合" in message


def test_collect_message_says_when_a_condition_was_not_understood():
    """用户填了读不懂的条件时必须明说"这次没生效"——这是本项目最忌讳的静默失效。"""
    from app.models.apply import ApplyTask
    from app.services.apply.task_runner import TaskRunner

    task = ApplyTask(kind="collect", succeeded=1, config={"filter_unapplied": ["学历"]})
    message = TaskRunner._collect_message(task)

    assert "没能识别" in message
    assert "学历" in message


def test_collect_message_distinguishes_all_filtered_from_nothing_found():
    """全被筛掉与"没搜到"是两回事：说成后者会让用户去改关键词，而问题出在筛选条件上。"""
    from app.models.apply import ApplyTask
    from app.services.apply.task_runner import TaskRunner

    message = TaskRunner._collect_message(
        ApplyTask(kind="collect", succeeded=0, skipped=0, config={"filtered_out": 5})
    )

    assert "不符合你填的筛选条件" in message
    assert "没有找到匹配的岗位" not in message


def test_login_wall_while_waiting_fails_immediately():
    """等待期间出现登录失效 → 立刻抛 login_required 类失败，绝不傻等满超时。"""
    import time

    # 超时给足 30 秒，用来证明它根本没等。
    adapter = BossAdapter(ready_wait=ReadyWait(timeout=30.0, poll_interval=0.5))
    target = adapter.build_search_url(QUERY, 1)
    client = ScriptedReadyClient(
        readiness=[
            {"url": target, "matched": 0, "ready_state": "complete",
             "explicitly_empty": False, "login_required": True, "title": "登录"}
        ]
    )

    started = time.monotonic()
    with pytest.raises(SiteFailure) as excinfo:
        adapter.collect_search(client, QUERY, page=1)
    elapsed = time.monotonic() - started

    assert excinfo.value.category == FAILURE_LOGIN_REQUIRED
    assert elapsed < 2.0, f"登录墙出现后仍等了 {elapsed:.2f}s，没有立刻失败"
    assert client.readiness_probes == 1


def test_login_wall_appearing_later_still_fails_as_soon_as_it_shows():
    """登录墙在第 3 次探针才出现时，也应在它出现的那一次立刻返回。"""
    adapter = _adapter(timeout=30.0, poll=0.001)
    target = adapter.build_search_url(QUERY, 1)
    client = ScriptedReadyClient(
        readiness=[
            {"url": target, "matched": 0, "ready_state": "loading", "explicitly_empty": False},
            {"url": target, "matched": 0, "ready_state": "loading", "explicitly_empty": False},
            {"url": target, "matched": 0, "ready_state": "complete",
             "explicitly_empty": False, "login_required": True},
        ]
    )

    with pytest.raises(SiteFailure) as excinfo:
        adapter.collect_search(client, QUERY, page=1)

    assert excinfo.value.category == FAILURE_LOGIN_REQUIRED
    assert client.readiness_probes == 3


def test_captcha_while_waiting_fails_immediately():
    adapter = _adapter(timeout=30.0, poll=0.001)
    target = adapter.build_search_url(QUERY, 1)
    client = ScriptedReadyClient(
        readiness=[
            {"url": target, "matched": 0, "ready_state": "complete",
             "explicitly_empty": False, "captcha": True}
        ]
    )

    with pytest.raises(SiteFailure) as excinfo:
        adapter.collect_search(client, QUERY, page=1)

    assert excinfo.value.category == FAILURE_CAPTCHA_REQUIRED
    assert client.readiness_probes == 1


def test_timeout_failure_carries_actionable_diagnostics():
    """超时时失败，且诊断里要带 URL / 标题 / 匹配控件数 / 期望控件描述。"""
    adapter = _adapter(timeout=0.0, poll=0.001)
    target = adapter.build_search_url(QUERY, 1)
    client = ScriptedReadyClient(
        readiness=[
            {"url": target, "title": "BOSS直聘-职位搜索", "matched": 0,
             "ready_state": "loading", "explicitly_empty": False}
        ]
    )

    with pytest.raises(SiteFailure) as excinfo:
        adapter.collect_search(client, QUERY, page=1)

    detail = excinfo.value.detail
    assert target in detail
    assert "BOSS直聘-职位搜索" in detail
    assert "匹配到的控件数：0" in detail
    assert "期望" in detail


def test_stale_first_page_document_is_not_mistaken_for_the_second_page():
    """分页：导航到第 2 页，但探针读到的是第 1 页的 DOM → 不得把上一页结果当成这一页。"""
    adapter = _adapter()
    page1 = adapter.build_search_url(QUERY, 1)
    page2 = adapter.build_search_url(QUERY, 2)
    client = ScriptedReadyClient(
        # 前两次仍是第 1 页（matched>0 且 complete）——若只看 matched 会误判为就绪。
        readiness=[
            {"url": page1, "matched": 8, "ready_state": "complete", "explicitly_empty": False},
            {"url": page1, "matched": 8, "ready_state": "complete", "explicitly_empty": False},
            {"url": page2, "matched": 3, "ready_state": "complete", "explicitly_empty": False},
        ],
        previous_url=page1,
        collect_payload=json.dumps({"items": [{"title": "第二页岗位"}], "has_next": False}),
    )

    page = adapter.collect_search(client, QUERY, page=2)

    assert [r.title for r in page.results] == ["第二页岗位"]
    # 旧文档被跳过，必须轮询到第 3 次才接受第 2 页。
    assert client.readiness_probes >= 3
    assert client.navigations == [page2]


def test_document_that_never_becomes_fresh_fails_instead_of_returning_old_results():
    """探针永远读到上一页：必须失败，绝不能把第 1 页的结果当成第 2 页返回。"""
    adapter = _adapter(timeout=0.05, poll=0.002)
    page1 = adapter.build_search_url(QUERY, 1)
    client = ScriptedReadyClient(
        readiness=[{"url": page1, "matched": 8, "ready_state": "complete", "explicitly_empty": False}],
        previous_url=page1,
        collect_payload=json.dumps({"items": [{"title": "第一页岗位"}], "has_next": False}),
    )

    with pytest.raises(SiteFailure) as excinfo:
        adapter.collect_search(client, QUERY, page=2)

    assert excinfo.value.category == FAILURE_SELECTOR_INVALID
    assert client.collect_calls == 0  # 没有把旧页内容当新页采回去


def test_a_different_redirected_search_is_not_accepted_just_because_url_changed():
    """首次导航也必须核对目标查询参数，不能把任意跳转后的搜索页当成本次筛选结果。"""
    adapter = _adapter(timeout=0.02, poll=0.001)
    target = adapter.build_search_url(QUERY, 1)
    wrong = target.replace("query=%E5%90%8E%E7%AB%AF", "query=Java")
    client = ScriptedReadyClient(
        readiness=[
            {"url": wrong, "matched": 6, "ready_state": "complete", "explicitly_empty": False}
        ],
        previous_url="about:blank",
        collect_payload=json.dumps({"items": [{"title": "错误筛选结果"}]}),
    )

    with pytest.raises(SiteFailure, match="页面没有切换到目标地址"):
        adapter.collect_search(client, QUERY, page=1)

    assert client.collect_calls == 0


def test_empty_keywords_and_city_do_not_crash():
    """空关键词 / 空城市：不炸、给出可理解的结果（能构造 URL 并正常走完流程）。"""
    adapter = _adapter()
    empty = CollectQuery(keywords=[], city="")
    target = adapter.build_search_url(empty, 1)
    assert target.startswith("https://www.zhipin.com/web/geek/job?")
    assert "query=" in target and "city=" in target

    client = ScriptedReadyClient(
        readiness=[{"url": target, "matched": 0, "ready_state": "complete", "explicitly_empty": True}]
    )
    page = adapter.collect_search(client, empty, page=1)

    assert page.results == []


def test_adapter_no_longer_opens_a_new_tab_for_collection():
    """导航改为复用同一标签页：采集路径不得调用 new_tab。"""
    adapter = _adapter()
    target = adapter.build_search_url(QUERY, 1)
    client = ScriptedReadyClient(
        readiness=[{"url": target, "matched": 1, "ready_state": "complete", "explicitly_empty": False}],
        collect_payload=json.dumps({"items": [REAL_ITEM], "has_next": False}),
    )

    adapter.collect_search(client, QUERY, page=1)

    # 采集只用了 navigate，没有 new_tab。
    assert client.navigations == [target]
    assert client.new_tab_calls == 0


def test_content_arriving_after_several_complete_polls_still_succeeds():
    """需求已更新：``readyState === 'complete'`` **不代表** SPA 该渲染的内容已经渲染完。

    页面在 ``complete`` 之后连续若干次探针仍读不到卡片、直到第 4 次才渲染出岗位——这时
    **必须成功**并真的采到那些岗位。旧实现把"complete 后约 0.8s 内没出卡片"当成"选择器失效"
    提前失败，真实站点首屏稍慢就会误失败（用户会从"采到 0 个"变成"采集失败"）。
    """
    adapter = _adapter(timeout=5.0, poll=0.002)
    target = adapter.build_search_url(QUERY, 1)
    client = ScriptedReadyClient(
        readiness=[
            {"url": target, "matched": 0, "ready_state": "complete", "explicitly_empty": False},
            {"url": target, "matched": 0, "ready_state": "complete", "explicitly_empty": False},
            {"url": target, "matched": 0, "ready_state": "complete", "explicitly_empty": False},
            # 第 4 次才由 complete 之后的异步渲染给出真实岗位卡片。
            {"url": target, "matched": 6, "ready_state": "complete", "explicitly_empty": False},
        ],
        collect_payload=json.dumps({"items": [REAL_ITEM], "has_next": False}),
    )

    page = adapter.collect_search(client, QUERY, page=1)

    # 关键：真的采到了那些延迟渲染出来的岗位（而不是"没抛异常就算过"）。
    assert [r.title for r in page.results] == ["后端开发工程师"]
    assert page.results[0].company == "示例科技"
    assert page.results[0].url == REAL_ITEM["url"]
    # 等到第 4 次（内容真正出现）才接受；前 3 次 complete 均未触发失败。
    assert client.readiness_probes >= 4
    assert client.collect_calls == 1


def test_content_never_arriving_until_timeout_fails_with_full_diagnostics():
    """内容直到超时都没出现 → 必须**失败**，且诊断四要素齐全。

    这是"提前失败"被移除后**唯一**的失败时限：超时。页面已 ``complete``、却始终没有卡片、
    也没有"无结果"标志，属于"页面已加载但找不到岗位卡片、结构可能已变化"，诊断里要有
    当前地址 / 页面标题 / 匹配到的控件数 / 期望控件。
    """
    adapter = _adapter(timeout=0.05, poll=0.002)
    target = adapter.build_search_url(QUERY, 1)
    client = ScriptedReadyClient(
        readiness=[
            {"url": target, "title": "BOSS直聘-职位搜索", "matched": 0,
             "ready_state": "complete", "explicitly_empty": False}
        ],
        collect_payload=json.dumps({"items": [], "has_next": False}),
    )

    with pytest.raises(SiteFailure) as excinfo:
        adapter.collect_search(client, QUERY, page=1)

    failure = excinfo.value
    detail = failure.detail
    assert failure.category == FAILURE_SELECTOR_INVALID
    assert target in detail
    assert "BOSS直聘-职位搜索" in detail
    assert "匹配到的控件数：0" in detail
    assert "期望" in detail
    # 未就绪就绝不去跑采集脚本（拿不到就不装作拿到了）。
    assert client.collect_calls == 0


def test_collection_that_finds_only_duplicates_completes_with_zero_new(db_session):
    """边界：整页岗位都已存在（全是重复）→ 采集 0 新增但任务**合法完成**。

    这属于"真的做了事、只是没有新增"，与"页面没加载"是两回事；文案必须把"都是重复"
    如实说清，不能误述成"没搜到"。
    """
    from app.models.job import Job
    from app.schemas.apply import CollectConfigIn
    from app.services.apply.collector import Collector
    from app.services.apply.task_runner import TaskRunner
    from app.services.sites.base import SearchPage, SearchResult

    db_session.add(
        Job(title="后端开发工程师", company="示例科技",
            source_url="https://www.zhipin.com/job_detail/1.html")
    )
    db_session.commit()

    class _DupAdapter(BossAdapter):
        def collect_search(self, client, query, page):  # type: ignore[override]
            return SearchPage(
                results=[
                    SearchResult(
                        title="后端开发工程师",
                        company="示例科技",
                        url="https://www.zhipin.com/job_detail/1.html",
                        source="BOSS直聘",
                    )
                ],
                page=page,
                has_next=False,
            )

    task = __import__("app.models.apply", fromlist=["ApplyTask"]).ApplyTask(
        kind="collect",
        status="running",
        total=20,
        config=CollectConfigIn(keywords=["后端"], per_task_limit=20).model_dump(),
    )
    db_session.add(task)
    db_session.commit()

    report = Collector().run(
        session=db_session,
        task=task,
        client=object(),
        adapter=_DupAdapter(),
        config=CollectConfigIn(keywords=["后端"], per_task_limit=20),
        checkpoint=lambda: None,
        sleeper=lambda _seconds: None,
        clock=_StepClock(100.0),
    )

    assert report.collected == 0
    assert report.skipped == 1
    # 文案必须把"全是重复"说清楚，不能误述成"没搜到"（本轮修复 B）。
    message = TaskRunner._collect_message(task)
    assert "都已存在" in message
    assert "跳过 1 个重复岗位" in message
    assert "没有找到匹配的岗位" not in message


# ===== 等待原语本身：不得有"大块阻塞" =====


class _StepClock:
    def __init__(self, step: float) -> None:
        self._t = 0.0
        self._step = step

    def __call__(self) -> float:
        value = self._t
        self._t += self._step
        return value


def test_wait_never_performs_a_long_blocking_sleep():
    """等待过程中每次睡眠都很短（≤ 轮询间隔），不会被一个长 sleep 把"停止"堵在外面。"""
    sleeps: list[float] = []

    with pytest.raises(TimeoutError):
        wait_for_page_state(
            lambda: {"matched": 0, "ready_state": "loading"},
            is_ready=lambda _state: False,
            on_timeout=lambda _state: TimeoutError("超时"),
            config=ReadyWait(timeout=1.0, poll_interval=0.4),
            sleeper=sleeps.append,
            clock=_StepClock(step=0.05),
        )

    assert sleeps, "应当至少睡过一次轮询间隔"
    assert max(sleeps) <= 0.4 + 1e-9, f"出现了大块阻塞：{max(sleeps)}s"
