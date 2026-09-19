"""QA 独立验证：「保存本次抓到的站点原文」的**运行器级接线**与隐私底线。

为什么要单独一个文件：``test_sample_recorder.py`` 验的是装饰器本身能否配对落盘，
``test_apply_queue_and_api.py`` / ``test_collect_backfill.py`` 验的是 config/API 形状，
但**功能真正接线的地方**——``task_runner._run_collect`` 里"读到开关 → 按适配器声明的 markers
安装装饰器 → 跑采集 → 四条终态路径都写账目"——**没有运行器级用例**（工程师自述的缺口）。
这段接线错了单测都不会红：装饰器装错位置、开关读反、markers 取错，生产里只会表现为
"样例永远为空"或"关了还写盘"，而且**都不报错**。这里用仓库已有的 runner 台架把它钉住，
并把三条隐私底线（只存 path、不落凭据、只写 captures）在**真实接线路径**上再验一遍。

隐私底线是本功能最该保守的部分：样例会被拿去建"真实样例回归"，一旦把 query 里的令牌
或请求头落盘，就有可能被当成夹具提交进仓库。所以下面凡是落盘断言，都对着文件**内容**验。
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import pytest

from app.config import captures_dir
from app.models.apply import ApplyTask
from app.schemas.apply import ApplyConfigIn, CollectConfigIn
from app.services.apply import apply_service
from app.services.apply.task_runner import TaskRunner, TaskStopped, _is_within
from app.services.browser.cdp_client import CdpClient, CdpError
from app.services.browser.sample_recorder import (
    MAX_TRACKED_REQUESTS,
    SampleRecordingCdpClient,
)
from app.services.sites.base import (
    ApplyOutcome,
    CollectQuery,
    RiskProfile,
    SearchPage,
    SiteAdapter,
    SiteFailure,
)
from app.services.sites.registry import SiteRegistry

# 复用装饰器单测里的假内层与构造器，避免"同一份夹具两处各写一遍"。
from test_sample_recorder import (
    MARKERS,
    _body_result,
    _FakeInner,
    _recorder,
    _response_event,
    _saved_files,
)

# query 里放一个"像令牌的串"：它绝不允许出现在落盘文件里。
SECRET = "SECRET123"
SEARCH_URL = f"https://www.zhipin.com/wapi/zpgeek/search/joblist.json?token={SECRET}&jobId=abc"


class _FakeClock:
    """每次读表都大步前进，让岗位间限速立即结束（离线测试不真等）。"""

    def __init__(self) -> None:
        self._t = 0.0

    def __call__(self) -> float:
        self._t += 100.0
        return self._t


class _NetworkFakeCdp(CdpClient):
    """能推送一次 ``Network.responseReceived`` 且能应答 ``Network.getResponseBody`` 的假客户端。

    生产里 URL 先到、body 后取，录制器靠 ``requestId`` 配对——这里还原同一时序，才能让
    "运行器把装饰器接在真实取体路径上"这件事被真正走一遍。``request_id`` 必须与适配器取体时
    用的一致，否则配对失败（这正是要防的静默失败）。
    """

    def __init__(self, url: str, body_payload, *, request_id: str = "req-1") -> None:
        self._url = url
        self._body = json.dumps(body_payload, ensure_ascii=False)
        self._request_id = request_id
        self.capture_methods: list[str] = []
        self.closed = False

    def start_event_capture(self, methods) -> None:
        self.capture_methods = list(methods)

    def stop_event_capture(self) -> None:
        self.capture_methods = []

    def drain_events(self):
        # 订阅停了就收不到响应——与真实客户端一致（写错取走/停止顺序就会被这条测出来）。
        if not self.capture_methods:
            return []
        return [_response_event(self._request_id, self._url)]

    def send(self, method, params=None, *, timeout=None):
        if method == "Network.getResponseBody" and isinstance(params, dict):
            if str(params.get("requestId")) == self._request_id:
                return {"body": self._body, "base64Encoded": False}
        return {}

    def list_targets(self):
        return []

    def new_tab(self, url: str = "about:blank") -> str:
        return "t"

    def evaluate(self, expression, *, timeout=None):
        return None

    def navigate(self, url, *, timeout=None):
        return {}

    def set_file_input(self, selector, files, *, timeout=None):
        return None

    def close(self) -> None:
        self.closed = True


class _RecordingAdapter(SiteAdapter):
    """采集适配器：先驱动一次"URL→body"时序（让录制器存下一份），再返回结果或抛异常。

    ``after`` 用来模拟四条终态：成功（None）、``SiteFailure``、``CdpError``、``TaskStopped``。
    """

    key = "boss"
    display_name = "示例采集站"
    hosts = ("zhipin.com",)
    sample_markers = (("search", ("joblist",)),)

    def __init__(
        self,
        *,
        url: str,
        body_payload=None,
        page: SearchPage | None = None,
        after: BaseException | None = None,
        markers=None,
    ) -> None:
        self._url = url
        self._body = body_payload if body_payload is not None else {"zpData": {"jobList": []}}
        self._page = page or SearchPage(results=[], has_next=False)
        self._after = after
        if markers is not None:
            # 站点知识只由适配器声明；``sample_markers=()`` 表示该站点不支持保存原文。
            self.sample_markers = markers

    def matches(self, url_or_source: str) -> bool:
        return True

    def risk_profile(self) -> RiskProfile:
        return RiskProfile(key=self.key)

    def collect_search(self, client, query: CollectQuery, page: int) -> SearchPage:
        client.start_event_capture(["Network.responseReceived"])
        client.drain_events()  # URL 先到，录制器据此记住 requestId → url
        client.send("Network.getResponseBody", {"requestId": "req-1"})  # body 后取，配对落盘
        client.stop_event_capture()
        if self._after is not None:
            raise self._after
        return self._page

    def open_apply(self, client, job):  # pragma: no cover - 采集不用
        raise AssertionError("采集不应触发投递")

    def fill_and_submit(self, client, data, greeting) -> ApplyOutcome:  # pragma: no cover
        raise AssertionError("采集不应触发投递")


def _registry(*adapters: SiteAdapter) -> SiteRegistry:
    registry = SiteRegistry()
    for adapter in adapters:
        registry.register(adapter)
    return registry


def _collect_task(db_session, *, save_site_samples: bool | None = None) -> ApplyTask:
    """一个采集任务；``save_site_samples`` 为 None 时**不带该键**（保持旧任务的 config 形状）。"""
    config = CollectConfigIn(keywords=["后端"], per_task_limit=20).model_dump()
    if save_site_samples is not None:
        config["save_site_samples"] = save_site_samples
    task = ApplyTask(kind="collect", status="pending", total=20, config=config)
    db_session.add(task)
    db_session.commit()
    return task


def _runner(adapter: SiteAdapter, client_factory) -> TaskRunner:
    return TaskRunner(
        registry=_registry(adapter),
        client_factory=client_factory,
        sleeper=lambda _seconds: None,
        clock=_FakeClock(),
        poll_interval=0.01,
    )


def _wait(runner: TaskRunner, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while runner.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)


def _patch_captures(monkeypatch, target: Path) -> None:
    """把运行器解析的样例目录改到临时目录。

    ``_run_collect`` 里是 ``from ...config import captures_dir`` 的**按名导入**，所以必须
    patch 它所在模块的属性；否则测试会把真实 ``backend/data/captures`` 写脏。
    """
    monkeypatch.setattr("app.services.apply.task_runner.captures_dir", lambda: target)


def _saved_json_files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.json")) if directory.exists() else []


# ===== 一、隐私底线（在真实接线路径上验）=====


def test_flag_on_records_a_sample_that_keeps_only_the_path(db_session, tmp_path, monkeypatch):
    """底线 1「URL 只存 path」+ 底线 3「只写 captures 目录」，走完整运行器路径。

    这是"带 query 的 URL 不会把令牌写进文件"的运行器级证据：适配器驱动真实取体时序 →
    运行器安装装饰器 → 落盘。断言落在**文件内容**上，而不是只断言目录存在。
    """
    target = tmp_path / "captures"
    _patch_captures(monkeypatch, target)
    real_captures = captures_dir()  # 真实仓库路径，用来确认本次没有写它
    existed_before = real_captures.exists()

    created: list[_NetworkFakeCdp] = []

    def factory(_config):
        client = _NetworkFakeCdp(SEARCH_URL, {"zpData": {"jobList": [{"jobName": "后端"}]}})
        created.append(client)
        return client

    task = _collect_task(db_session, save_site_samples=True)
    runner = _runner(_RecordingAdapter(url=SEARCH_URL), factory)

    runner.start(task.id)
    _wait(runner)

    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    assert stored.status == "completed"

    # 账目写进了 task.config：份数 + 目录，用户据此知道去哪儿拿。
    assert stored.config["saved_samples"] == 1
    samples_dir = Path(stored.config["samples_dir"])
    assert samples_dir == target / "boss"

    files = _saved_json_files(target)
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    payload = json.loads(text)

    # 底线 1：只留 path，query / fragment / 令牌一律不落盘。
    assert payload["url_path"] == "/wapi/zpgeek/search/joblist.json"
    assert SECRET not in text
    assert "?" not in text and "&" not in text and "#" not in text
    assert payload["body"]["zpData"]["jobList"] == [{"jobName": "后端"}]

    # 底线 3：只写 captures 目录，绝不碰真实仓库数据目录 / 数据集 / 浏览器登录态。
    assert real_captures.exists() == existed_before
    assert target in samples_dir.parents
    from app.dataset_registry import datasets_directory
    from app.services.browser.browser_manager import default_profile_dir

    assert samples_dir != datasets_directory()
    assert datasets_directory() not in samples_dir.parents
    assert default_profile_dir() not in samples_dir.parents


def test_recorded_sample_has_exactly_the_three_safe_fields(db_session, tmp_path, monkeypatch):
    """底线 2「不落任何凭据」：落盘 JSON 的字段**只有** url_path / captured_at / body。

    用"集合相等"而不是"包含"，才能挡住将来有人顺手把 headers / cookies / request_body
    塞进同一份 payload——那样的夹具一旦进仓库就是把凭据带出去了。
    """
    target = tmp_path / "captures"
    _patch_captures(monkeypatch, target)
    task = _collect_task(db_session, save_site_samples=True)
    runner = _runner(_RecordingAdapter(url=SEARCH_URL), lambda _c: _NetworkFakeCdp(SEARCH_URL, {"ok": 1}))

    runner.start(task.id)
    _wait(runner)

    payload = json.loads(_saved_json_files(target)[0].read_text(encoding="utf-8"))
    assert set(payload) == {"url_path", "captured_at", "body"}


def test_flag_off_writes_nothing_and_never_even_resolves_the_directory(
    db_session, tmp_path, monkeypatch
):
    """默认关闭：开关为假 → **连 captures_dir() 都不调用**、不建目录、不落盘、不写账目。

    把 ``captures_dir`` 换成记账的探针：只要被调用一次就记下，能区分"调用了但没写"与
    "根本没走到"。这是"绝不默默记录"这条底线在运行器层的直接证据。
    """
    calls: list[int] = []

    def spy():
        calls.append(1)
        return tmp_path / "captures"

    monkeypatch.setattr("app.services.apply.task_runner.captures_dir", spy)
    task = _collect_task(db_session)  # 不带 save_site_samples
    runner = _runner(_RecordingAdapter(url=SEARCH_URL), lambda _c: _NetworkFakeCdp(SEARCH_URL, {"ok": 1}))

    runner.start(task.id)
    _wait(runner)

    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    assert stored.status == "completed"
    assert calls == []  # 开关为假时连目录都不解析
    assert not (tmp_path / "captures").exists()
    assert "saved_samples" not in stored.config
    assert "samples_dir" not in stored.config


def test_adapter_without_markers_writes_nothing_even_when_flag_is_on(
    db_session, tmp_path, monkeypatch
):
    """适配器没声明 ``sample_markers``（默认空）时，即使开了开关也一个文件都不写、不建目录。

    这条守住"站点知识只属于适配器层"：装饰器不认识任何站点，适配器不声明就不录。
    """
    calls: list[int] = []
    monkeypatch.setattr(
        "app.services.apply.task_runner.captures_dir",
        lambda: (calls.append(1), tmp_path / "captures")[1],
    )
    adapter = _RecordingAdapter(url=SEARCH_URL, markers=())
    task = _collect_task(db_session, save_site_samples=True)
    runner = _runner(adapter, lambda _c: _NetworkFakeCdp(SEARCH_URL, {"ok": 1}))

    runner.start(task.id)
    _wait(runner)

    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    assert stored.status == "completed"
    assert calls == []
    assert not (tmp_path / "captures").exists()
    assert "saved_samples" not in stored.config


def test_a_malicious_site_key_cannot_write_samples_outside_captures(
    db_session, tmp_path, monkeypatch
):
    """回归（缺陷修复）：配置里的 ``site_key`` 是**用户输入**，曾被直接拿去拼样例目录，
    能把样例写到 ``captures/`` 之外——例如 ``../browser-profile``（投递浏览器的登录态目录），
    破坏"只写 captures"这条底线。

    修法：目录改用**已解析适配器**的 ``key``（代码常量，如 ``boss``），用户输入不再进入文件路径；
    并在拼完后加一条 ``captures`` 之内检查（越界就不保存、只记日志）。

    这条测试对"改回用 site_key"**有牙**：样本必须落在 ``captures/<adapter.key>``；而且整个
    临时目录下、``captures`` 之外不得出现任何样例文件。把实现改回用 site_key，第一个断言
    （样本落在 ``captures/boss``）立刻变红。
    """
    target = tmp_path / "captures"
    _patch_captures(monkeypatch, target)

    # 配置里塞一个会"往上跳"的 site_key——它不在注册表里，_collect_adapter 会回退到 adapters[0]。
    apply_service.save_apply_config(db_session, ApplyConfigIn(site_key="../browser-profile"))

    task = _collect_task(db_session, save_site_samples=True)
    runner = _runner(
        _RecordingAdapter(url=SEARCH_URL),
        lambda _c: _NetworkFakeCdp(SEARCH_URL, {"ok": 1}),
    )

    runner.start(task.id)
    _wait(runner)

    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    assert stored.status == "completed"

    # 样本落在 captures/<adapter.key>（boss），而不是那个畸形 site_key 指向的地方。
    assert Path(stored.config["samples_dir"]) == target / "boss"
    assert len(_saved_json_files(target / "boss")) == 1

    # captures 之外（含 ../browser-profile）不得出现任何样例文件。
    assert _saved_json_files(tmp_path / "browser-profile") == []
    # 整个临时目录下的 json 与 captures 下的 json 完全一致 → 没有任何文件逃出 captures。
    assert _saved_json_files(target.parent) == _saved_json_files(target)


# ===== 二、四条终态路径都要写账目，且已捕获的样例照样保留 =====

@pytest.mark.parametrize(
    ("after", "expected_status", "expected_reason"),
    [
        (None, "completed", "done"),  # 成功
        (SiteFailure("selector_invalid", "页面结构可能已变化"), "failed", "error"),  # 站点失败
        (CdpError("调试通道断开"), "failed", "error"),  # CDP 错误
        (TaskStopped(), "stopped", "user"),  # 用户停止
    ],
)
def test_every_terminal_path_records_count_and_directory(
    db_session, tmp_path, monkeypatch, after, expected_status, expected_reason
):
    """成功 / SiteFailure / CdpError / TaskStopped 四条终态都必须写"存了几份、在哪"。

    用户点了停止或采集失败后，同样想知道样例存哪了；不写账目等于把已经存下来的样例藏起来。
    这里让适配器**先存下一份再抛异常**，验证四条路径都记账，且样例文件真的还在。
    """
    target = tmp_path / "captures"
    _patch_captures(monkeypatch, target)
    task = _collect_task(db_session, save_site_samples=True)
    runner = _runner(
        _RecordingAdapter(url=SEARCH_URL, after=after),
        lambda _c: _NetworkFakeCdp(SEARCH_URL, {"ok": 1}),
    )

    runner.start(task.id)
    _wait(runner)

    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    assert stored.status == expected_status
    assert stored.stop_reason == expected_reason
    # 已捕获的样例照样保留，且账目里能读到份数与目录。
    assert stored.config["saved_samples"] == 1
    assert Path(stored.config["samples_dir"]) == target / "boss"
    assert len(_saved_json_files(target)) == 1


def test_main_flow_still_completes_when_recording_fails_to_decode(
    db_session, tmp_path, monkeypatch
):
    """解码失败 / 非 JSON 只是跳过这一条，**绝不影响主采集流程**（任务仍应完成）。"""
    target = tmp_path / "captures"
    _patch_captures(monkeypatch, target)

    class _HtmlBodyCdp(_NetworkFakeCdp):
        def send(self, method, params=None, *, timeout=None):
            if method == "Network.getResponseBody":
                return {"body": "<html>验证码页</html>", "base64Encoded": False}
            return {}

    task = _collect_task(db_session, save_site_samples=True)
    runner = _runner(_RecordingAdapter(url=SEARCH_URL), lambda _c: _HtmlBodyCdp(SEARCH_URL, {}))

    runner.start(task.id)
    _wait(runner)

    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    assert stored.status == "completed"
    assert stored.config["saved_samples"] == 0
    assert _saved_json_files(target) == []


# ===== 三、装饰器对主流程完全透明（这里出错会直接把采集弄坏）=====


def test_decorator_returns_are_identical_with_and_without_wrapping(tmp_path):
    """包一层之后 ``drain_events`` / ``send`` / ``evaluate`` / ``navigate`` / ``list_targets``
    的返回值与不包时**完全一致**。

    适配器是照着"没用装饰器"写的：只要某一个转发方法把返回值改了（漏 return、返回 None），
    适配器就会拿不到响应体而**静默退回 DOM**，采集表面成功、实际走了慢且脆的兜底路径。
    这里用"同样的内层建两份：一份裸用、一份包着"，逐方法比对返回值。
    """

    def build() -> _FakeInner:
        return _FakeInner(
            events=[_response_event("1", "https://x/wapi/zpgeek/search/joblist.json")],
            bodies={"1": _body_result({"k": 1})},
        )

    raw = build()
    wrapped = SampleRecordingCdpClient(
        build(), markers=MARKERS, directory=tmp_path / "captures" / "boss"
    )

    assert wrapped.drain_events() == raw.drain_events()
    assert wrapped.evaluate("rf:probe") == raw.evaluate("rf:probe")
    assert wrapped.navigate("https://x/next") == raw.navigate("https://x/next")
    assert wrapped.list_targets() == raw.list_targets()
    assert wrapped.new_tab("https://x") == raw.new_tab("https://x")
    assert wrapped.send("Page.enable") == raw.send("Page.enable")
    assert wrapped.send("Network.getResponseBody", {"requestId": "1"}) == raw.send(
        "Network.getResponseBody", {"requestId": "1"}
    )


# ===== 四、配对不受 500 上限影响 + 落盘文件都是合法 JSON =====


def test_a_realistic_batch_under_the_tracking_limit_pairs_everything(tmp_path):
    """长跑里 URL 成批到达、body 随后成批取：只要一批不超过 500，配对就一条都不丢。

    ``requestId → url`` 映射超限才丢最旧。这里 200 条（< 500）先全部到达再全部取体，
    应对**全部配对成功**——若丢最旧导致配对失败，样本会静默少存，这正是本功能最怕的失败。
    同时断言**每一份落盘文件都是合法 JSON**（夹具一旦解析不了就是废的）。
    """
    count = 200
    assert count < MAX_TRACKED_REQUESTS
    events = [
        _response_event(str(i), f"https://x/wapi/zpgeek/search/joblist.json?page={i}")
        for i in range(count)
    ]
    bodies = {str(i): _body_result({"n": i}) for i in range(count)}
    recorder = _recorder(tmp_path, _FakeInner(events=events, bodies=bodies), max_samples=count)

    recorder.drain_events()  # 一大批 URL 先到
    for i in range(count):  # body 随后成批取
        recorder.send("Network.getResponseBody", {"requestId": str(i)})

    files = _saved_files(tmp_path)
    assert len(files) == count
    assert recorder.saved_count == count
    for path in files:
        json.loads(path.read_text(encoding="utf-8"))  # 每一份都能解析


def test_oversized_sample_is_skipped_whole_never_a_truncated_file(tmp_path, caplog):
    """超 2MB 的样例是**整份跳过**（记一条 warning），绝不写出半截 JSON。

    若实现是"把序列化后的 JSON 截断"，文件会解析不了、对夹具就是废的。这里断言：
    先存一份正常样例、再来一份超大样例 → 超大那份不产生任何文件，已存的那份仍然合法可解析。
    """
    import logging

    big = _body_result("ok")
    huge = json.dumps({"blob": "x" * 5000}, ensure_ascii=False)
    inner = _FakeInner(
        events=[
            _response_event("1", "https://x/wapi/zpgeek/search/joblist.json?page=1"),
            _response_event("2", "https://x/wapi/zpgeek/search/joblist.json?page=2"),
        ],
        bodies={"1": big, "2": {"body": huge, "base64Encoded": False}},
    )
    recorder = _recorder(tmp_path, inner, max_bytes=512)

    with caplog.at_level(logging.WARNING):
        recorder.drain_events()
        recorder.send("Network.getResponseBody", {"requestId": "1"})  # 正常，落盘
        recorder.send("Network.getResponseBody", {"requestId": "2"})  # 超大，跳过

    files = _saved_files(tmp_path)
    assert recorder.saved_count == 1
    assert len(files) == 1  # 超大那份没有产出（尤其是没有产出半截文件）
    json.loads(files[0].read_text(encoding="utf-8"))  # 已落盘那份仍合法
    assert any("单份上限" in record.message for record in caplog.records)


# ===== 五、畸形 URL / fragment 不让采集报错 =====


def test_malformed_url_does_not_raise_and_drops_the_path(tmp_path):
    """畸形 URL（``urlsplit`` 抛 ``ValueError``）绝不能让采集报错；path 取不到就留空。

    站点偶尔会发出畸形地址；录制器是**旁路观察者**，它出错会顺着装饰器把异常带进主流程，
    所以这里必须钉住"宁留空、不抛异常"。
    """
    malformed = "http://[::1/wapi/zpgeek/search/joblist.json"  # 未闭合 IPv6 → urlsplit 抛 ValueError
    inner = _FakeInner(
        events=[_response_event("1", malformed)],
        bodies={"1": _body_result({"k": 1})},
    )
    recorder = _recorder(tmp_path, inner)

    recorder.drain_events()
    recorder.send("Network.getResponseBody", {"requestId": "1"})  # 不抛异常

    payload = json.loads(_saved_files(tmp_path)[0].read_text(encoding="utf-8"))
    assert payload["url_path"] == ""  # 取不到 path 就留空


def test_fragment_only_url_keeps_the_path_and_strips_the_fragment(tmp_path):
    """带 fragment 的 URL：只留 path，fragment 不落盘。"""
    inner = _FakeInner(
        events=[_response_event("1", "https://x/wapi/zpgeek/search/joblist.json#section-3")],
        bodies={"1": _body_result({"k": 1})},
    )
    recorder = _recorder(tmp_path, inner)

    recorder.drain_events()
    recorder.send("Network.getResponseBody", {"requestId": "1"})

    text = _saved_files(tmp_path)[0].read_text(encoding="utf-8")
    payload = json.loads(text)
    assert payload["url_path"] == "/wapi/zpgeek/search/joblist.json"
    assert "#" not in text


# ===== 六、API 形状核实（未知字段必须 422，不是把脏数据当 500 吞掉）=====


def test_collect_task_rejects_unknown_body_fields_with_422(client):
    """``POST /collect/tasks`` 的请求体是 ``extra="forbid"``：传未知字段要给 422，
    而不是带着未知字段继续跑（更不是 500）。这保证"每次采集显式勾选"是一个封闭的输入面，
    不会因为前端多传了个字段就静默改变行为。"""
    client.put("/api/collect/config", json={"keywords": ["后端"], "city": "北京"})

    response = client.post("/api/collect/tasks", json={"unknown_field": True})

    assert response.status_code == 422


# ===== 七、第二道防线 _is_within 的边界（B 的牙齿）=====
#
# 背景：修复把「只用已解析适配器的 key 拼目录」（A）与「拼完再检查是否在 captures 之内」
# （B）做成两道防线。C（恶意 site_key 回归）只钉住了 A——A 正确时，即使把 B 整段删掉，
# C 的断言（样本落在 captures/boss、captures 外无 json）**依然全绿**，因为目录本就落在
# captures 内。所以这里单独为 B 补一组用例：直测函数契约 + 一条会让 join 结果越界的
# runner 级用例，让"越界即拒写"这条性质单独也有牙。


def _make_escaping_link(link: Path, target: Path) -> bool:
    """在 ``link`` 处建一个指向外部 ``target`` 的链接，返回是否**真的**建成且会被 resolve() 跟随。

    两条经验决定了这个 helper 必须"回读核实"、而不是"没抛异常就当成功"：

    - 有些环境（含本机沙箱）``os.symlink`` 会**静默失败**：不抛异常、但链接根本没建出来；
    - Windows 上无符号链接权限时 ``os.symlink`` 也会失败，此时退回**目录联接**（junction，
      不需要特权）——对 ``_is_within`` 而言二者等价，因为它只看 ``resolve()`` 是否跳出 root。

    统一用"``resolve()`` 是否真的跳到 ``target``"作为成功判据；建不成就返回 False，由调用方
    跳过，绝不伪造绿灯。
    """
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pass
    if link.exists() and link.resolve() == target.resolve():
        return True
    if os.name == "nt":
        import subprocess

        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    try:
        return link.exists() and link.resolve() == target.resolve()
    except OSError:
        return False


def test_is_within_rejects_sibling_directory_sharing_a_prefix(tmp_path):
    """兄弟目录同前缀（``captures-evil``）必须判为「不在之内」。

    这是手写"是不是在里面"检查最经典的错误：``str(path).startswith(str(root))`` 对
    ``<root>-evil`` 返回 True（字符串前缀相同），于是把样例写进一个只是"名字像 captures"
    的目录。这里断言为 False，并同时钉住"字符串法会误判"，说明为什么必须用 resolve()。
    """
    root = tmp_path / "captures"
    root.mkdir()
    sibling = tmp_path / "captures-evil"

    assert str(sibling).startswith(str(root))  # 朴素的 startswith 会误判为"在内"
    assert _is_within(sibling, root) is False  # 正确实现必须判为"不在内"

    # 反向确认：真正的子目录仍是 True（挡住"一律返回 False"这种假修复）。
    assert _is_within(root / "boss", root) is True


def test_is_within_accepts_the_root_itself_without_raising(tmp_path):
    """``path == root`` 时行为必须明确且**不抛异常**：这里钉住返回 True（root 在自身之内）。"""
    root = tmp_path / "captures"
    root.mkdir()

    assert _is_within(root, root) is True


def test_is_within_normalises_dotdot(tmp_path):
    """含 ``..`` 的路径按 resolve() 归一化后再判断：回到内部算内、跳到外部算外。"""
    root = tmp_path / "captures"
    (root / "boss").mkdir(parents=True)

    assert _is_within(root / "boss" / ".." / "boss", root) is True
    assert _is_within(root / ".." / "outside", root) is False


def test_is_within_works_even_when_paths_do_not_exist(tmp_path):
    """目标 / 根都还不存在时也要能用（``resolve`` 非严格模式），不能因为不存在就崩。"""
    root = tmp_path / "captures"  # 故意不创建

    assert _is_within(root / "boss", root) is True
    assert _is_within(tmp_path / "elsewhere", root) is False


def test_is_within_returns_false_when_resolve_raises_oserror(monkeypatch):
    """``resolve()`` 抛 ``OSError`` 时必须返回 False，绝不向上传播。

    落盘是旁路能力：一个解析失败的路径不该把整次采集弄坏。这里让 ``Path.resolve`` 直接
    抛错，断言函数吞掉异常并返回 False。
    """

    def boom(self, *args, **kwargs):
        raise OSError("模拟 resolve 失败")

    monkeypatch.setattr(Path, "resolve", boom, raising=True)

    assert _is_within(Path("a/b"), Path("a")) is False


def test_is_within_follows_a_symlink_that_escapes_captures(tmp_path):
    """软链接逃逸：captures 内一个指向外部的软链接，保存路径经过它 → 必须判为「不在之内」。

    这正是用 ``resolve()`` 而不是字符串比较的理由：字符串看 ``captures/evil`` 明明是
    ``captures`` 的子路径（下面显式断言了这点），但 ``resolve()`` 会跟随链接、发现它其实
    指向外部。符号链接建不出来时退回目录联接；两者都建不出才跳过——不伪造绿灯。
    """
    root = tmp_path / "captures"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "evil"

    if not _make_escaping_link(link, outside):
        pytest.skip("本环境既建不出符号链接也建不出目录联接，跳过链接逃逸用例")

    assert str(link).startswith(str(root))  # 字符串法会误判为"在内"
    assert _is_within(link, root) is False  # resolve() 跟随链接 → 正确判为"不在内"


@pytest.mark.skipif(os.name != "nt", reason="大小写/反斜杠等价只在 Windows 文件系统上有意义")
def test_is_within_windows_case_and_separator_forms(tmp_path):
    """Windows 大小写不敏感、``\\`` 与 ``/`` 等价：这些形态不应误判。

    ``Captures`` 与 ``captures`` 在 Windows 上指向同一目录，必须算"在内"；
    ``captures\\boss\\..\\boss`` 归一化后仍在本目录之内，也不算越界。
    """
    root = tmp_path / "captures"
    (root / "boss").mkdir(parents=True)

    assert _is_within(tmp_path / "Captures" / "boss", root) is True
    assert _is_within(tmp_path / Path("captures\\boss\\..\\boss"), root) is True
    assert _is_within(tmp_path / Path("captures-evil"), root) is False


# ===== 八、B 的 runner 级牙齿：join 结果越界 → 拒写、任务照常完成 =====


class _EscapingKeyAdapter(_RecordingAdapter):
    """``key`` 含 ``..``：模拟"join 出来的目录落到 captures 之外"这一 B 要挡住的场景。

    ``adapter.key`` 本是代码常量；这里刻意让它越界，用来**单独**验证第二道防线——即使
    A 的拼法本身产出了越界目录，B 也必须拦住落盘。把 B 整段删掉、A 保持不变时，本用例会红
    （样例会写进 captures 之外）。
    """

    key = "../escaped"


def test_guard_blocks_an_escaping_target_dir_and_keeps_the_task_healthy(
    db_session, tmp_path, monkeypatch, caplog
):
    """B（``_is_within`` 检查）**单独**也有牙。

    构造一个 key 含 ``..`` 的适配器，让 ``captures_root / adapter.key`` 落到 captures 之外：
    - 有 B → 不安装装饰器、不写任何文件、只记一条 warning，采集照常 ``completed``；
    - 删掉 B（A 不变）→ 样例会写进 captures 之外 → 下面的 ``_saved_json_files(tmp_path) == []``
      与 ``"saved_samples" not in ...`` 立刻变红。

    这样 A、B 两道防线各有各的用例钉住，消除"C 只测到 A、B 被删了也不红"的盲区。
    """
    target = tmp_path / "captures"
    _patch_captures(monkeypatch, target)
    task = _collect_task(db_session, save_site_samples=True)
    # 注册表里只放这个 key 越界的适配器 → _collect_adapter 无论站点配置如何都会选中它。
    runner = _runner(
        _EscapingKeyAdapter(url=SEARCH_URL),
        lambda _c: _NetworkFakeCdp(SEARCH_URL, {"ok": 1}),
    )

    with caplog.at_level(logging.WARNING):
        runner.start(task.id)
        _wait(runner)

    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)

    # 越界只跳过保存，绝不影响采集本身：任务正常完成。
    assert stored.status == "completed"
    # recorder 未被安装 → 不写账目（与"关掉开关就不留痕迹"一致）。
    assert "saved_samples" not in stored.config
    # 关键断言：captures 之内、之外都不得出现任何样例 json。
    assert _saved_json_files(target) == []
    assert _saved_json_files(tmp_path) == []
    # 且必须留下可检索的 warning（不是静默丢弃）。
    assert any("不在 captures 之内" in record.message for record in caplog.records)


def test_backslash_traversal_site_key_cannot_write_outside_captures(
    db_session, tmp_path, monkeypatch
):
    """独立复现（B 侧的第二形态）：``site_key`` 用 **Windows 反斜杠**写法做上跳，同样写不出去。

    与 C 互补：C 用的是 ``../browser-profile``（正斜杠），这里用 ``..\\..\\browser-profile``，
    覆盖"用户输入在 Windows 上以反斜杠表达穿越"这一形态。断言口径与 C 相同——样本只落在
    ``captures/<adapter.key>``，captures 之外一份都没有。
    """
    target = tmp_path / "captures"
    _patch_captures(monkeypatch, target)
    apply_service.save_apply_config(db_session, ApplyConfigIn(site_key="..\\..\\browser-profile"))

    task = _collect_task(db_session, save_site_samples=True)
    runner = _runner(
        _RecordingAdapter(url=SEARCH_URL),
        lambda _c: _NetworkFakeCdp(SEARCH_URL, {"ok": 1}),
    )

    runner.start(task.id)
    _wait(runner)

    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    assert stored.status == "completed"
    assert Path(stored.config["samples_dir"]) == target / "boss"
    assert len(_saved_json_files(target / "boss")) == 1
    # captures 之外（这个畸形 site_key 指向的落点）一份都没有。
    assert _saved_json_files(tmp_path / "browser-profile") == []
    assert _saved_json_files(target.parent) == _saved_json_files(target)
