"""记录采集过程中站点接口的**响应原文**，供离线回归测试使用。

为什么需要这个能力：仓库里**一份真实抓取样例都没有**（``tests/fixtures/`` 是空的），
现有站点解析测试用的全是**手写 payload**——那只能证明"解析器能解析我们想象出来的结构"。
要做"真实样例回归"（站点改版时立刻发现），必须先有真实样例；本装饰器就是那条通道。

它往磁盘写站点数据，所以三条底线不能破：

1. **默认关闭、每次采集显式勾选**：只有任务运行器读到 ``save_site_samples`` 为真时才安装
   本装饰器；为假时连目录都不创建、一个文件都不写（见 ``task_runner._run_collect``）。
2. **不落任何凭据**：URL 只保留 ``path``，丢掉 query / fragment——query 里可能有站点内部
   参数甚至令牌，而夹具只需要 path（本项目判断接口用的就是 path 上的 markers）。也**不**
   记录请求头、Cookie、请求体。
3. **只写进 ``<数据目录>/captures/``**：该目录在 ``backend/data/`` 下、已被 ``.gitignore``
   忽略；绝不写进 ``backend/data/browser-profile/``（投递浏览器的登录态）或任何 dataset 目录。

本模块**不含任何站点专属常量**：要保存哪些接口由调用方（任务运行器）从站点适配器的
``sample_markers`` 取出来传进来——站点知识只属于适配器层，这是本项目的分层纪律。
"""
from __future__ import annotations

import base64
import json
import logging
from collections import OrderedDict
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .cdp_client import CdpClient

logger = logging.getLogger(__name__)

# 一次采集最多保存多少份样例。样例是"出问题时拿来对着看"的，几十份足够覆盖列表与详情；
# 不设上限则长跑（翻很多页）会把磁盘和样例的体积都耗在大量重复的结构上。
MAX_SAMPLES_PER_CAPTURE = 30

# 单份样例的字节上限。招聘接口的 JSON 通常几十 KB，超过这个数多半抓到了别的东西
# （图片、脚本、被注入的探针），留着没有价值还占磁盘。
MAX_SAMPLE_BYTES = 2 * 1024 * 1024

# ``requestId → url`` 映射的上限。URL 先出现、响应体后取，配对必须靠这张表；长跑会让它
# 无界增长，超限时丢最旧的即可（响应体通常紧随 URL 之后回来，旧条目早就用不上了）。
MAX_TRACKED_REQUESTS = 500


def _url_path(url: str) -> str:
    """只取 URL 的 path，丢掉 query 与 fragment（见模块说明的第 2 条底线）。"""
    try:
        return urlsplit(url).path or ""
    except ValueError:  # 极端畸形 URL：宁可留空，也不让采集因它报错
        return ""


