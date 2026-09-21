"""接口响应解析与「网络优先、DOM 兜底」两条路径。

**为什么这块值得单独测**：网络解析的失败方式很隐蔽——接口路径变了、结构变了、
被风控换成 HTML，任何一处不对都会让整条采集**静默退回 DOM**。退回本身是对的，
但如果没人测"什么时候该退回"，就会变成"网络这条路其实从来没生效过"却没人发现。

所以这里两条都测：**走得通时必须用网络结果**（字段更全），**走不通时必须安静退回 DOM**
（而不是抛异常或返回空）。

还有一类更隐蔽的："退回 DOM"不是因为接口变了，而是因为**订阅的时序写错了**——比如
导航完就停止订阅（可 XHR 要等页面跑起来才发），或者包装层没把订阅转发下去。这两处都
曾经真的写错过，所以假客户端按**真实时序**推送事件（见 ``ScriptedClient``），并且
单独钉住订阅 / 导航 / 取走 / 停止的先后顺序。
"""
import base64
import json

import pytest

from app.models.apply import FAILURE_SELECTOR_INVALID
from app.services.browser.network_capture import (
    MAX_BODY_BYTES,
    collect_bodies,
    first_json_with,
    response_urls,
)
from app.services.apply.task_runner import StopAwareCdpClient, TaskStopped
from app.services.browser.page_ready import ReadyWait
from app.services.sites.base import CollectQuery, SiteFailure
from app.services.sites.boss import NETWORK_RESPONSE_EVENT, BossAdapter
from app.services.sites.boss_network import (
    DETAIL_MARKERS,
    SEARCH_MARKER,
    SEARCH_MARKERS,
    api_error,
    format_salary,
    looks_like_detail,
    looks_like_search,
    parse_detail_response,
    parse_salary_text,
    parse_search_response,
)


# ===== 薪资格式化 =====


def test_salary_uses_the_same_wording_as_the_site():
    """用户在页面上看到的是「20-40K」，接口里是 20000/40000，格式化后要能对上。"""
    assert format_salary(20000, 40000) == "20-40K"
    assert format_salary(20000, 20000) == "20K"
    assert format_salary(20000, 40000, 16) == "20-40K·16薪"


def test_daily_salary_is_not_shown_as_monthly_k():
    """300-800 是日薪，写成「0-1K」会让人以为这岗位月薪一块钱。"""
    assert format_salary(300, 800) == "300-800元/天"


def test_missing_salary_stays_empty_instead_of_being_invented():
    assert format_salary(None, None) == ""
    assert format_salary(0, 0) == ""
    assert format_salary("面议", "面议") == ""
    # 只有一边有值时补齐，不要留一个半截的区间。
    assert format_salary(20000, None) == "20K"


def test_absurd_month_count_is_ignored():
    assert format_salary(20000, 40000, 99) == "20-40K"


# ===== 列表响应解析 =====


def _search_payload() -> dict:
    return {
        "code": 0,
        "zpData": {
            "jobList": [
                {
                    "jobName": "后端开发实习生",
                    "brandName": "示例科技",
                    "cityName": "天津",
                    "encryptJobId": "abc123",
                    "lowSalary": 200,
                    "highSalary": 300,
                    "jobExperience": "在校/应届",
                    "jobDegree": "本科",
                    "brandIndustry": "互联网",
                    "brandScaleName": "100-499人",
                    "brandStageName": "B轮",
                    "skills": ["Python", "FastAPI", "Python"],
                    "bossActiveTimeDesc": "今日活跃",
                }
            ]
        },
    }


def test_search_response_maps_to_the_same_shape_as_the_dom_script():
    """两条路产出的结构必须一致，上层才能不分支地处理。"""
    items = parse_search_response(_search_payload())
    assert items is not None
    first = items[0]
    # DOM 脚本产出的五个字段一个都不能少。
    assert set(first) >= {"title", "company", "location", "salary", "url"}
    assert first["title"] == "后端开发实习生"
    assert first["company"] == "示例科技"
    assert first["location"] == "天津"
    assert first["salary"] == "200-300元/天"
    assert "abc123" in first["url"]


