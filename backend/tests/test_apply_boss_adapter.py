"""BOSS 直聘适配器离线测试：喂静态页面快照，断言采集解析、投递结果判定与失败分类。

真实 DOM 无法联调，所以适配器把"解析与判定"抽成了纯函数，这里直接喂快照验证它们；
选择器失效时必须给出可操作诊断（含当前 URL / 标题 / 匹配控件数 / 期望）。
"""
import json

import pytest

from app.models.apply import (
    FAILURE_CAPTCHA_REQUIRED,
    FAILURE_GREETING_MISSING,
    FAILURE_LOGIN_REQUIRED,
    FAILURE_SELECTOR_INVALID,
)
from app.services.browser.cdp_client import CdpClient
from app.services.browser.page_ready import ReadyWait
from app.services.apply.task_runner import TaskStopped
from app.services.sites.base import CollectQuery, SiteFailure
from app.services.sites.boss import (
    BOSS_DISPLAY_NAME,
    BOSS_KEY,
    BossAdapter,
    _SELECTORS,
    classify_submit_state,
    detect_blocker,
    parse_job_detail,
    parse_search_payload,
    selector_diagnostic,
)

FAKE_JOB = type("FakeJob", (), {"source_url": "https://www.zhipin.com/job_detail/abc.html"})()

# 等待参数：离线测试用极短超时/间隔，避免用例真的等满默认的十几秒。
FAST_WAIT = ReadyWait(timeout=0.05, poll_interval=0.001)
# 就绪探针的默认响应（页面已加载、匹配到 1 个目标控件）。
READY_STATE = {"matched": 1, "explicitly_empty": False, "ready_state": "complete"}


def boss() -> BossAdapter:
    return BossAdapter(ready_wait=FAST_WAIT)


class ScriptedCdpClient(CdpClient):
    """按表达式里的标记返回脚本化结果的假 CDP 客户端。

    复用同一标签页导航（``navigate``），因此这里同时记录 ``navigations``；``rf:readiness``
    探针默认返回"已就绪"，各用例可用 ``ready`` 覆盖成"未就绪 / 无结果 / 已定型不可用"。
    """

    def __init__(self, responses=None, *, ready=None):
        self.responses = responses or {}
        self.ready = dict(READY_STATE) if ready is None else ready
        self.expressions: list[str] = []
        self.navigations: list[str] = []
        # 兼容旧断言：new_tab 仍记录，但采集/投递路径已改为 navigate 复用标签页。
        self.tabs: list[str] = []

    def list_targets(self):
        return []

    def new_tab(self, url: str = "about:blank") -> str:
        self.tabs.append(url)
        return "TAB"

    def navigate(self, url: str, *, timeout=None):
        self.navigations.append(url)
        return {}

    def send(self, method, params=None, *, timeout=None):
        return {}

    def evaluate(self, expression, *, timeout=None):
        self.expressions.append(expression)
        if "rf:readiness" in expression:
            return self.ready
        for marker, value in self.responses.items():
            if marker in expression:
                return value
        return None

    def close(self):
        pass


def test_matches_only_boss_targets():
    adapter = BossAdapter()

    assert adapter.matches("BOSS直聘") is True
    assert adapter.matches("https://www.zhipin.com/web/geek/job") is True
    assert adapter.matches("手动添加") is False
    assert adapter.matches("https://www.lagou.com") is False


def test_risk_profile_is_conservative():
    profile = BossAdapter().risk_profile()

    assert profile.key == BOSS_KEY
    assert profile.min_interval_seconds >= 20
    assert profile.max_per_hour <= 100
    assert profile.needs_login is True


def test_every_selector_is_a_non_empty_string():
    assert _SELECTORS
    for name, selector in _SELECTORS.items():
        assert isinstance(selector, str) and selector, name


