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
from app.services.sites.base import CollectQuery, RiskProfile, SiteAdapter, SiteFailure
from app.services.sites.boss import (
    BOSS_DISPLAY_NAME,
    BOSS_KEY,
    BossAdapter,
    _SELECTORS,
    classify_submit_state,
    detect_blocker,
    parse_job_detail,
    parse_search_payload,
    same_target_page,
    selector_diagnostic,
)
from app.services.sites.boss_network import SEARCH_MARKER, search_has_more

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
        if isinstance(self.ready, dict) and not self.ready.get("url"):
            self.ready["url"] = url
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
    assert "city=101210100" in url
    assert url.endswith("page=3")


def test_salary_experience_education_are_locally_filtered_instead_of_unmapped():
    """薪资 / 经验 / 学历**不再报成"未生效"**：它们换成"采集后按接口字段本地筛选"。

    以前这三项一律标「未生效」，用户以为自己填的条件被丢掉了。现在它们真的会生效，
    只是生效的位置从"查询参数"换成了"采集后的本地筛选"（见 ``collect_filters``）。
    适配器要**声明**这件事，否则采集器不知道可以按接口字段筛。
    岗位类型同理：原始编码来自列表接口（``extra["job_type_code"]``）。
    """
    adapter = BossAdapter()
    query = CollectQuery(keywords=["后端"], salary_min=20, experience="3-5年", education="本科")

    # 不再有"未生效"的条件——真的没有条件被丢掉了。
    assert adapter.unmapped_conditions(query) == []
    assert adapter.unmapped_conditions(CollectQuery(keywords=["后端"], city="北京")) == []
    # 声明了这四项，采集器才会执行本地筛选。
    assert adapter.post_filter_conditions == ("薪资", "经验", "学历", "岗位类型")
    assert adapter.requires_resume is False


@pytest.mark.parametrize(
    ("job_type", "expected_param"),
    [
        ("实习", "jobType=1902"),
        ("社招", "jobType=1901"),
        # 校招在 BOSS 官方筛选里没有对应档（校招是独立专区）——不传参数，
        # 由采集后的本地筛选按接口编码判定。
        ("校招", None),
        ("", None),
    ],
)
def test_job_type_maps_to_official_site_param(job_type, expected_param):
    """实习/社招映射到站点官方 jobType 参数（真实实测的编码）；校招不映射。"""
    adapter = BossAdapter()
    url = adapter.build_search_url(CollectQuery(keywords=["后端"], city="北京", job_type=job_type), 1)
    assert "query=%E5%90%8E%E7%AB%AF" in url
    if expected_param is None:
        assert "jobType" not in url
    else:
        assert expected_param in url


def test_an_adapter_without_the_capability_still_reports_conditions_as_unmapped():
    """没声明本地筛选能力的站点，行为**不能**跟着变——它仍然要如实报「未生效」。

    这条守的是"别把 BOSS 的特例当成所有站点的默认"：能力由适配器声明，
    基类默认是"不支持"。
    """

    class _PlainAdapter(SiteAdapter):
        key = "plain"
        display_name = "示例站点"
        hosts = ("example.com",)

        def risk_profile(self) -> RiskProfile:  # pragma: no cover - 本用例不采集
            return RiskProfile(key=self.key)

        def collect_search(self, client, query, page):  # pragma: no cover
            raise AssertionError

        def open_apply(self, client, job):  # pragma: no cover
            raise AssertionError

        def fill_and_submit(self, client, data, greeting):  # pragma: no cover
            raise AssertionError

    assert _PlainAdapter.post_filter_conditions == ()
    assert _PlainAdapter.requires_resume is True


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
            "url": adapter.build_search_url(CollectQuery(keywords=["后端"]), 1),
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
            "url": adapter.build_search_url(CollectQuery(keywords=["后端"]), 1),
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
        {
            "rf:apply-entry": {
                "found": True,
                "matched": 1,
                "url": FAKE_JOB.source_url,
                "title": "t",
            }
        }
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
            "rf:entry-rect": {
                "found": True, "matched": 1, "label": "立即沟通",
                "x": 500, "y": 200, "width": 120, "height": 40,
                "url": "u", "title": "t",
            },
            "rf:chat-state": {
                "on_chat": True, "input_found": True, "found": True,
                "kind": "contenteditable", "url": "u", "title": "聊天",
            },
            "rf:fill-greeting": {"ok": True, "value": "您好，很感兴趣。"},
            "rf:send-rect": {
                "found": True, "disabled": False, "label": "发送",
                "x": 900, "y": 700, "width": 60, "height": 36,
                "url": "u", "title": "聊天",
            },
            "rf:submit-state": {"success": True, "url": "u", "title": "聊天"},
        }
    )

    outcome = adapter.fill_and_submit(client, {"name": "张三"}, greeting="您好，很感兴趣。")

    assert outcome.success is True
    assert outcome.greeting_sent == "您好，很感兴趣。"
    assert any("rf:fill-greeting" in expression for expression in client.expressions)
    # 现版链路用可信鼠标事件点击，不再发合成 click 探针。
    assert not any("rf:click-apply" in e or "rf:click-send" in e
                   for e in client.expressions)