def test_search_response_keeps_the_extra_fields_the_dom_cannot_see():
    """经验、学历、技能标签是 DOM 里读不到的——这正是走网络的理由。"""
    items = parse_search_response(_search_payload())
    extra = items[0]["extra"]
    assert extra["experience"] == "在校/应届"
    assert extra["degree"] == "本科"
    assert extra["skills"] == ["Python", "FastAPI"]  # 去重后
    assert extra["industry"] == "互联网"


def test_unrecognised_structures_return_none_instead_of_raising():
    """接口路径变了、结构换了——这些都该安静地退回 DOM，而不是让采集失败。"""
    for payload in (None, [], {}, {"zpData": {}}, {"zpData": {"jobList": []}}, "不是 JSON 结构"):
        assert parse_search_response(payload) is None
    assert looks_like_search({}) is False


def test_items_without_an_encrypt_id_still_come_through():
    """拿不到详情页地址时不该整条丢掉——上层会退回"点开卡片拿 href"。"""
    payload = {"zpData": {"jobList": [{"jobName": "实习生", "brandName": "某公司"}]}}
    items = parse_search_response(payload)
    assert items is not None
    assert items[0]["url"] == ""


def test_search_parser_accepts_field_aliases_inside_the_real_container():
    """**卡片内的字段**改名仍能解析（`jobName`→`jobTitle`、`salaryMin`、`skillList`…）。

    与 `test_site_contract_drift.py` 的分工是刻意的：那边钉住"**容器与键**改名即失败"
    （`data` 这类泛化名字会让页面上无关的响应也被判成岗位列表）；这里钉住"**字段**改名
    仍能用"——字段名足够具体，而且还有岗位名等内容特征把关，放宽是安全的。
    """
    payload = {
        "code": 0,
        "zpData": {
            "jobList": [
                {
                    "jobTitle": "平台开发工程师",
                    "areaName": "杭州",
                    "encryptId": "renamed123",
                    "salaryMin": 18000,
                    "salaryMax": 30000,
                    "experienceName": "3-5年",
                    "degreeName": "本科",
                    "skillList": [{"name": "Python"}, {"tagName": "Redis"}],
                }
            ]
        },
    }

    items = parse_search_response(payload)
    assert items is not None
    assert items[0]["title"] == "平台开发工程师"
    assert items[0]["location"] == "杭州"
    assert items[0]["salary"] == "18-30K"
    assert items[0]["extra"]["skills"] == ["Python", "Redis"]
    assert looks_like_search(payload) is True


def test_search_parser_prefers_an_explicit_detail_url():
    """接口直接给了详情页地址时用它，而不是用 id 拼一个。"""
    payload = {
        "zpData": {
            "jobList": [
                {
                    "jobTitle": "平台开发工程师",
                    "brandName": "别名科技",
                    "jobUrl": "/job_detail/url-alias.html",
                }
            ]
        }
    }

    items = parse_search_response(payload)

    assert items is not None
    assert items[0]["url"] == "https://www.zhipin.com/job_detail/url-alias.html"


def test_generic_list_alias_is_not_mistaken_for_jobs():
    payload = {"data": {"list": [{"title": "一条新闻", "url": "/article/1"}]}}
    assert parse_search_response(payload) is None
    assert looks_like_search(payload) is False


# ===== 详情响应解析 =====


def _detail_payload() -> dict:
    return {
        "zpData": {
            "jobInfo": {
                "jobName": "后端开发实习生",
                "encryptJobId": "abc123",
                "postDescription": "<p>负责接口开发<br>参与联调</p>",
                "jobDegree": "本科",
                "jobExperience": "在校/应届",
                "skills": ["Python", "Redis"],
            },
            "bossInfo": {"activeTimeDesc": "今日活跃", "name": "张女士", "title": "HR"},
            "brandInfo": {"brandName": "示例科技", "brandIndustry": "互联网"},
        }
    }


def test_detail_response_strips_html_and_keeps_the_full_jd():
    parsed = parse_detail_response(_detail_payload())
    assert parsed is not None
    assert parsed["job_title"] == "后端开发实习生"
    assert parsed["company"] == "示例科技"
    # HTML 标签要变成换行，不能把标签本身喂给匹配分析。
    assert "<p>" not in parsed["description"]
    assert "负责接口开发" in parsed["description"]
    assert "参与联调" in parsed["description"]