def test_build_search_url_maps_keyword_city_and_page():
    adapter = BossAdapter()

    url = adapter.build_search_url(
        CollectQuery(keywords=["后端开发"], city="杭州"), page=3
    )

    assert "query=%E5%90%8E%E7%AB%AF%E5%BC%80%E5%8F%91" in url
    assert "city=%E6%9D%AD%E5%B7%9E" in url
    assert url.endswith("page=3")


def test_unmapped_conditions_flags_salary_experience_education():
    adapter = BossAdapter()

    assert adapter.unmapped_conditions(CollectQuery(keywords=["后端"], city="北京")) == []
    assert adapter.unmapped_conditions(
        CollectQuery(keywords=["后端"], salary_min=20, experience="3-5年", education="本科")
    ) == ["薪资", "经验", "学历"]


def test_parse_search_payload_builds_results():
    payload = {
        "items": [
            {"title": "后端开发", "company": "示例科技", "salary": "20-30K", "location": "北京",
             "url": "https://www.zhipin.com/job_detail/1.html"},
            "not a dict",
        ],
        "has_next": True,
    }

    page = parse_search_payload(payload, page=2, unmapped_conditions=["薪资"])

    assert page.page == 2
    assert page.has_next is True
    assert page.unmapped_conditions == ["薪资"]
    assert len(page.results) == 1
    assert page.results[0].title == "后端开发"
    assert page.results[0].source == BOSS_DISPLAY_NAME


def test_parse_search_payload_rejects_a_broken_payload():
    with pytest.raises(SiteFailure) as excinfo:
        parse_search_payload("nope", page=1)
    assert excinfo.value.category == FAILURE_SELECTOR_INVALID


def test_parse_job_detail_reads_the_expected_fields():
    detail = parse_job_detail(
        {"job_title": "后端开发", "company": "示例科技", "description": "职责", "requirements": "要求"}
    )

    assert detail["job_title"] == "后端开发"
    assert detail["requirements"] == "要求"


def test_detect_blocker_prefers_captcha_over_login():
    assert detect_blocker({"captcha": True, "login_required": True}) == "captcha"
    assert detect_blocker({"login_required": True}) == "login"
    assert detect_blocker({}) is None


def test_classify_submit_state_returns_success():
    outcome = classify_submit_state({"success": True}, greeting="您好")

    assert outcome.success is True
    assert outcome.greeting_sent == "您好"


def test_classify_submit_state_maps_captcha_and_login():
    with pytest.raises(SiteFailure) as captcha:
        classify_submit_state({"captcha": True, "url": "u", "title": "t"})
    assert captcha.value.category == FAILURE_CAPTCHA_REQUIRED

    with pytest.raises(SiteFailure) as login:
        classify_submit_state({"login_required": True, "url": "u", "title": "t"})
    assert login.value.category == FAILURE_LOGIN_REQUIRED


def test_classify_submit_state_without_a_marker_is_a_selector_failure_with_diagnostics():
    with pytest.raises(SiteFailure) as excinfo:
        classify_submit_state({"url": "https://x/job", "title": "岗位详情", "matched": 0})

    failure = excinfo.value
    assert failure.category == FAILURE_SELECTOR_INVALID
    assert "https://x/job" in failure.detail
    assert "岗位详情" in failure.detail
    assert "匹配到的控件数：0" in failure.detail
    assert "期望" in failure.detail


def test_selector_diagnostic_includes_actionable_hints():
    text = selector_diagnostic(
        {"url": "https://x/job", "title": "详情", "matched": 3}, "「立即沟通 / 投递」入口"
    )

    assert "https://x/job" in text
    assert "详情" in text
    assert "匹配到的控件数：3" in text
    assert "反馈给维护者" in text


def test_collect_search_reuses_the_tab_and_parses_the_page():
    adapter = boss()
    client = ScriptedCdpClient(
        {"rf:collect": json.dumps({"items": [{"title": "后端开发"}], "has_next": False})}
    )

    page = adapter.collect_search(client, CollectQuery(keywords=["后端"], city="北京"), page=1)

    # 复用当前标签页导航（navigate），而不是每页 new_tab。
    assert client.navigations and client.navigations[0].startswith(
        "https://www.zhipin.com/web/geek/job"
    )
    assert client.tabs == []
    assert [result.title for result in page.results] == ["后端开发"]
    # 先探针（等待就绪），再采集。
    assert any("rf:readiness" in expression for expression in client.expressions)
    assert any("rf:collect" in expression for expression in client.expressions)


