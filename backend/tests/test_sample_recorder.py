"""站点原文录制装饰器（``SampleRecordingCdpClient``）与它的接线，全部离线。

为什么单独、认真地测：这块的失败方式都是**静默**的——url/body 配错、把 query 里的令牌一起
落盘、上限没生效导致磁盘被塞满、开关为假却建了目录，**都不会报错**，只会在某天"拿样例去回归"
时才发现样例是错的（或更糟：把凭据当成样例提交进了仓库）。所以逐条钉住：配对、path 取舍、
上限与日志、非 JSON 不影响主流程、关闭时一个文件都不写。

用假的"内层客户端"，不连浏览器、不写真实 ``backend/data/``（一律写进 ``tmp_path``）。
"""
from __future__ import annotations

import base64
import json
import logging

from app.services.browser.sample_recorder import (
    SampleRecordingCdpClient,
)

# 站点知识（markers）由适配器层声明；这里照抄一份最小集合，验证装饰器只认调用方给的东西。
MARKERS = (("search", ("joblist",)), ("detail", ("/job/detail",)))


class _FakeInner:
    """最小内层客户端：实现录制器会转发到的方法，并记录被代理的调用。"""

    def __init__(self, *, events=None, bodies=None):
        self._pending = list(events or [])
        self._bodies = dict(bodies or {})
        self.sent: list[tuple[str, dict | None]] = []
        self.capture_started: list[str] | None = None
        self.capture_stopped = False
        self.closed = False

    def drain_events(self):
        events, self._pending = self._pending, []
        return events

    def send(self, method, params=None, **_kwargs):
        self.sent.append((method, params))
        if method == "Network.getResponseBody" and isinstance(params, dict):
            return dict(self._bodies.get(str(params.get("requestId")), {}))
        return {}

    def list_targets(self):
        return []

    def new_tab(self, url="about:blank"):
        return "t"

    def evaluate(self, expression, **_kwargs):
        return None

    def navigate(self, url, **_kwargs):
        return {}

    def start_event_capture(self, methods):
        self.capture_started = list(methods)

    def stop_event_capture(self):
        self.capture_stopped = True

    def set_file_input(self, selector, files, **_kwargs):
        return None

    def close(self):
        self.closed = True


def _response_event(request_id: str, url: str) -> dict:
    return {
        "method": "Network.responseReceived",
        "params": {"requestId": request_id, "response": {"url": url}},
    }


def _body_result(payload, *, base64_encoded: bool = False) -> dict:
    raw = json.dumps(payload, ensure_ascii=False)
    if base64_encoded:
        raw = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    return {"body": raw, "base64Encoded": base64_encoded}


def _recorder(tmp_path, inner, **kwargs) -> SampleRecordingCdpClient:
    return SampleRecordingCdpClient(
        inner,
        markers=MARKERS,
        directory=tmp_path / "captures" / "boss",
        **kwargs,
    )


def _saved_files(tmp_path):
    directory = tmp_path / "captures" / "boss"
    return sorted(directory.glob("*.json")) if directory.exists() else []


# ===== 配对与落盘形状 =====


def test_pairs_url_and_body_and_keeps_only_the_path(tmp_path):
    """URL 先出现、响应体后取，靠 requestId 配对；落盘只留 path、丢掉 query。

    query 里可能有站点内部参数甚至令牌，而夹具只需要 path（判断接口用的就是 path 上的 markers），
    所以这里同时钉住两件事：配得上、且**不留 query**。
    """
    inner = _FakeInner(
        events=[
            _response_event(
                "1", "https://www.zhipin.com/wapi/zpgeek/search/joblist.json?token=SECRET&page=1#frag"
            )
        ],
        bodies={"1": _body_result({"zpData": {"jobList": [{"jobName": "后端"}]}})},
    )
    recorder = _recorder(tmp_path, inner)

    recorder.drain_events()  # 先记住 url
    recorder.send("Network.getResponseBody", {"requestId": "1"})

    files = _saved_files(tmp_path)
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    payload = json.loads(text)
    assert payload["url_path"] == "/wapi/zpgeek/search/joblist.json"
    assert "SECRET" not in text  # query 里的令牌绝不落盘
    assert "?" not in text and "#" not in text
    assert payload["body"]["zpData"]["jobList"] == [{"jobName": "后端"}]
    assert payload["captured_at"]
    assert files[0].name.endswith("-search.json")