def test_detail_response_keeps_hr_activity_for_the_filter():
    """HR 活跃时间是"过滤不活跃 HR"唯一可靠的依据，DOM 里拿不到。"""
    parsed = parse_detail_response(_detail_payload())
    assert parsed["extra"]["hr_active_time"] == "今日活跃"
    assert parsed["extra"]["skills"] == ["Python", "Redis"]


def test_detail_response_does_not_duplicate_the_description_into_requirements():
    """接口没有把"任职要求"单列出来；为了凑字段把描述复制一份会让匹配分析读到两份同样文本。"""
    parsed = parse_detail_response(_detail_payload())
    assert parsed["requirements"] == ""


def test_detail_without_a_description_is_not_a_detail():
    """描述为空时这份数据没有价值——如实返回 None，让上层退回 DOM。"""
    payload = {"zpData": {"jobInfo": {"jobName": "岗位", "postDescription": ""}}}
    assert parse_detail_response(payload) is None
    assert looks_like_detail(payload) is False
    assert looks_like_detail({"zpData": {"jobInfo": {"postDescription": "有内容"}}}) is True


def test_detail_parser_accepts_field_aliases():
    """详情侧同样只对**字段**放宽：`postDescription`→`jobDescription`、`activeTimeDesc`→
    `activeDesc` 等仍能读到，但容器（`zpData` / `jobInfo`）与列表侧一样只认原名。"""
    payload = {
        "zpData": {
            "jobInfo": {
                "jobTitle": "后端工程师",
                "encryptId": "detail123",
                "jobDescription": "<p>负责服务端开发</p>",
                "degreeName": "本科",
            },
            "recruiterInfo": {"activeDesc": "刚刚活跃", "recruiterName": "李女士"},
            "brandInfo": {"brandName": "示例公司"},
        }
    }
    parsed = parse_detail_response(payload)
    assert parsed is not None
    assert parsed["job_title"] == "后端工程师"
    assert parsed["company"] == "示例公司"
    assert parsed["description"] == "负责服务端开发"
    assert parsed["extra"]["hr_active_time"] == "刚刚活跃"
    assert looks_like_detail(payload) is True


def test_detail_parser_accepts_brand_com_info():
    payload = {
        "zpData": {
            "jobInfo": {"jobName": "后端工程师", "postDescription": "负责接口开发"},
            "brandComInfo": {"brandName": "新版公司容器"},
        }
    }

    parsed = parse_detail_response(payload)

    assert parsed is not None
    assert parsed["company"] == "新版公司容器"


def test_api_error_recognises_nonzero_code_and_message():
    assert api_error({"code": 19, "message": "参数值错误"}) == ("19", "参数值错误")
    assert api_error({"code": 0, "message": "Success"}) is None
    assert api_error({"data": {"jobs": []}}) is None


# ===== 事件与响应体 =====


def _response_event(request_id: str, url: str) -> dict:
    return {
        "method": "Network.responseReceived",
        "params": {"requestId": request_id, "response": {"url": url}},
    }


def _body_event(request_id: str, body, *, base64_encoded: bool = False) -> dict:
    raw = json.dumps(body, ensure_ascii=False)
    if base64_encoded:
        raw = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    return {
        "method": "Network.getResponseBody",
        "requestId": request_id,
        "result": {"body": raw, "base64Encoded": base64_encoded},
    }


def test_response_urls_filter_by_markers_and_keep_order():
    events = [
        _response_event("1", "https://www.zhipin.com/img/logo.png"),
        _response_event("2", f"https://www.zhipin.com{SEARCH_MARKER}?page=1"),
        _response_event("3", f"https://www.zhipin.com{SEARCH_MARKER}?page=2"),
    ]
    urls = response_urls(events, markers=SEARCH_MARKERS)
    # 顺序有意义：页面上同一接口会被调用多次，先回来的通常是我们正要的那份。
    assert urls == [
        f"https://www.zhipin.com{SEARCH_MARKER}?page=1",
        f"https://www.zhipin.com{SEARCH_MARKER}?page=2",
    ]
    assert response_urls(events, markers=DETAIL_MARKERS) == []