def test_collect_search_stops_on_a_captcha():
    adapter = boss()
    client = ScriptedCdpClient({"rf:collect": json.dumps({"captcha": True, "items": []})})

    with pytest.raises(SiteFailure) as excinfo:
        adapter.collect_search(client, CollectQuery(keywords=["后端"]), page=1)

    assert excinfo.value.category == FAILURE_CAPTCHA_REQUIRED


def test_collect_search_fails_when_the_page_is_loaded_but_has_no_cards():
    """页面已加载完成、却既没有卡片也没有"无结果"标志 → **必须失败**，不能静默当成采到 0 个。"""
    adapter = boss()
    client = ScriptedCdpClient(
        ready={"matched": 0, "explicitly_empty": False, "ready_state": "complete"}
    )

    with pytest.raises(SiteFailure) as excinfo:
        adapter.collect_search(client, CollectQuery(keywords=["后端"]), page=1)

    assert excinfo.value.category == FAILURE_SELECTOR_INVALID
    assert "期望" in excinfo.value.detail
    # 失败时**不应**再执行采集脚本（拿不到就别装作拿到了）。
    assert not any("rf:collect" in expression for expression in client.expressions)


def test_timeout_message_when_document_never_finishes_loading():
    """从未到达 complete（``ready_state`` 非 complete / 空）→ 文案是"页面加载超时…请稍后重试"。

    这是"网络慢/被拦截"该看到的提示，**不能**误报成"页面结构可能已变化"。
    """
    adapter = boss()
    client = ScriptedCdpClient(
        ready={
            "url": "https://www.zhipin.com/web/geek/job?x",
            "title": "搜索中",
            "matched": 0,
            "explicitly_empty": False,
            "ready_state": "loading",
        }
    )

    with pytest.raises(SiteFailure) as excinfo:
        adapter.collect_search(client, CollectQuery(keywords=["后端"]), page=1)

    detail = excinfo.value.detail
    assert "页面加载超时" in detail
    assert "页面结构可能已变化" not in detail
    assert "期望" in detail  # 诊断仍然齐备


def test_timeout_message_when_page_is_loaded_but_has_no_cards():
    """已 complete、且是新文档、却无卡片也无"无结果" → 文案是"页面已加载但找不到岗位卡片…"。"""
    adapter = boss()
    client = ScriptedCdpClient(
        ready={
            "url": "https://www.zhipin.com/web/geek/job?x",
            "title": "职位搜索",
            "matched": 0,
            "explicitly_empty": False,
            "ready_state": "complete",
        }
    )

    with pytest.raises(SiteFailure) as excinfo:
        adapter.collect_search(client, CollectQuery(keywords=["后端"]), page=1)

    detail = excinfo.value.detail
    assert "页面已加载但找不到岗位卡片" in detail
    assert "页面结构可能已变化" in detail
    assert "匹配到的控件数：0" in detail


def test_collect_search_returns_an_empty_page_when_there_are_genuinely_no_results():
    """关键词真的搜不到：页面明确呈现"无结果"，返回空页是合法的（不报错）。"""
    adapter = boss()
    client = ScriptedCdpClient(
        ready={"matched": 0, "explicitly_empty": True, "ready_state": "complete"}
    )

    page = adapter.collect_search(client, CollectQuery(keywords=["不存在的关键词"]), page=1)

    assert page.results == []
    assert page.has_next is False