def test_fill_and_submit_blocks_when_a_required_greeting_is_empty():
    adapter = BossAdapter()
    client = ScriptedCdpClient(
        {
            "rf:entry-rect": {
                "found": True, "matched": 1, "label": "立即沟通",
                "x": 500, "y": 200, "width": 120, "height": 40,
                "url": "u", "title": "t",
            },
        }
    )

    with pytest.raises(SiteFailure) as excinfo:
        adapter.fill_and_submit(client, {}, greeting="")

    assert excinfo.value.category == FAILURE_GREETING_MISSING


def test_fill_and_submit_propagates_a_captcha_at_submit():
    adapter = BossAdapter()
    client = ScriptedCdpClient(
        {
            "rf:entry-rect": {
                "found": True, "matched": 1, "label": "立即沟通",
                "x": 500, "y": 200, "width": 120, "height": 40,
                "url": "u", "title": "t",
            },
            "rf:chat-state": {
                "on_chat": True, "input_found": True, "found": True,
                "kind": "contenteditable", "url": "u", "title": "聊天",
            },
            "rf:fill-greeting": {"ok": True, "value": "您好"},
            "rf:send-rect": {
                "found": True, "disabled": False, "label": "发送",
                "x": 900, "y": 700, "width": 60, "height": 36,
                "url": "u", "title": "聊天",
            },
            "rf:submit-state": {"captcha": True, "url": "u", "title": "t"},
        }
    )

    with pytest.raises(SiteFailure) as excinfo:
        adapter.fill_and_submit(client, {}, greeting="您好")

    assert excinfo.value.category == FAILURE_CAPTCHA_REQUIRED


# ===== 采集抗改版（网络优先 / 地址规范化 / 选择器降级）=====
#
# 这一组对应一次真实故障：投递台报"页面没有切换到目标地址；匹配到的控件数: 0"，
# 而用户截图里 BOSS 的岗位列表**渲染得好好的**。两个独立的 bug 叠在一起：
#   1. 新鲜度判据是"地址与拼出来的目标**整串相等**"，站点把 /job 规范化成 /jobs 之后，
#      每次正常导航都被误判成"没切换"；
#   2. 卡片选择器还是旧的 `job-card-wrapper`（新页面是 `li.job-card-box`），
#      于是 matched 恒为 0 —— 而"匹配 0 个"以前会一路走到超时失败，
#      哪怕网络层手里已经有完整的岗位列表。


def test_same_target_page_accepts_normalised_urls_but_rejects_other_pages():
    """新鲜度判据：容忍站点的查询串规范化，但绝不把"还停在上一页"当成"已到位"。"""
    target = "https://www.zhipin.com/web/geek/job?query=%E5%90%8E%E7%AB%AF&city=&page=2"

    # 路径被规范化（/job → /jobs）、参数顺序不同 —— 都还算"就是目标那一页"。
    assert same_target_page("https://www.zhipin.com/web/geek/jobs?query=%E5%90%8E%E7%AB%AF&city=&page=2", target)
    assert same_target_page("https://www.zhipin.com/web/geek/job?page=2&city=&query=%E5%90%8E%E7%AB%AF", target)
    # 停在上一页 / 关键词不同 / 还没到搜索页 —— 都不算。
    assert not same_target_page("https://www.zhipin.com/web/geek/job?query=%E5%90%8E%E7%AB%AF&city=&page=1", target)
    assert not same_target_page("https://www.zhipin.com/web/geek/job?query=JAVA&city=&page=2", target)
    assert not same_target_page("https://www.zhipin.com/", target)


def test_a_redirected_search_url_still_counts_as_the_target_page():
    """站点把搜索地址规范化成 /jobs 之后，采集仍应正常完成而不是超时报"没切换地址"。"""
    adapter = boss()
    request = CollectQuery(keywords=["后端"])
    target = adapter.build_search_url(request, 1)
    normalized = target.replace("/web/geek/job?", "/web/geek/jobs?")
    assert normalized != target  # 确认这条用例真的在测"地址对不上"

    client = ScriptedCdpClient(
        {"rf:collect */": json.dumps({"items": [{"title": "后端开发"}], "has_next": False})},
        ready={
            "url": normalized,
            "matched": 5,
            "explicitly_empty": False,
            "ready_state": "complete",
        },
    )

    page = adapter.collect_search(client, request, page=1)

    assert [result.title for result in page.results] == ["后端开发"]