def test_loose_markers_survive_an_api_path_rename():
    """站点给接口路径加版本后缀（``joblist.json`` → ``joblistV2.json``）时仍要认得出来。

    以前只认整串路径，改一次命名整条"网络优先"通路就**静默失效**（失败方式是退回 DOM，
    从外面完全看不出来），而 DOM 恰好是最容易被改版打穿的那一层。
    """
    exact = f"https://www.zhipin.com{SEARCH_MARKER}?page=1"
    renamed = "https://www.zhipin.com/wapi/zpgeek/search/joblistV2.json?page=1"
    events = [_response_event("1", exact), _response_event("2", renamed)]

    # 原路径与改版后的路径都要认得出来，且保持出现顺序。
    assert response_urls(events, markers=SEARCH_MARKERS) == [exact, renamed]
    # 两套候选**不能重叠**：列表响应绝不能被当成详情去解析（结构完全不同）。
    assert response_urls(events, markers=DETAIL_MARKERS) == []


def test_collect_bodies_decodes_base64_payloads():
    events = [
        _response_event("1", "https://x" + SEARCH_MARKER),
        _body_event("1", _search_payload(), base64_encoded=True),
    ]
    captured = collect_bodies(events)
    assert len(captured) == 1
    assert captured[0].body["zpData"]["jobList"]


def test_non_json_bodies_are_skipped_silently():
    """抓到 HTML（被风控换成验证页）时不该报错，只是没有可用数据。"""
    events = [
        _response_event("1", "https://x" + SEARCH_MARKER),
        {"method": "Network.getResponseBody", "requestId": "1", "result": {"body": "<html>验证</html>"}},
    ]
    assert collect_bodies(events) == []


def test_oversized_bodies_are_rejected():
    """被注入的探针或图片会返回巨大响应体，解它只会占内存。"""
    huge = "x" * (MAX_BODY_BYTES + 10)
    events = [
        _response_event("1", "https://x" + SEARCH_MARKER),
        {"method": "Network.getResponseBody", "requestId": "1", "result": {"body": huge}},
    ]
    assert collect_bodies(events) == []


def test_first_json_with_takes_the_first_matching_body():
    events = [
        _response_event("1", "https://x" + SEARCH_MARKER),
        _body_event("1", {"无关": True}),
        _response_event("2", "https://x" + SEARCH_MARKER),
        _body_event("2", _search_payload()),
    ]
    captured = collect_bodies(events)
    found = first_json_with(captured, looks_like_search)
    assert found is not None and found["zpData"]["jobList"]
    assert first_json_with(captured, looks_like_detail) is None


def test_a_failing_predicate_does_not_break_the_capture():
    """判定函数自己出错时只是跳过那一条，不该让整次采集挂掉。"""

    def explode(_payload):
        raise RuntimeError("判定函数写错了")

    events = [
        _response_event("1", "https://x" + SEARCH_MARKER),
        _body_event("1", _search_payload()),
    ]
    assert first_json_with(collect_bodies(events), explode) is None


# ===== 适配器：网络优先、DOM 兜底 =====


