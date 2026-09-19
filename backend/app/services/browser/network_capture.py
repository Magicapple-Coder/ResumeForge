"""从 CDP 网络事件里解析招聘网站的接口响应。

**为什么优先走网络而不是 DOM**：岗位列表与详情都是 XHR 渲染的。直接读接口响应有几个
实打实的好处——字段齐全（列表页只有摘要，详情接口带完整 JD）、不受渲染时序影响
（页面结构变了但接口回来的还是同一份数据）、不受字体反爬影响（有的站点把关键数字
渲染成自定义字体，读 DOM 只能拿到乱码，而响应里是明文）。

**DOM 解析仍然保留**：接口路径可能改、可能被风控换掉，那时退回 DOM 至少还能用。
两条路并存，由调用方决定用哪条，而不是二选一。

这里只做**纯解析**：吃 CDP 事件、吐结构化数据，不碰浏览器、不发请求，所以能离线测。
"""
from __future__ import annotations

import base64
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# 一次采集最多解多少条响应：页面里每条岗位卡片都可能触发一次请求，
# 不设上限会让内存随翻页线性增长。
MAX_PARSED_RESPONSES = 200
# 单个响应体的体积上限。招聘接口的 JSON 通常几十 KB，超过这个数说明抓到了别的东西
# （图片、脚本、被注入的探针），解它没有意义还占内存。
MAX_BODY_BYTES = 2 * 1024 * 1024


@dataclass
class CapturedResponse:
    """一条拦到的响应：URL 与已解码的 JSON 体。"""

    url: str
    body: Any


def _decode_body(event: dict[str, Any]) -> Any | None:
    """把 ``Network.getResponseBody`` 的返回解成 JSON；解不出来返回 None。"""
    result = event.get("result")
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
        if len(raw) > MAX_BODY_BYTES:
            return None
        body = raw.decode("utf-8", errors="replace")
    if len(body) > MAX_BODY_BYTES:
        return None
    try:
        return json.loads(body)
    except (ValueError, TypeError):
        # 不是 JSON（HTML、脚本、纯文本）——不是我们要的东西，安静地跳过。
        return None


def response_urls(events: list[dict[str, Any]], *, markers: Sequence[str]) -> list[str]:
    """从 ``Network.responseReceived`` 事件里挑出 URL 含任一 ``markers`` 的那些。

    返回的是**响应 id → URL** 的候选清单，调用方据此决定要取哪个响应体。
    按出现顺序返回，因为"点击卡片后第一个回来的详情请求"往往就是刚点的那条。

    ``markers`` 是一组片段、命中任一即可：站点给接口路径加版本后缀（``joblist.json`` →
    ``joblistV2.json``）时，只认整串会让这条通路**整体失效**，而它的失败方式恰恰是静默退回
    DOM。宽松一点的 URL 匹配由调用方的**结构判定**兜住（``looks_like_search`` 等），
    所以这里放宽是安全的。
    """
    urls: list[str] = []
    for event in events:
        if event.get("method") != "Network.responseReceived":
            continue
        params = event.get("params")
        if not isinstance(params, dict):
            continue
        response = params.get("response")
        if not isinstance(response, dict):
            continue
        url = str(response.get("url") or "")
        if markers and not any(marker and marker in url for marker in markers):
            continue
        if url and url not in urls:
            urls.append(url)
    return urls[:MAX_PARSED_RESPONSES]


def collect_bodies(
    events: list[dict[str, Any]],
    *,
    markers: Sequence[str] = (),
    limit: int = MAX_PARSED_RESPONSES,
) -> list[CapturedResponse]:
    """把一批事件里"已取回响应体"的那些解析出来。

    调用方需要先对候选 URL 发 ``Network.getResponseBody``，把结果也塞进这批事件里
    （它们的 ``method`` 是 ``Network.getResponseBody``，且带 ``requestId``）。
    """
    by_request: dict[str, str] = {}
    for event in events:
        if event.get("method") != "Network.responseReceived":
            continue
        params = event.get("params")
        response = params.get("response") if isinstance(params, dict) else None
        if not isinstance(response, dict):
            continue
        request_id = str(params.get("requestId") or "")
        url = str(response.get("url") or "")
        if request_id and url:
            by_request[request_id] = url

    captured: list[CapturedResponse] = []
    for event in events:
        if event.get("method") != "Network.getResponseBody":
            continue
        request_id = str(event.get("requestId") or "")
        url = by_request.get(request_id, "")
        if markers and not any(marker and marker in url for marker in markers):
            continue
        body = _decode_body(event)
        if body is None:
            continue
        captured.append(CapturedResponse(url=url, body=body))
        if len(captured) >= limit:
            break
    return captured


def first_json_with(
    captured: list[CapturedResponse], predicate
) -> Any | None:
    """按顺序找第一个满足 ``predicate`` 的响应体。

    顺序有意义：一类接口在页面上会被调用多次（滚动加载、切换筛选），而我们要的通常是
    **第一个**符合结构的那份——后面的可能是空页或别的筛选条件下的结果。
    """
    for item in captured:
        try:
            if predicate(item.body):
                return item.body
        except Exception:  # noqa: BLE001 - 结构五花八门，判定函数自己不该炸掉采集
            logger.debug("判定响应体时出错，已跳过：%s", item.url)
            continue
    return None


__all__ = [
    "MAX_BODY_BYTES",
    "MAX_PARSED_RESPONSES",
    "CapturedResponse",
    "collect_bodies",
    "first_json_with",
    "response_urls",
]
