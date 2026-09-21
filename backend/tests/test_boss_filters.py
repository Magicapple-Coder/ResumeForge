"""BOSS 站点侧筛选项：清单读取、来源降级、编码校验与 URL 拼接。

**每个用例都不联网**：要么注入假的 fetcher，要么走内置快照。真实站点行为由
``tests/test_boss_filters_live.py`` 之外的实测记录保证（见模块文档里的实测注释）。
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from app.services.browser.browser_manager import BrowserError
from app.services.sites.base import (
    SOURCE_PUBLIC,
    SOURCE_SESSION,
    SOURCE_SNAPSHOT,
    SOURCE_UNAVAILABLE,
    CollectQuery,
    FilterResolution,
)
from app.services.sites.boss import BossAdapter
from app.services.sites.boss_search import CONDITIONS_FETCH_WAIT_SECONDS
from app.services.sites.boss_filters import (
    CONDITIONS_ENDPOINT,
    INDUSTRY_ENDPOINT,
    UNLIMITED_CODE,
    build_catalogue,
    fetch_catalogue,
    parse_conditions,
    parse_filter_bar,
    parse_industries,
    resolve_codes,
    snapshot_catalogue,
)


def conditions_payload(job_types: list[dict] | None = None) -> dict:
    """一份与真实 ``conditions.json`` 同形的响应（编码是数字，含 0）。"""
    return {
        "code": 0,
        "message": "Success",
        "zpData": {
            "jobTypeList": job_types
            if job_types is not None
            else [
                {"code": 0, "name": "不限"},
                {"code": 1901, "name": "全职"},
                {"code": 1903, "name": "兼职"},
            ],
            "salaryList": [
                {"code": 0, "name": "不限", "lowSalary": 0, "highSalary": 0},
                {"code": 405, "name": "10-20K", "lowSalary": 10, "highSalary": 20},
            ],
            "experienceList": [
                {"code": 0, "name": "不限"},
                {"code": 104, "name": "1-3年"},
            ],
            "degreeList": [
                {"code": 0, "name": "不限"},
                {"code": 203, "name": "本科"},
            ],
            "scaleList": [
                {"code": 0, "name": "不限"},
                {"code": 306, "name": "10000人以上"},
            ],
            "stageList": [
                {"code": 0, "name": "不限"},
                {"code": 803, "name": "A轮"},
            ],
        },
    }


def industry_payload() -> dict:
    """``industry.json`` 的 ``zpData`` 是**数组**（与 conditions.json 的对象形状不同）。"""
    return {
        "code": 0,
        "zpData": [
            {
                "code": 100000,
                "name": "互联网/AI",
                "subLevelModelList": [
                    {"code": 100020, "name": "互联网"},
                    {"code": 100028, "name": "人工智能"},
                ],
            }
        ],
    }


def bar_payload(industry_code: str = "23") -> dict:
    """一份与 ``FILTER_BAR_SCRIPT`` 同形的产出（含行业的渲染序号陷阱）。"""
    return {
        "url": "https://www.zhipin.com/web/geek/jobs?query=python",
        "groups": [
            {
                "title": "求职类型",
                "options": [
                    {"code": "0", "label": "不限", "group": ""},
                    {"code": "1901", "label": "全职", "group": ""},
                    {"code": "1903", "label": "兼职", "group": ""},
                    {"code": "1902", "label": "实习", "group": ""},
                ],
            },
            {
                "title": "公司行业",
                "options": [
                    {"code": industry_code, "label": "电子/半导体/集成电路",
                     "group": "电子/通信/半导体"},
                ],
            },
        ],
    }


def fake_fetcher(mapping: dict[str, object]):
    calls: list[str] = []

    def _get(url: str, timeout: float):
        calls.append(url)
        if url not in mapping:
            raise OSError(f"没有为 {url} 准备假响应")
        return mapping[url]

    _get.calls = calls  # type: ignore[attr-defined]
    return _get


# ===== 解析 =====


def test_parse_conditions_keeps_the_zero_code():
    """「不限」的编码是数字 0。**它必须留下来**——`str(0 or "")` 会把它吃成空串，
    每个下拉框就都少一个选项，而用户看不出少的是哪一个。"""
    parsed = parse_conditions(conditions_payload())
    assert parsed["jobType"][0].code == UNLIMITED_CODE
    assert parsed["jobType"][0].label == "不限"
    assert [item.code for item in parsed["degree"]] == ["0", "203"]


def test_parse_conditions_ignores_error_responses():
    assert parse_conditions({"code": 403, "message": "forbidden", "zpData": {}}) == {}
    assert parse_conditions(None) == {}
    assert parse_conditions("<html>") == {}


def test_parse_industries_accepts_the_array_shaped_container():
    """``industry.json`` 的 ``zpData`` 是数组。只认对象的写法会让行业清单**静默变空**。"""
    parsed = parse_industries(industry_payload())
    assert [(item.code, item.label, item.group) for item in parsed] == [
        ("100020", "互联网", "互联网/AI"),
        ("100028", "人工智能", "互联网/AI"),
    ]
    assert parse_industries({"code": 0, "zpData": {"industryList": []}}) == ()


def test_parse_filter_bar_maps_groups_by_title():
    parsed = parse_filter_bar(bar_payload())
    assert [item.code for item in parsed["jobType"]] == ["0", "1901", "1903", "1902"]
    # 行业缺席：它在筛选栏里只给渲染序号，真实编码要从接口拿（见下一个用例）。
    assert "industry" not in parsed


def test_parse_filter_bar_never_trusts_the_industry_render_index():
    """**这是本模块最要紧的一条**：行业的 ``ka`` 后缀是渲染序号（``sel-industry-23``），
    真实编码是 ``101407``。照抄序号会发一个"合法但不相干"的编码出去，站点照样返回结果——
    用户以为筛了，那是最坏的一种错。所以行业一律不采纳页面那份。"""
    catalogue = build_catalogue(bar=parse_filter_bar(bar_payload(industry_code="23")))
    industry = next(group for group in catalogue if group.key == "industry")
    assert industry.options == ()
    assert industry.source == SOURCE_UNAVAILABLE


def test_parse_filter_bar_tolerates_unknown_titles_and_junk():
    parsed = parse_filter_bar(
        {"groups": [{"title": "没见过的格子", "options": [{"code": "1", "label": "x"}]},
                    "junk", {"title": "学历要求", "options": [{"code": "", "label": "空编码"}]}]}
    )
    assert parsed == {}


# ===== 目录构建与来源 =====


def test_build_catalogue_lets_the_page_win_over_the_interface():
    """页面那份是用户真实看到的（含账号可见的完整求职类型），接口那份只是补它的缺。"""
    catalogue = build_catalogue(
        conditions=parse_conditions(conditions_payload()),
        industries=parse_industries(industry_payload()),
        bar=parse_filter_bar(bar_payload()),
        source=SOURCE_SESSION,
    )
    by_key = {group.key: group for group in catalogue}
    assert [item.label for item in by_key["jobType"].options] == ["不限", "全职", "兼职", "实习"]
    assert [item.label for item in by_key["industry"].options] == ["互联网", "人工智能"]
    assert by_key["industry"].source == SOURCE_SESSION


def test_snapshot_covers_every_short_list_but_not_industry():
    by_key = {group.key: group for group in snapshot_catalogue()}
    for key in ("jobType", "salary", "experience", "degree", "scale", "stage"):
        assert by_key[key].options, f"{key} 的快照不该是空的"
        assert by_key[key].source == SOURCE_SNAPSHOT
    # 行业 134 条不进代码，拿不到就如实标不可用。
    assert by_key["industry"].source == SOURCE_UNAVAILABLE


def test_fetch_catalogue_prefers_the_session_then_public_then_snapshot():
    getter = fake_fetcher(
        {CONDITIONS_ENDPOINT: conditions_payload(), INDUSTRY_ENDPOINT: industry_payload()}
    )
    # 1) 会话里读到了 → 用会话那份，同时**仍然补一次免登录请求**拿行业。
    session = fetch_catalogue(
        fetcher=getter, session_values={CONDITIONS_ENDPOINT: conditions_payload()},
        bar_payload=bar_payload(),
    )
    assert all(group.source == SOURCE_SESSION for group in session)
    assert INDUSTRY_ENDPOINT in getter.calls

    # 2) 会话读不到 → 免登录公开清单。
    public = fetch_catalogue(fetcher=getter)
    assert all(group.source == SOURCE_PUBLIC for group in public)

    # 3) 网络也不通 → 内置快照。
    def boom(url: str, timeout: float):
        raise OSError("offline")

    offline = fetch_catalogue(fetcher=boom)
    assert next(g for g in offline if g.key == "degree").source == SOURCE_SNAPSHOT


def test_fetch_catalogue_uses_the_session_bar_even_when_the_fetch_failed():
    """页面筛选栏读到了、带凭据的接口没读到，也要用页面那份——它同样含账号可见的选项。"""
    getter = fake_fetcher({INDUSTRY_ENDPOINT: industry_payload()})
    catalogue = fetch_catalogue(fetcher=getter, bar_payload=bar_payload())
    job_type = next(group for group in catalogue if group.key == "jobType")
    assert [item.label for item in job_type.options] == ["不限", "全职", "兼职", "实习"]
    assert job_type.source == SOURCE_SESSION


# ===== 编码校验 =====


def test_resolve_codes_skips_unlimited_and_builds_params():
    resolved = resolve_codes(
        {"degree": "203", "scale": "0"}, build_catalogue(conditions=parse_conditions(conditions_payload()))
    )
    assert resolved.params == {"degree": "203"}
    assert resolved.applied == ["学历要求：本科"]
    assert resolved.unapplied == []
    assert resolved.as_dict()["params"] == {"degree": "203"}


def test_resolve_codes_refuses_codes_it_cannot_verify():
    """站点改版后旧编码照样"合法"，发出去会静默筛错——**宁可如实报未生效**。"""
    resolved = resolve_codes(
        {"scale": "999999", "degree": "203"},
        build_catalogue(conditions=parse_conditions(conditions_payload())),
    )
    assert resolved.params == {"degree": "203"}
    assert resolved.unapplied == ["公司规模"]
    assert "scale" not in resolved.params


def test_resolve_codes_reports_a_group_whose_list_is_missing():
    resolved = resolve_codes({"industry": "100028"}, snapshot_catalogue())
    assert resolved.params == {}
    assert resolved.unapplied == ["公司行业"]


def test_resolve_codes_reports_a_group_the_site_no_longer_offers():
    """旧配置里留下的分组（站点已经不提供了）也要报出来，不能悄悄丢掉。"""
    resolved = resolve_codes({"payType": "2503"}, snapshot_catalogue())
    assert resolved.unapplied == ["payType"]


def test_resolve_codes_without_selection_is_a_no_op():
    assert resolve_codes(None, snapshot_catalogue()).as_dict() == {
        "params": {},
        "applied": [],
        "unapplied": [],
    }


# ===== 适配器接线 =====


def test_build_search_url_carries_the_verified_filter_params():
    adapter = BossAdapter()
    url = adapter.build_search_url(
        CollectQuery(
            keywords=["python"],
            city="成都",
            filters={"degree": "203", "salary": "405"},
        ),
        2,
    )
    assert "degree=203" in url
    assert "salary=405" in url
    assert url.endswith("&page=2")


def test_build_search_url_lets_the_explicit_job_type_win():
    """同一个 ``jobType`` 不能在地址里出现两次：旧映射（岗位类型）与用户显式选择
    （站点筛选）撞车时，站点取哪一个不确定——那正是"我选了实习却混进全职"的成因。"""
    adapter = BossAdapter()
    url = adapter.build_search_url(
        CollectQuery(keywords=["python"], city="成都", job_type="社招",
                     filters={"jobType": "1902"}),
        1,
    )
    assert url.count("jobType=") == 1
    assert "jobType=1902" in url
    assert "jobType=1901" not in url


def test_build_search_url_keeps_the_legacy_job_type_mapping_without_site_filters():
    adapter = BossAdapter()
    url = adapter.build_search_url(
        CollectQuery(keywords=["python"], city="成都", job_type="实习"), 1
    )
    assert "jobType=1902" in url


def test_build_search_url_escapes_param_names_and_codes():
    """键名来自站点，一律转义——站点改个键名不该把查询串拼坏。"""
    adapter = BossAdapter()
    url = adapter.build_search_url(
        CollectQuery(keywords=["a"], city="成都", filters={"a b": "x&y=1", "": "skip"}), 1
    )
    assert "a%20b=x%26y%3D1" in url
    assert "skip" not in url


def test_adapter_prepares_filters_offline_with_an_injected_fetcher():
    adapter = BossAdapter(
        filter_fetcher=fake_fetcher(
            {CONDITIONS_ENDPOINT: conditions_payload(), INDUSTRY_ENDPOINT: industry_payload()}
        )
    )
    resolved = adapter.prepare_collect_filters({"degree": "203", "scale": "306"}, None)
    assert resolved.params == {"degree": "203", "scale": "306"}
    assert resolved.unapplied == []


def test_adapter_reports_filters_it_could_not_verify():
    adapter = BossAdapter(
        filter_fetcher=fake_fetcher({CONDITIONS_ENDPOINT: conditions_payload()})
    )
    resolved = adapter.prepare_collect_filters({"degree": "999"}, None)
    assert isinstance(resolved, FilterResolution)
    assert resolved.params == {}
    assert resolved.unapplied == ["学历要求"]


def test_adapter_without_selection_never_touches_the_network():
    """没选任何筛选项时不该发请求：这是最常见的一次采集，白读一次清单毫无意义。"""
    getter = fake_fetcher({})
    adapter = BossAdapter(filter_fetcher=getter)
    assert adapter.prepare_collect_filters({}, None).params == {}
    assert adapter.prepare_collect_filters(None, None).unapplied == []
    assert getter.calls == []  # type: ignore[attr-defined]


def test_adapter_reads_the_session_first_when_a_client_is_available():
    getter = fake_fetcher({INDUSTRY_ENDPOINT: industry_payload()})

    class FakeClient:
        def __init__(self) -> None:
            self.scripts: list[str] = []

        def evaluate(self, expression: str, **_kwargs):
            self.scripts.append(expression)
            if "rf:filter-conditions" in expression:
                import json

                return json.dumps(conditions_payload(), ensure_ascii=False)
            return bar_payload()

    client = FakeClient()
    adapter = BossAdapter(filter_fetcher=getter)
    groups = adapter.fetch_filter_options(client)
    assert [item.label for item in groups[0].options] == ["不限", "全职", "兼职", "实习"]
    assert groups[0].source == SOURCE_SESSION
    # 页面上已经有筛选栏时**不再发那次接口请求**：筛选栏更完整，而那次 fetch 在 geek 页面上
    # 根本不会 resolve，继续等它只会白等一个轮询预算。
    assert any("rf:filters" in script for script in client.scripts)
    assert not any("rf:filter-conditions" in script for script in client.scripts)


def test_adapter_uses_the_credentialed_fetch_when_the_page_has_no_bar():
    """页面不是搜索结果页（例如停在站点首页）时，靠带登录态的接口请求补齐账号可见的选项。"""
    getter = fake_fetcher({INDUSTRY_ENDPOINT: industry_payload()})

    class HomePageClient:
        def __init__(self) -> None:
            self.saw_fetch_script = False

        def evaluate(self, expression: str, **_kwargs):
            if "rf:filters" in expression:
                return {"groups": []}  # 首页上没有筛选栏
            if "rf:filter-conditions" in expression:
                self.saw_fetch_script = True
                return 1
            if "__rfFilterConditions" in expression:
                import json

                return json.dumps(conditions_payload(), ensure_ascii=False)
            return None

    client = HomePageClient()
    adapter = BossAdapter(filter_fetcher=getter)
    groups = adapter.fetch_filter_options(client)
    assert client.saw_fetch_script
    assert groups[0].source == SOURCE_SESSION
    assert [item.label for item in groups[0].options] == ["不限", "全职", "兼职"]


def test_adapter_gives_up_quickly_when_the_credentialed_fetch_never_resolves():
    """**实测过的站点行为**：geek 页面上那次 fetch 永远不 resolve。它必须迅速收手，
    而不是把每一次读取都拖成一次完整超时（那会让配置界面转圈、让采集启动变慢）。"""

    class HangingClient:
        def __init__(self) -> None:
            self.polls = 0

        def evaluate(self, expression: str, **_kwargs):
            if "rf:filters" in expression:
                return {"groups": []}
            if "rf:filter-conditions" in expression:
                return 1
            if "__rfFilterConditions" in expression:
                self.polls += 1
                return None  # 永远 pending
            return None

    client = HangingClient()
    adapter = BossAdapter(filter_fetcher=fake_fetcher({}))
    started = time.monotonic()
    groups = adapter.fetch_filter_options(client)
    elapsed = time.monotonic() - started
    assert client.polls > 0
    assert elapsed < CONDITIONS_FETCH_WAIT_SECONDS + 3
    # 拿不到就退回公开清单（测试环境里公开也读不到 → 快照），**不是**空清单。
    assert groups[0].options


class _BarOnlyClient:
    """停在**岗位详情页**的浏览器：页面上没有筛选栏，只有带登录态的 fetch 能拿到清单。

    这正是"采集开始那一刻"的真实状态——上一轮采集的最后一个动作是打开岗位详情。免登录的
    公开清单里没有「实习」这类只对某些账号可见的档，所以第一次校验必然判它"没能生效"。
    """

    def __init__(self, public_job_types: list[dict] | None = None) -> None:
        self.navigated: list[str] = []
        self._conditions = public_job_types or conditions_payload()["zpData"]["jobTypeList"]
        self._on_search_page = False
        self._fetch_done = False

    def navigate(self, url: str, **_kwargs):
        self.navigated.append(url)
        self._on_search_page = "geek/jobs" in url
        return {}

    def evaluate(self, expression: str, **_kwargs):
        if "rf:filters" in expression:
            return bar_payload() if self._on_search_page else {"groups": []}
        if "rf:filter-conditions" in expression:
            self._fetch_done = False
            return 1
        if "__rfFilterConditions" in expression:
            self._fetch_done = True
            return None  # geek 页面上那次 fetch 永远不 resolve（实测）
        return None


def test_prepare_opens_the_search_page_when_the_public_list_is_not_enough():
    """选了公开清单里没有的档（「实习」）时，才去搜索页读一次筛选栏，然后就能生效。"""
    getter = fake_fetcher(
        {CONDITIONS_ENDPOINT: conditions_payload(), INDUSTRY_ENDPOINT: industry_payload()}
    )
    client = _BarOnlyClient()
    adapter = BossAdapter(filter_fetcher=getter)
    resolved = adapter.prepare_collect_filters({"jobType": "1902"}, client)
    assert resolved.params == {"jobType": "1902"}
    assert resolved.applied == ["求职类型：实习"]
    assert resolved.unapplied == []
    assert client.navigated == ["https://www.zhipin.com/web/geek/jobs"]


def test_prepare_does_not_open_any_page_when_the_public_list_already_answers():
    """公开清单就能确认的选项**一次多余页面都不开**——这是绝大多数采集的情形。"""
    getter = fake_fetcher(
        {CONDITIONS_ENDPOINT: conditions_payload(), INDUSTRY_ENDPOINT: industry_payload()}
    )
    client = _BarOnlyClient()
    adapter = BossAdapter(filter_fetcher=getter)
    resolved = adapter.prepare_collect_filters({"degree": "203", "scale": "306"}, client)
    assert resolved.params == {"degree": "203", "scale": "306"}
    assert client.navigated == []


def test_prepare_does_not_open_a_page_when_one_is_already_there():
    """页面上已经有筛选栏（用户就停在搜索页）时不再导航——那会把他正在看的页面顶掉。"""
    getter = fake_fetcher(
        {CONDITIONS_ENDPOINT: conditions_payload(), INDUSTRY_ENDPOINT: industry_payload()}
    )
    client = _BarOnlyClient()
    client._on_search_page = True
    adapter = BossAdapter(filter_fetcher=getter)
    resolved = adapter.prepare_collect_filters({"jobType": "1902"}, client)
    assert resolved.params == {"jobType": "1902"}
    assert client.navigated == []


def test_adapter_falls_back_when_the_page_read_fails():
    class BrokenClient:
        def evaluate(self, expression: str, **_kwargs):
            raise RuntimeError("页面读不到")

    adapter = BossAdapter(
        filter_fetcher=fake_fetcher(
            {CONDITIONS_ENDPOINT: conditions_payload(), INDUSTRY_ENDPOINT: industry_payload()}
        )
    )
    groups = adapter.fetch_filter_options(BrokenClient())
    assert all(group.source == SOURCE_PUBLIC for group in groups)


# ===== 接口 =====


class _StoppedBrowser:
    """假装浏览器没启动。

    **测试必须显式把浏览器摘掉**：接口会去探测投递专用浏览器的调试端口，而开发者本机
    常常真的开着一个（跑真实采集验证时就是），于是这个用例的结果取决于那台机器当下的状态。
    """

    @staticmethod
    def status():
        return SimpleNamespace(state="stopped")


def _no_browser(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.apply.apply_service.get_browser_manager", lambda _db: _StoppedBrowser()
    )


def test_filter_options_endpoint_returns_groups(client, monkeypatch):
    adapter = BossAdapter(
        filter_fetcher=fake_fetcher(
            {CONDITIONS_ENDPOINT: conditions_payload(), INDUSTRY_ENDPOINT: industry_payload()}
        )
    )
    monkeypatch.setattr("app.services.apply.apply_service.current_site", lambda _db: adapter)
    _no_browser(monkeypatch)

    response = client.get("/api/collect/filters")
    assert response.status_code == 200
    body = response.json()
    assert body["site_key"] == "boss"
    assert body["session_read"] is False  # 没有浏览器 → 用的是公开清单
    by_key = {group["key"]: group for group in body["groups"]}
    assert by_key["degree"]["param"] == "degree"
    assert [item["label"] for item in by_key["degree"]["options"]] == ["不限", "本科"]
    assert by_key["industry"]["options"][1] == {
        "code": "100028",
        "label": "人工智能",
        "group": "互联网/AI",
    }


def test_filter_options_endpoint_degrades_instead_of_failing(client, monkeypatch):
    """清单读不到是降级路径：界面最多少一个筛选区，绝不能因此打不开。"""

    class BrokenAdapter:
        key = "boss"
        display_name = "BOSS 直聘"

        def fetch_filter_options(self, _client=None):
            raise RuntimeError("站点接口挂了")

    monkeypatch.setattr(
        "app.services.apply.apply_service.current_site", lambda _db: BrokenAdapter()
    )
    _no_browser(monkeypatch)
    response = client.get("/api/collect/filters")
    assert response.status_code == 200
    assert response.json()["groups"] == []


def test_filter_options_endpoint_degrades_when_the_browser_probe_raises(client, monkeypatch):
    """浏览器状态探测本身炸了，也要当"没启动"处理，而不是把 500 抛给界面。"""

    def boom(_db):
        raise BrowserError("调试端口没应答")

    monkeypatch.setattr("app.services.apply.apply_service.get_browser_manager", boom)
    monkeypatch.setattr(
        "app.services.apply.apply_service.current_site",
        lambda _db: BossAdapter(
            filter_fetcher=fake_fetcher({CONDITIONS_ENDPOINT: conditions_payload()})
        ),
    )
    response = client.get("/api/collect/filters")
    assert response.status_code == 200
    assert response.json()["session_read"] is False


def test_collect_config_round_trips_site_filters(client):
    """筛选项随采集条件一起存、一起读。"""
    response = client.put(
        "/api/collect/config",
        json={"keywords": ["python"], "city": "成都", "filters": {"degree": "203"}},
    )
    assert response.status_code == 200
    assert response.json()["filters"] == {"degree": "203"}
    assert client.get("/api/collect/config").json()["filters"] == {"degree": "203"}


@pytest.mark.parametrize(
    "payload",
    [
        {"filters": {f"k{index}": "1" for index in range(20)}},
        {"filters": {"k": "x" * 64}},
    ],
)
def test_collect_config_rejects_oversized_filters(client, payload):
    response = client.put("/api/collect/config", json={"keywords": ["python"], **payload})
    assert response.status_code == 422