class ScriptedClient:
    """能推送网络事件、也能回答脚本表达式的假客户端。

    **响应是在"页面加载过程中"回来的**，这里用 ``evaluate`` 来代表那个时刻：只有订阅
    还开着时收到探针调用，待推送的响应才会进缓冲区。若把事件当成"构造时就躺在缓冲区里"，
    那么"导航完就取走并停止订阅"这类**时序错误**（真实浏览器里 XHR 正是等待期间才回来）
    在测试里永远暴露不出来——而它在生产中的表现是**静默退回 DOM**。
    """

    def __init__(self, *, events=None, expressions=None, supports_capture=True):
        self._pending = list(events or [])
        self._buffered: list[dict] = []
        self._all_events = list(events or [])
        self._expressions = expressions or {}
        self.navigations: list[str] = []
        self.capture_methods: list[str] = []
        self.started_with: list[str] = []
        self.sent: list[str] = []
        # 订阅 / 导航 / 取走 / 停止的先后顺序本身就是要验的东西（见各条测试的断言）。
        self.log: list[str] = []
        if supports_capture:
            self.start_event_capture = self._start  # type: ignore[assignment]
            self.drain_events = self._drain  # type: ignore[assignment]
            self.stop_event_capture = self._stop  # type: ignore[assignment]

    def _start(self, methods):
        self.capture_methods = list(methods)
        self.started_with = list(methods)
        self.log.append("subscribe")

    def _drain(self):
        self.log.append("drain")
        events, self._buffered = self._buffered, []
        return events

    def _stop(self):
        # 真实实现（WebsocketCdpClient）在这里连缓冲区一起清掉，所以调用方必须**先取走
        # 再停止**；这个假客户端照做，好让写错顺序的实现被测出来。
        self.log.append("stop")
        self.capture_methods = []
        self._buffered = []

    def _release(self):
        """页面又跑了一会儿：待推送的响应进入缓冲区——但只有订阅还开着才收得到。"""
        if self.capture_methods:
            self._buffered.extend(self._pending)
            self._pending = []

    def navigate(self, url, **_kwargs):
        self.log.append("navigate")
        self.navigations.append(url)
        return {}

    def send(self, method, params=None, **_kwargs):
        self.sent.append(method)
        # 模拟 Network.getResponseBody：把该 requestId 的响应体还回去。
        # 假客户端要能应答这个命令，否则"网络优先"这条路在测试里永远走不通，
        # 而它恰恰是这里要验的东西。
        if method == "Network.getResponseBody" and isinstance(params, dict):
            request_id = str(params.get("requestId") or "")
            for event in self._all_events:
                if event.get("method") == "Network.getResponseBody" and str(
                    event.get("requestId")
                ) == request_id:
                    return event.get("result") or {}
        return {}

    def evaluate(self, expression, **_kwargs):
        # 每一次探针调用都代表"页面又跑了一会儿"——接口响应就是在这个窗口里回来的。
        self._release()
        for marker, value in self._expressions.items():
            if marker in expression:
                if marker == "rf:readiness" and isinstance(value, dict) and not value.get("url"):
                    value = dict(value)
                    value["url"] = self.navigations[-1] if self.navigations else "about:blank"
                return json.dumps(value, ensure_ascii=False)
        return json.dumps({}, ensure_ascii=False)

    def list_targets(self):
        return []

    def new_tab(self, url="about:blank"):
        return "t"

    def close(self):
        return None


READY = {"matched": 3, "has_next": True}

# 等待参数调得很短：这里验的是"走哪条路"（网络优先 / 退回 DOM），不是"等多久"。
# 生产默认值是 15 秒，用它会让超时那几条测试每条白等 15 秒。
FAST_WAIT = ReadyWait(timeout=0.05, poll_interval=0.001)


def _adapter() -> BossAdapter:
    return BossAdapter(ready_wait=FAST_WAIT)


def test_collect_prefers_the_network_response_when_it_is_available():
    """接口走得通时必须用它的结果——字段更全，而且不受渲染时序影响。"""
    events = [
        _response_event("1", "https://www.zhipin.com" + SEARCH_MARKER),
        _body_event("1", _search_payload()),
    ]
    client = ScriptedClient(
        events=events,
        # DOM 脚本故意返回一份**不同的**数据：用到了它说明走错了路。
        expressions={"rf:readiness": READY, "rf:collect": {"items": [{"title": "DOM 来的"}]}},
    )

    page = _adapter().collect_search(client, CollectQuery(keywords=["后端"]), 1)

    assert len(page.results) == 1
    assert page.results[0].title == "后端开发实习生"
    assert page.results[0].company == "示例科技"
    # 额外字段也要带出来（DOM 里读不到）。
    assert page.results[0].extra["degree"] == "本科"
    # 顺序本身就是这条链路的关键：订阅早于导航（否则漏掉第一批响应），而响应要等页面
    # 跑起来才回来，所以"取走"必须晚于导航、"停止"必须晚于取走（停止会清掉缓冲区）。
    assert client.started_with == ["Network.responseReceived"]
    assert (
        client.log.index("subscribe")
        < client.log.index("navigate")
        < client.log.index("drain")
        < client.log.index("stop")
    )