def test_collect_search_fails_immediately_when_a_login_wall_is_shown_while_waiting():
    """等待期间出现登录墙 → **立刻**抛对应失败，不傻等满超时。"""
    adapter = boss()
    client = ScriptedCdpClient(
        ready={"matched": 0, "explicitly_empty": False, "login_required": True, "url": "u", "title": "t"}
    )

    with pytest.raises(SiteFailure) as excinfo:
        adapter.collect_search(client, CollectQuery(keywords=["后端"]), page=1)

    assert excinfo.value.category == FAILURE_LOGIN_REQUIRED


def test_wait_can_be_interrupted_by_the_stop_signal():
    """等待是可被"停止"打断的：停止信号在下一次 CDP 调用（探针）前抛出。"""
    adapter = boss()
    client = ScriptedCdpClient(
        ready={"matched": 0, "explicitly_empty": False, "ready_state": "loading"}
    )
    original = client.evaluate
    calls = {"n": 0}

    def stop_on_second_call(expression, *, timeout=None):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise TaskStopped()
        return original(expression, timeout=timeout)

    client.evaluate = stop_on_second_call  # type: ignore[assignment]

    with pytest.raises(TaskStopped):
        adapter.collect_search(client, CollectQuery(keywords=["后端"]), page=1)


class StaleDocumentClient(ScriptedCdpClient):
    """模拟"导航已发起、但旧文档仍短暂存活"：先返回旧页地址，再切到新页。"""

    def __init__(self, states, *, previous_url, responses=None):
        super().__init__(responses)
        self._states = list(states)
        self._index = 0
        self._previous_url = previous_url
        self.readiness_polls = 0

    def evaluate(self, expression, *, timeout=None):
        if "rf:url" in expression:
            return {"url": self._previous_url}
        if "rf:readiness" in expression:
            self.readiness_polls += 1
            state = self._states[min(self._index, len(self._states) - 1)]
            self._index += 1
            return state
        return super().evaluate(expression, timeout=timeout)


def test_collect_search_waits_until_the_new_document_takes_over():
    """导航刚发起时旧文档还在：地址没变成新页就**不能**认这次读取，否则会读到上一页。"""
    adapter = boss()
    old = "https://www.zhipin.com/web/geek/job?query=%E5%90%8E%E7%AB%AF&city=&page=1"
    new = "https://www.zhipin.com/web/geek/job?query=%E5%90%8E%E7%AB%AF&city=&page=2"
    client = StaleDocumentClient(
        [
            {"url": old, "matched": 5, "ready_state": "complete"},  # 旧文档，仍在 page=1
            {"url": old, "matched": 5, "ready_state": "complete"},  # 仍是旧文档
            {"url": new, "matched": 5, "ready_state": "complete"},  # 新文档已接管
        ],
        previous_url=old,
        responses={"rf:collect": json.dumps({"items": [{"title": "第二页岗位"}], "has_next": False})},
    )

    page = adapter.collect_search(client, CollectQuery(keywords=["后端"]), page=2)

    assert [result.title for result in page.results] == ["第二页岗位"]
    # 旧文档被跳过，至少要轮询到第三次才接受。
    assert client.readiness_polls >= 3


def test_timeout_message_when_the_document_never_switches_to_the_target():
    """始终是陈旧文档（地址没切到目标页）→ 文案是"页面没有切换到目标地址"。"""
    adapter = boss()
    old = "https://www.zhipin.com/web/geek/job?query=x&city=&page=1"
    client = StaleDocumentClient(
        [{"url": old, "title": "旧页", "matched": 8, "ready_state": "complete"}],
        previous_url=old,
    )

    with pytest.raises(SiteFailure) as excinfo:
        adapter.collect_search(client, CollectQuery(keywords=["后端"]), page=1)

    detail = excinfo.value.detail
    assert "页面没有切换到目标地址" in detail
    assert old in detail  # 诊断里的"当前地址"就是那份陈旧文档


def test_fetch_job_detail_waits_for_the_page_then_parses():
    adapter = boss()
    client = ScriptedCdpClient(
        {"rf:detail": json.dumps({"job_title": "后端开发", "description": "职责正文"})}
    )

    detail = adapter.fetch_job_detail(client, "https://www.zhipin.com/job_detail/xyz")

    assert client.navigations == ["https://www.zhipin.com/job_detail/xyz"]
    assert detail["job_title"] == "后端开发"
    assert detail["description"] == "职责正文"