def _decode_body(result: Any) -> Any | None:
    """把 ``Network.getResponseBody`` 的 result 解成 JSON；解不出来返回 None。

    解码失败 / 非 JSON（HTML、脚本）都只返回 None——调用方据此跳过这一条，
    **绝不影响主采集流程**。
    """
    if not isinstance(result, dict):
        return None
    body = result.get("body")
    if not isinstance(body, str) or not body:
        return None
    if result.get("base64Encoded"):
        try:
            raw = base64.b64decode(body, validate=False)
        except (ValueError, TypeError):
            return None
        body = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(body)
    except (ValueError, TypeError):
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SampleRecordingCdpClient(CdpClient):
    """在 ``StopAwareCdpClient`` 之外再包一层，把目标接口的响应原文落盘。

    与既有装饰器同构：它是一个 ``CdpClient``，把每个调用转发给内层，只在两处插观察：

    - ``drain_events()``：从 ``Network.responseReceived`` 里记下 ``requestId → url``；
    - ``send("Network.getResponseBody", ...)``：用 ``requestId`` 配对出 URL 与响应体，
      命中调用方给的 markers 就落盘。

    **配对顺序是有意的**：URL（responseReceived）总是先出现、响应体（getResponseBody）
    后取，所以这里维护一张映射来配对。反过来做（先看响应体再找 URL）根本配不上。
    """

    def __init__(
        self,
        inner: CdpClient,
        *,
        markers: Sequence[tuple[str, Sequence[str]]],
        directory: Path,
        max_samples: int = MAX_SAMPLES_PER_CAPTURE,
        max_bytes: int = MAX_SAMPLE_BYTES,
        max_tracked_requests: int = MAX_TRACKED_REQUESTS,
    ) -> None:
        """``markers`` 是一组 ``(标签, 路径片段...)``；标签用于文件名（search / detail）。

        ``directory`` 就是样例要写进的**最终目录**（由调用方按 ``captures/<site_key>``
        拼好传进来），这里不再自行推导——这样测试能换成临时目录，生产也只有一个来源。
        """
        self._inner = inner
        self._markers = tuple(
            (str(label), tuple(marker for marker in group if marker))
            for label, group in (markers or ())
        )
        self._directory = Path(directory)
        self._max_samples = max(0, int(max_samples))
        self._max_bytes = max(0, int(max_bytes))
        self._max_tracked = max(1, int(max_tracked_requests))
        self._request_urls: OrderedDict[str, str] = OrderedDict()
        self._saved = 0
        self._count_limit_logged = False
        self._size_limit_logged = False

    @property
    def saved_count(self) -> int:
        """本次已保存的样例份数（任务收尾时写进文案，用户据此知道存了几份）。"""
        return self._saved

    @property
    def directory(self) -> Path:
        """样例落盘的目录（任务收尾时写进文案，用户据此知道去哪儿拿）。"""
        return self._directory

    # ===== 观察点 =====

    def _remember_urls(self, events: Sequence[dict[str, Any]]) -> None:
        for event in events:
            if not isinstance(event, dict) or event.get("method") != "Network.responseReceived":
                continue
            params = event.get("params")
            response = params.get("response") if isinstance(params, dict) else None
            if not isinstance(response, dict):
                continue
            request_id = str(params.get("requestId") or "")
            url = str(response.get("url") or "")
            if not request_id or not url:
                continue
            self._request_urls[request_id] = url
            self._request_urls.move_to_end(request_id)
            # 有界：超限丢最旧的，防止长跑时无界增长。
            while len(self._request_urls) > self._max_tracked:
                self._request_urls.popitem(last=False)

    def _label_for(self, url: str) -> str | None:
        for label, markers in self._markers:
            if any(marker in url for marker in markers):
                return label
        return None

    def _record(self, url: str, result: Any) -> None:
        label = self._label_for(url)
        if label is None:
            # 不是我们要保存的接口：安静跳过（页面上几十个无关请求都会走到这里）。
            return
        if self._saved >= self._max_samples:
            if not self._count_limit_logged:
                logger.warning(
                    "本次采集已保存 %s 份站点样例，达到上限，后续样例不再保存（目录：%s）",
                    self._max_samples,
                    self._directory,
                )
                self._count_limit_logged = True
            return
        body = _decode_body(result)
        if body is None:
            # 解码失败 / 非 JSON：不影响主流程，也不落盘（夹具要的是可解析的结构）。
            return
        payload = json.dumps(
            {
                # 只留 path、不留 query（见模块说明第 2 条底线）。
                "url_path": _url_path(url),
                "captured_at": _now().isoformat(),
                "body": body,
            },
            ensure_ascii=False,
            indent=2,
        )
        encoded = payload.encode("utf-8")
        if len(encoded) > self._max_bytes:
            if not self._size_limit_logged:
                logger.warning(
                    "站点样例超过单份上限（%s 字节），已跳过这一份：%s",
                    self._max_bytes,
                    _url_path(url),
                )
                self._size_limit_logged = True
            return
        try:
            # 惰性建目录：只有真的要写时才创建，避免"没抓到任何东西"也在磁盘上留一个空目录。
            self._directory.mkdir(parents=True, exist_ok=True)
            path = self._directory / self._file_name(label)
            path.write_bytes(encoded)
        except OSError:
            logger.warning("写入站点样例失败，已跳过（不影响采集）：%s", _url_path(url), exc_info=True)
            return
        self._saved += 1

    def _file_name(self, label: str) -> str:
        stamp = _now().strftime("%Y%m%d-%H%M%S")
        # 序号保证同一秒内的多份也不会互相覆盖。
        return f"{stamp}-{self._saved + 1:03d}-{label}.json"

    def drain_events(self) -> list[dict[str, Any]]:
        events = self._inner.drain_events()
        self._remember_urls(events)
        return events

    def send(
        self, method: str, params: dict[str, Any] | None = None, *, timeout: float | None = None
    ) -> dict[str, Any]:
        result = self._inner.send(method, params, timeout=timeout)
        if method == "Network.getResponseBody" and isinstance(params, dict):
            request_id = str(params.get("requestId") or "")
            url = self._request_urls.get(request_id)
            if url:
                self._record(url, result)
        return result

    # ===== 其余调用一律原样转发 =====
    # 与 ``StopAwareCdpClient`` 同样的纪律：``CdpClient`` 给可选能力提供了"不支持"的空实现，
    # 忘转发不会报错，只会**安静地**把事件订阅 / 关闭等能力吞掉。所以这里逐个显式转发。

    def list_targets(self) -> list[dict[str, Any]]:
        return self._inner.list_targets()

    def new_tab(self, url: str = "about:blank") -> str:
        return self._inner.new_tab(url)

    def evaluate(self, expression: str, *, timeout: float | None = None) -> Any:
        return self._inner.evaluate(expression, timeout=timeout)

    def navigate(self, url: str, *, timeout: float | None = None) -> dict[str, Any]:
        return self._inner.navigate(url, timeout=timeout)

    def set_file_input(
        self, selector: str, files: list[str], *, timeout: float | None = None
    ) -> None:
        return self._inner.set_file_input(selector, files, timeout=timeout)

    def start_event_capture(self, methods: Sequence[str]) -> None:
        self._inner.start_event_capture(methods)

    def stop_event_capture(self) -> None:
        self._inner.stop_event_capture()

    def close(self) -> None:
        self._inner.close()


__all__ = [
    "MAX_SAMPLE_BYTES",
    "MAX_SAMPLES_PER_CAPTURE",
    "MAX_TRACKED_REQUESTS",
    "SampleRecordingCdpClient",
]