def test_collect_falls_back_to_the_dom_when_the_interface_is_unrecognised():
    """接口结构变了 → 安静地退回 DOM，而不是失败或返回空。"""
    events = [
        _response_event("1", "https://www.zhipin.com" + SEARCH_MARKER),
        _body_event("1", {"完全不同的结构": []}),
    ]
    client = ScriptedClient(
        events=events,
        expressions={
            "rf:readiness": READY,
            "rf:collect": {"items": [{"title": "DOM 来的", "company": "某公司"}]},
        },
    )

    page = _adapter().collect_search(client, CollectQuery(keywords=["后端"]), 1)
    assert [item.title for item in page.results] == ["DOM 来的"]


def test_collect_reports_a_nonzero_boss_api_response_before_dom_fallback():
    events = [
        _response_event("1", "https://www.zhipin.com" + SEARCH_MARKER),
        _body_event("1", {"code": 19, "message": "参数值错误"}),
    ]
    client = ScriptedClient(
        events=events,
        expressions={
            "rf:readiness": READY,
            "rf:collect": {"items": [{"title": "不应采用的 DOM 结果"}]},
        },
    )

    with pytest.raises(SiteFailure, match="code=19.*参数值错误"):
        _adapter().collect_search(client, CollectQuery(keywords=["后端"]), 1)


def test_collect_falls_back_when_the_client_cannot_capture_events():
    """不支持事件订阅的客户端（例如别的浏览器桥接实现）照样能用。"""
    client = ScriptedClient(
        expressions={
            "rf:readiness": READY,
            "rf:collect": {"items": [{"title": "DOM 来的"}]},
        },
        supports_capture=False,
    )
    page = _adapter().collect_search(client, CollectQuery(keywords=["后端"]), 1)
    assert [item.title for item in page.results] == ["DOM 来的"]


def test_collect_still_reports_a_genuinely_empty_result():
    """明确无结果时返回空页是合法的，不该因为"没解析出东西"就退化成失败。"""
    client = ScriptedClient(
        expressions={"rf:readiness": {**READY, "matched": 0, "explicitly_empty": True}},
    )
    page = _adapter().collect_search(client, CollectQuery(keywords=["不存在的岗位"]), 1)
    assert page.results == []
    assert page.has_next is False


def test_detail_prefers_the_network_response():
    events = [
        _response_event(
            "1", "https://www.zhipin.com/wapi/zpgeek/job/detail.json?encryptJobId=abc"
        ),
        _body_event("1", _detail_payload()),
    ]
    client = ScriptedClient(
        events=events,
        expressions={
            "rf:readiness": {"url": "https://www.zhipin.com/job_detail/abc.html", "matched": 1},
            "rf:detail": {"job_title": "DOM 来的", "description": "DOM 描述"},
        },
    )

    detail = _adapter().fetch_job_detail(client, "https://www.zhipin.com/job_detail/abc.html")
    assert detail["job_title"] == "后端开发实习生"
    assert "负责接口开发" in detail["description"]
    assert detail["extra"]["hr_active_time"] == "今日活跃"


def test_detail_network_response_survives_a_stale_dom_selector():
    events = [
        _response_event(
            "1", "https://www.zhipin.com/wapi/zpgeek/job/detail.json?encryptJobId=abc"
        ),
        _body_event("1", _detail_payload()),
    ]
    target = "https://www.zhipin.com/job_detail/abc.html"
    client = ScriptedClient(
        events=events,
        expressions={
            "rf:readiness": {
                "url": target,
                "matched": 0,
                "ready_state": "complete",
                "explicitly_empty": False,
            }
        },
    )

    detail = _adapter().fetch_job_detail(client, target)

    assert detail["job_title"] == "后端开发实习生"
    assert "负责接口开发" in detail["description"]