def test_detail_and_search_use_their_own_labels(tmp_path):
    """两类接口分别落 named 文件，用户/回归脚本一眼能分清哪份是搜索、哪份是详情。"""
    inner = _FakeInner(
        events=[
            _response_event("1", "https://x/wapi/zpgeek/search/joblist.json"),
            _response_event("2", "https://x/wapi/zpgeek/job/detail.json?id=9"),
        ],
        bodies={"1": _body_result({"a": 1}), "2": _body_result({"b": 2})},
    )
    recorder = _recorder(tmp_path, inner)
    recorder.drain_events()
    recorder.send("Network.getResponseBody", {"requestId": "1"})
    recorder.send("Network.getResponseBody", {"requestId": "2"})

    names = [path.name for path in _saved_files(tmp_path)]
    assert len(names) == 2
    assert any(name.endswith("-search.json") for name in names)
    assert any(name.endswith("-detail.json") for name in names)


# ===== 只保存目标接口 / 惰性建目录 =====


def test_non_target_responses_are_not_saved_and_no_directory_is_created(tmp_path):
    """页面上一堆无关请求（图片、脚本、埋点）一条都不该存；没存东西就不留空目录。

    这条同时覆盖"开关为假时不创建目录、不写文件"的实质：装饰器**惰性建目录**，
    没有命中目标接口时磁盘上什么都不会多出来。
    """
    inner = _FakeInner(
        events=[_response_event("1", "https://www.zhipin.com/img/logo.png")],
        bodies={"1": _body_result({"x": 1})},
    )
    recorder = _recorder(tmp_path, inner)
    recorder.drain_events()
    recorder.send("Network.getResponseBody", {"requestId": "1"})

    assert _saved_files(tmp_path) == []
    assert not (tmp_path / "captures").exists()


# ===== 上限与日志 =====


def test_sample_limit_stops_saving_and_logs(tmp_path, caplog):
    """每次采集最多 N 份，超了就停并**记日志说明**——绝不静默丢。"""
    events = [_response_event(str(i), "https://x/wapi/zpgeek/search/joblist.json") for i in range(5)]
    bodies = {str(i): _body_result({"i": i}) for i in range(5)}
    inner = _FakeInner(events=events, bodies=bodies)
    recorder = _recorder(tmp_path, inner, max_samples=2)

    with caplog.at_level(logging.WARNING):
        recorder.drain_events()
        for i in range(5):
            recorder.send("Network.getResponseBody", {"requestId": str(i)})

    assert recorder.saved_count == 2
    assert len(_saved_files(tmp_path)) == 2
    assert any("上限" in record.message for record in caplog.records)


def test_oversized_sample_is_skipped_and_logged(tmp_path, caplog):
    """单份超过上限就跳过并记日志（多半抓到了图片/脚本一类的巨物）。"""
    huge = {"blob": "x" * 5000}
    inner = _FakeInner(
        events=[_response_event("1", "https://x/wapi/zpgeek/search/joblist.json")],
        bodies={"1": _body_result(huge)},
    )
    recorder = _recorder(tmp_path, inner, max_bytes=512)

    with caplog.at_level(logging.WARNING):
        recorder.drain_events()
        recorder.send("Network.getResponseBody", {"requestId": "1"})

    assert _saved_files(tmp_path) == []
    assert any("单份上限" in record.message for record in caplog.records)


def test_tracked_request_map_is_bounded(tmp_path):
    """``requestId → url`` 映射有上限：超限丢最旧的，长跑时不会无界增长。

    这里上限设 2、连续记 3 条，再对**最旧的**取体——它应已被淘汰、配不上 URL、不落盘；
    对**最新的**取体则应正常落盘。
    """
    inner = _FakeInner(
        events=[
            _response_event("1", "https://x/wapi/zpgeek/search/joblist/1.json"),
            _response_event("2", "https://x/wapi/zpgeek/search/joblist/2.json"),
            _response_event("3", "https://x/wapi/zpgeek/search/joblist/3.json"),
        ],
        bodies={
            "1": _body_result({"n": 1}),
            "2": _body_result({"n": 2}),
            "3": _body_result({"n": 3}),
        },
    )
    recorder = _recorder(tmp_path, inner, max_tracked_requests=2)
    recorder.drain_events()
    recorder.send("Network.getResponseBody", {"requestId": "1"})  # 已淘汰
    recorder.send("Network.getResponseBody", {"requestId": "3"})  # 仍在

    files = _saved_files(tmp_path)
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding="utf-8"))["url_path"].endswith("/joblist/3.json")