class NetworkCaptureClient(ScriptedCdpClient):
    """支持事件订阅的假客户端：把预置的接口响应交给采集器。

    真实链路上岗位列表来自 CDP 网络事件（``Network.responseReceived`` +
    ``Network.getResponseBody``）。这里把"接口返回了一份岗位列表"直接摆进去，
    用来验证"DOM 选择器失效也不影响采集"。
    """

    def __init__(self, responses=None, *, ready=None, events=None, bodies=None):
        super().__init__(responses, ready=ready)
        self.events = list(events or [])
        self.bodies = dict(bodies or {})
        self.capturing = False

    def start_event_capture(self, events):
        self.capturing = True

    def drain_events(self):
        return list(self.events) if self.capturing else []

    def stop_event_capture(self):
        self.capturing = False

    def send(self, method, params=None, *, timeout=None):
        if method == "Network.getResponseBody":
            return self.bodies.get(str((params or {}).get("requestId")), {})
        return {}


def test_network_capture_rescues_collection_when_the_dom_selector_is_stale():
    """DOM 卡片选择器过期（matched 恒为 0）不该让采集失败：接口已经返回了岗位列表。"""
    adapter = boss()
    payload = {
        "zpData": {
            "hasMore": True,
            "jobList": [
                {
                    "encryptJobId": "abc",
                    "jobName": "后端开发",
                    "brandName": "某某科技",
                    "cityName": "天津",
                    "lowSalary": 15000,
                    "highSalary": 25000,
                    "salaryMonth": 12,
                }
            ],
        }
    }
    client = NetworkCaptureClient(
        ready={
            "url": "https://www.zhipin.com/web/geek/jobs?query=%E5%90%8E%E7%AB%AF&city=&page=1",
            "matched": 0,  # 卡片 class 已改名 —— 选择器一个都匹配不到
            "explicitly_empty": False,
            "ready_state": "complete",
        },
        events=[
            {
                "method": "Network.responseReceived",
                "params": {
                    "requestId": "r1",
                    "response": {"url": f"https://www.zhipin.com{SEARCH_MARKER}?page=1"},
                },
            }
        ],
        bodies={"r1": {"body": json.dumps(payload), "base64Encoded": False}},
    )

    page = adapter.collect_search(client, CollectQuery(keywords=["后端"]), page=1)

    assert [result.title for result in page.results] == ["后端开发"]
    assert page.results[0].company == "某某科技"
    # 12 薪是常态，不缀"·12薪"；只有 13 薪及以上才显示（见 format_salary 的口径）。
    assert page.results[0].salary == "15-25K"
    # 翻页标志来自接口（页面探针根本不报 has_next），否则永远停在第 1 页。
    assert page.has_next is True


def test_falls_back_to_job_links_when_the_card_selector_misses():
    """卡片结构没匹配到、但岗位链接在 → 用链接兜底出结果，而不是报"什么都没抓到"。"""
    adapter = boss()
    client = ScriptedCdpClient(
        {
            "rf:collect-links": json.dumps(
                {
                    "items": [
                        {"title": "前端开发", "url": "https://www.zhipin.com/job_detail/x.html"}
                    ],
                    "has_next": False,
                }
            ),
            "rf:collect */": json.dumps({"items": [], "has_next": False}),
        },
        ready={
            "url": adapter.build_search_url(CollectQuery(keywords=["前端"]), 1).replace(
                "/web/geek/job?", "/web/geek/jobs?"
            ),
            "matched": 3,
            "explicitly_empty": False,
            "ready_state": "complete",
        },
    )

    page = adapter.collect_search(client, CollectQuery(keywords=["前端"]), page=1)

    assert [result.title for result in page.results] == ["前端开发"]