def test_detail_falls_back_to_the_dom():
    events = [
        _response_event("1", "https://www.zhipin.com/wapi/zpgeek/job/detail.json"),
        _body_event("1", {"没有 jobInfo": True}),
    ]
    client = ScriptedClient(
        events=events,
        expressions={
            "rf:readiness": {"url": "https://www.zhipin.com/job_detail/abc.html", "matched": 1},
            "rf:detail": {"job_title": "DOM 来的", "description": "DOM 描述"},
        },
    )
    detail = _adapter().fetch_job_detail(client, "https://www.zhipin.com/job_detail/abc.html")
    assert detail["job_title"] == "DOM 来的"


def test_detail_keeps_the_caller_url_when_the_api_omits_it():
    """接口没给详情页地址时要用调用方传进来的那个，而不是留空。"""
    payload = _detail_payload()
    payload["zpData"]["jobInfo"].pop("encryptJobId")
    events = [
        _response_event("1", "https://www.zhipin.com/wapi/zpgeek/job/detail.json"),
        _body_event("1", payload),
    ]
    client = ScriptedClient(
        events=events,
        expressions={"rf:readiness": {"url": "x", "matched": 1}},
    )
    target = "https://www.zhipin.com/job_detail/abc.html"
    assert _adapter().fetch_job_detail(client, target)["url"] == target


def test_an_interface_failure_never_becomes_a_silent_empty_result():
    """选择器失效仍然是**一等的失败**——兜底不等于把问题咽下去。"""
    client = ScriptedClient(
        expressions={"rf:readiness": {"url": "x", "matched": 0, "explicitly_empty": False}},
    )
    with pytest.raises(SiteFailure) as excinfo:
        _adapter().collect_search(client, CollectQuery(keywords=["后端"]), 1)
    assert excinfo.value.category == FAILURE_SELECTOR_INVALID


# ===== 采集器那层包装不许把订阅吞掉 =====


def _stopped() -> None:
    raise TaskStopped()


def test_the_runner_wrapper_does_not_swallow_event_capture():
    """采集器把真实客户端包在 ``StopAwareCdpClient`` 里，那层包装必须转发事件订阅。

    否则 ``CdpClient`` 基类的"不支持"空实现会被当成"这个客户端不支持订阅"，网络优先
    这条路**在生产里永远退回 DOM，而离线测试全绿**——正是本文件开头说的那种失败。
    """
    events = [
        _response_event("1", "https://www.zhipin.com" + SEARCH_MARKER),
        _body_event("1", _search_payload()),
    ]
    inner = ScriptedClient(
        events=events,
        expressions={"rf:readiness": READY, "rf:collect": {"items": [{"title": "DOM 来的"}]}},
    )
    page = _adapter().collect_search(
        StopAwareCdpClient(inner, lambda: None), CollectQuery(keywords=["后端"]), 1
    )
    assert [item.title for item in page.results] == ["后端开发实习生"]


def test_the_wrapper_still_honours_stop_before_subscribing():
    """转发订阅不能把"停止"绕过去：订阅会真的发 CDP 命令，所以仍要插检查点。"""
    wrapped = StopAwareCdpClient(ScriptedClient(), _stopped)
    with pytest.raises(TaskStopped):
        wrapped.start_event_capture([NETWORK_RESPONSE_EVENT])


def test_a_stop_does_not_throw_away_events_already_captured():
    """取走已拦到的响应是纯本地操作。在这里抛"停止"会把到手的数据白扔掉，
    让采集白白退回字段更少的 DOM 结果。"""
    inner = ScriptedClient(events=[_response_event("1", "https://x")])
    inner.start_event_capture([NETWORK_RESPONSE_EVENT])
    inner.evaluate("rf:readiness")  # 页面跑了一会儿，响应进了缓冲区
    # 此刻用户点了停止：再发 CDP 命令会被守卫拦下，但"取走已到手的数据"不该被拦。
    wrapped = StopAwareCdpClient(inner, _stopped)
    assert len(wrapped.drain_events()) == 1