def test_fetch_job_detail_fails_when_the_page_never_becomes_ready():
    adapter = boss()
    client = ScriptedCdpClient(
        ready={"matched": 0, "explicitly_empty": False, "ready_state": "complete"}
    )

    with pytest.raises(SiteFailure) as excinfo:
        adapter.fetch_job_detail(client, "https://www.zhipin.com/job_detail/xyz")

    assert excinfo.value.category == FAILURE_SELECTOR_INVALID


def test_open_apply_requires_a_source_url():
    adapter = boss()
    client = ScriptedCdpClient({"rf:apply-entry": {"found": True}})
    job = type("Job", (), {"source_url": ""})()

    with pytest.raises(SiteFailure) as excinfo:
        adapter.open_apply(client, job)

    assert excinfo.value.category == FAILURE_SELECTOR_INVALID


def test_open_apply_reuses_the_tab_and_confirms_the_entry_is_present():
    adapter = boss()
    client = ScriptedCdpClient(
        {"rf:apply-entry": {"found": True, "matched": 1, "url": "u", "title": "t"}}
    )

    adapter.open_apply(client, FAKE_JOB)

    assert client.navigations == [FAKE_JOB.source_url]
    assert client.tabs == []


def test_open_apply_reports_a_missing_entry_with_diagnostics():
    adapter = boss()
    client = ScriptedCdpClient(
        {"rf:apply-entry": {"found": False, "matched": 0, "url": "https://x/job", "title": "详情"}}
    )

    with pytest.raises(SiteFailure) as excinfo:
        adapter.open_apply(client, FAKE_JOB)

    assert excinfo.value.category == FAILURE_SELECTOR_INVALID
    assert "https://x/job" in excinfo.value.detail


def test_fill_and_submit_success_sends_the_greeting():
    adapter = BossAdapter()
    client = ScriptedCdpClient(
        {
            "rf:apply-entry": {"found": True, "matched": 1, "url": "u", "title": "t"},
            "rf:form-controls": json.dumps({"controls": []}),
            "rf:greeting-state": {"found": True, "required": True, "url": "u", "title": "t"},
            "rf:submit-state": {"success": True, "url": "u", "title": "t"},
        }
    )

    outcome = adapter.fill_and_submit(client, {"name": "张三"}, greeting="您好，很感兴趣。")

    assert outcome.success is True
    assert outcome.greeting_sent == "您好，很感兴趣。"
    assert any("rf:fill-greeting" in expression for expression in client.expressions)


def test_fill_and_submit_blocks_when_a_required_greeting_is_empty():
    adapter = BossAdapter()
    client = ScriptedCdpClient(
        {
            "rf:apply-entry": {"found": True, "matched": 1, "url": "u", "title": "t"},
            "rf:form-controls": json.dumps({"controls": []}),
            "rf:greeting-state": {"found": True, "required": True, "url": "u", "title": "t"},
        }
    )

    with pytest.raises(SiteFailure) as excinfo:
        adapter.fill_and_submit(client, {}, greeting="")

    assert excinfo.value.category == FAILURE_GREETING_MISSING


def test_fill_and_submit_propagates_a_captcha_at_submit():
    adapter = BossAdapter()
    client = ScriptedCdpClient(
        {
            "rf:apply-entry": {"found": True, "matched": 1, "url": "u", "title": "t"},
            "rf:form-controls": json.dumps({"controls": []}),
            "rf:greeting-state": {"found": True, "required": False, "url": "u", "title": "t"},
            "rf:submit-state": {"captcha": True, "url": "u", "title": "t"},
        }
    )

    with pytest.raises(SiteFailure) as excinfo:
        adapter.fill_and_submit(client, {}, greeting="您好")

    assert excinfo.value.category == FAILURE_CAPTCHA_REQUIRED