def test_reports_a_diagnostic_instead_of_a_silent_zero_when_nothing_is_found():
    """三条路都没拿到岗位时必须**报错并带诊断**，绝不静默返回 0 条。

    静默的 0 是最坏的结果：用户会以为"关键词没搜到"，而实际是工具坏了，于是永远
    不会把诊断反馈回来，选择器也就永远收敛不了。
    """
    adapter = boss()
    client = ScriptedCdpClient(
        {
            "rf:collect-links": json.dumps({"items": [], "has_next": False}),
            "rf:collect */": json.dumps(
                {
                    "items": [],
                    "has_next": False,
                    "url": "https://www.zhipin.com/web/geek/jobs?page=1",
                    "title": "BOSS直聘",
                }
            ),
        },
        ready={
            "url": adapter.build_search_url(CollectQuery(keywords=["前端"]), 1).replace(
                "/web/geek/job?", "/web/geek/jobs?"
            ),
            "matched": 3,  # 页面等待认为"有内容"，但两套 DOM 脚本都取不到
            "explicitly_empty": False,
            "ready_state": "complete",
        },
    )

    with pytest.raises(SiteFailure) as excinfo:
        adapter.collect_search(client, CollectQuery(keywords=["前端"]), page=1)

    detail = excinfo.value.detail
    assert "岗位卡片" in detail
    assert "匹配到的控件数：0" in detail


def test_search_has_more_returns_none_when_the_flag_is_absent():
    """接口没给翻页标志时返回 None（由调用方决定退路），不要瞎猜一个 False。"""
    assert search_has_more({"zpData": {"hasMore": True}}) is True
    assert search_has_more({"zpData": {"hasMore": False}}) is False
    assert search_has_more({"zpData": {"jobList": []}}) is None
    assert search_has_more(None) is None


# ===== 反爬混淆的还原（用户实测：职位名 "-K"、薪资为空）=====


def test_dom_collection_restores_the_obfuscated_title_and_hands_back_the_salary():
    """真实故障形态：新版列表把岗位名与薪资放在**同一个节点**里，数字还被字体反爬吃掉。

    用户在界面上看到的是职位名 "全栈工程师-K"（数字变成方框）而薪资列为空。
    这两件事是同一个根因的两面：文本没还原 + 没把粘连的薪资拆出来。
    """
    payload = {
        "items": [
            {
                "title": "全栈工程师\ue032\ue033-\ue032\ue036K",
                "company": "天津云际",
                "location": "天津·西青区·侯台",
                "salary": "",  # 新版列表没有独立的薪资节点，取到空
                "url": "https://www.zhipin.com/job_detail/x.html",
            }
        ],
        "has_next": False,
    }

    page = parse_search_payload(payload, 1)

    assert page.results[0].title == "全栈工程师"
    assert page.results[0].salary == "23-26K"


def test_dom_collection_rejects_a_salary_node_that_is_not_a_salary():
    """薪资选择器放宽之后可能取到一个同时含岗位名的容器，不能把它当薪资写进库。"""
    payload = {
        "items": [
            {
                "title": "全栈工程师23-26K",
                "salary": "全栈工程师23-26K",  # 取错了节点
                "url": "https://x/job_detail/1.html",
            }
        ],
        "has_next": False,
    }

    page = parse_search_payload(payload, 1)

    assert page.results[0].title == "全栈工程师"
    assert page.results[0].salary == "23-26K"


def test_dom_detail_splits_description_and_requirements():
    """用户实测："有的全部被塞进职位描述里面了"——按小标题切出来。"""
    payload = {
        "job_title": "全栈工程师",
        "company": "某某科技",
        "description": (
            "岗位职责：负责前后端开发与系统设计，参与需求评审并把方案落地。"
            "岗位要求：1、三年以上全栈经验。2、熟悉 Python。"
        ),
        "requirements": "",
    }

    detail = parse_job_detail(payload)

    assert detail["description"].startswith("岗位职责")
    assert "岗位要求" not in detail["description"]
    assert detail["requirements"].startswith("岗位要求")


def test_dom_detail_keeps_a_dedicated_requirements_container_when_present():
    payload = {
        "description": "岗位职责：负责前后端开发与系统设计，参与需求评审并把方案落地。",
        "requirements": "任职要求：1、精通 Python。",
    }

    detail = parse_job_detail(payload)

    assert detail["requirements"] == "任职要求：1、精通 Python。"


def test_dom_detail_cleans_watermarks_from_the_job_description():
    """真实 JD 里被塞了 ``boss`` / ``kanzhun`` / ``直聘`` 三种水印，不清会一路进到匹配分析。"""
    payload = {
        "description": "教育背景：本boss科在校生；熟练使kanzhun用Golang；工kanzhun作周期：长直聘期兼职。",
    }

    detail = parse_job_detail(payload)

    assert "boss" not in detail["description"]
    assert "kanzhun" not in detail["description"]
    assert "本科在校生" in detail["description"]
    assert "熟练使用Golang" in detail["description"]
    assert "工作周期：长期兼职" in detail["description"]