def test_the_fields_the_local_filters_read_are_the_ones_the_api_parser_produces():
    """把"本地筛选读哪些键"与"接口解析产出哪些键"接在一起钉住。

    这是最容易在真实使用里**悄悄失效**的一环：筛选逻辑自己有测试、解析函数也有测试，
    但两边用的键名对不上时，线上每个岗位都会落进"判断不了 → 原样保留"——筛选看起来在工作
    （有账目、有提示），实际一条都没筛掉。所以这条测试必须**跨两个模块**验证。
    """
    from app.services.apply.collect_filters import evaluate_filters

    payload = {
        "zpData": {
            "jobList": [
                {
                    "encryptJobId": "abc",
                    "jobName": "全栈工程师",
                    "brandName": "某某科技",
                    "cityName": "天津",
                    "lowSalary": 20000,
                    "highSalary": 30000,
                    "salaryMonth": 12,
                    "jobExperience": "3-5年",
                    "jobDegree": "本科",
                }
            ]
        }
    }

    parsed = parse_search_response(payload)

    assert parsed is not None
    extra = parsed[0]["extra"]
    # 我本科、3-5 年、期望 ≥20K —— 三条都满足，应当保留。
    assert evaluate_filters(
        education="本科", experience="3-5年", salary_min=20, extra=extra
    ).keep
    # 反向确认它真的**在判断**：我只要大专学历时，这个要求本科的岗位应当被筛掉。
    # 少了这一半，键名对不上时上面那句仍然会通过（全都因为"缺字段"而保留）。
    decision = evaluate_filters(education="大专", extra=extra)
    assert decision.keep is False
    assert decision.rejected_by == ("学历",)


# ===== 薪资文本解析（2026-09-20 真实验证发现的回归：接口只有 salaryDesc 文本，没有数字
# 字段——不解析文本的话，薪资筛选在真实数据下从不生效，低于期望下限的岗位全部漏进来）=====


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # 真实抓包里的三种写法。
        ("12-24K·14薪", (12000, 24000)),
        ("500-1000元/天", (500, 1000)),  # 日薪：数字如实返回，salary_band 会识别为"判断不了"
        ("200-250元/天", (200, 250)),
        ("12-24K", (12000, 24000)),
        ("1.5-2.5万", (15000, 25000)),
        # 单位的边界。
        ("2-3k", (2000, 3000)),
        ("10~20千", (10000, 20000)),
        # 读不出 → None（绝不编造）。
        ("面议", None),
        ("", None),
        ("8-15万/年", None),  # 年薪口径不与月薪比较
    ],
)
def test_parse_salary_text(text, expected):
    assert parse_salary_text(text) == expected


def test_search_response_parses_salary_from_desc_when_numeric_fields_missing():
    """真实接口只有 `salaryDesc` 文本：extra 的数字区间要从文本解析出来。"""
    payload = {
        "code": 0,
        "zpData": {
            "jobList": [
                {
                    "encryptJobId": "abc",
                    "jobName": "后端开发",
                    "brandName": "某某科技",
                    "salaryDesc": "12-24K·14薪",
                    "jobExperience": "3-5年",
                    "jobDegree": "本科",
                    "jobType": 0,
                },
                {
                    "encryptJobId": "def",
                    "jobName": "后端开发实习生",
                    "brandName": "某某科技",
                    "salaryDesc": "500-1000元/天",
                    "jobType": 4,
                },
            ]
        },
    }

    parsed = parse_search_response(payload)

    assert parsed is not None
    assert parsed[0]["extra"]["salary_low"] == 12000
    assert parsed[0]["extra"]["salary_high"] == 24000
    assert parsed[0]["extra"]["job_type_code"] == 0
    # 日薪岗位：数字如实带上（上层按"单位不同"处理），编码 4=实习。
    assert parsed[1]["extra"]["salary_low"] == 500
    assert parsed[1]["extra"]["salary_high"] == 1000
    assert parsed[1]["extra"]["job_type_code"] == 4


def test_numeric_salary_fields_still_win_over_text():
    """将来站点若恢复数字字段，数字优先、文本只是兜底。"""
    payload = {
        "code": 0,
        "zpData": {
            "jobList": [
                {
                    "encryptJobId": "abc",
                    "jobName": "后端开发",
                    "salaryDesc": "1-2K",
                    "lowSalary": 20000,
                    "highSalary": 30000,
                }
            ]
        },
    }

    parsed = parse_search_response(payload)

    assert parsed is not None
    assert parsed[0]["extra"]["salary_low"] == 20000
    assert parsed[0]["extra"]["salary_high"] == 30000