# ===== 失败不影响主流程 =====


def test_non_json_body_is_skipped_without_affecting_the_caller(tmp_path):
    """抓到 HTML（被风控换成验证页）时安静跳过，且 ``send`` 的返回值原样透传。"""
    result = {"body": "<html>验证</html>", "base64Encoded": False}
    inner = _FakeInner(
        events=[_response_event("1", "https://x/wapi/zpgeek/search/joblist.json")],
        bodies={"1": result},
    )
    recorder = _recorder(tmp_path, inner)

    returned = (
        recorder.drain_events(),
        recorder.send("Network.getResponseBody", {"requestId": "1"}),
    )

    assert returned[1] == result  # 主流程拿到的还是原来的响应
    assert _saved_files(tmp_path) == []


# ===== 其余调用一律转发（不能吞掉订阅 / 关闭等能力）=====


def test_forwards_non_intercepted_calls(tmp_path):
    """``CdpClient`` 给可选能力的默认实现是"不支持"的空实现——忘转发会**静默**把订阅吞掉。

    所以这里逐个确认：订阅、停止订阅、取走事件、关闭都真的转发到了内层。
    """
    inner = _FakeInner(events=[_response_event("1", "https://x/wapi/zpgeek/search/joblist.json")])
    recorder = _recorder(tmp_path, inner)

    recorder.start_event_capture(["Network.responseReceived"])
    assert recorder.drain_events() == [
        _response_event("1", "https://x/wapi/zpgeek/search/joblist.json")
    ]
    recorder.stop_event_capture()
    recorder.close()

    assert inner.capture_started == ["Network.responseReceived"]
    assert inner.capture_stopped is True
    assert inner.closed is True


# ===== 与真实适配器路径接起来：markers 来自适配器、配对走真实时序 =====


def test_records_through_the_real_adapter_capture_path(tmp_path):
    """把"适配器声明的 markers"与"真实取体时序"接在一起钉住。

    单测能证明装饰器配得上，但**配不上**才是更常见的真实故障：适配器取的 requestId 与
    装饰器记住的 requestId 若不是同一个（或订阅没转发、事件没经过 drain），装饰器就永远
    存不下东西，而且不报错。这条复用 ``test_boss_network`` 的 ``ScriptedClient`` 走真实
    ``BossAdapter.collect_search``，证明端到端确实存下了搜索接口的原文。
    """
    from app.services.sites.base import CollectQuery
    from app.services.sites.boss_network import SEARCH_MARKER
    from test_boss_network import (
        READY,
        ScriptedClient,
        _adapter,
        _body_event,
        _response_event as boss_response_event,
        _search_payload,
    )

    events = [
        boss_response_event("1", f"https://www.zhipin.com{SEARCH_MARKER}?page=1"),
        _body_event("1", _search_payload()),
    ]
    inner = ScriptedClient(
        events=events,
        expressions={"rf:readiness": READY, "rf:collect": {"items": [{"title": "DOM 来的"}]}},
    )
    recorder = SampleRecordingCdpClient(
        inner,
        markers=_adapter().sample_markers,
        directory=tmp_path / "captures" / "boss",
    )

    _adapter().collect_search(recorder, CollectQuery(keywords=["后端"]), 1)

    files = _saved_files(tmp_path)
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["url_path"] == SEARCH_MARKER
    assert payload["body"]["zpData"]["jobList"]


# ===== 样例目录的硬边界 =====


def test_captures_directory_is_under_backend_data_and_not_a_dataset_dir():
    """样例目录必须落在 ``backend/data/captures``，且与数据集目录**分开**。

    这是三条硬边界里的第 3 条：样例是排查产物，不该跟着数据集切换，更不该和投递浏览器的
    登录态（``backend/data/browser-profile/``）混在一起。这里钉住它的推导来源与落点——目录
    一旦漂移到数据集里，样例就会跟着备份包被带出去。
    """
    from app.config import BACKEND_DIR, DATA_DIR, captures_dir
    from app.dataset_registry import datasets_directory

    captures = captures_dir()
    # 与数据库同源推导：都在 backend/data 下，而不是别处拼出来的相对路径。
    assert captures == DATA_DIR / "captures"
    assert DATA_DIR == BACKEND_DIR / "data"
    assert BACKEND_DIR in captures.parents
    # 与数据集目录互不包含（样例不进数据集，也不会被当成数据集的一部分）。
    datasets = datasets_directory()
    assert datasets not in captures.parents
    assert captures not in datasets.parents
