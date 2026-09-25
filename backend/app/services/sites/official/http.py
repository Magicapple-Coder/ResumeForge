"""受限的取回层：SSRF 防护 + 大小/超时/跳转约束 + 阻断分类。

这是 ``FeedHttp`` 的**唯一实现**，也是适配器碰不到 httpx 的原因——把传输收在一处，
"忘了校验目标地址"这件事就不存在可选的余地。

与 ``services/search/page_reader.py`` 的关系：**复用它的 ``is_public_http_url``**（私网/回环
拒绝只有一份实现），但不复用它取正文的那条路径，原因有两条且都影响正确性：

1. **它跟随重定向时不重新校验目标**（``follow_redirects=True`` 交给 httpx 内部处理，跳转
   到 ``http://10.0.0.1/`` 不会被拦）。本模块手动跟跳转，**每一跳都重新过一遍防护**。
2. 它只返回正文、丢掉状态码，而状态码正是阻断分类的主要依据。

**本模块不重试。** 重试节奏属于编排层（要遵守站点的 ``Retry-After`` 与限速画像），放在这里
会让每一次取回都变成一个隐藏的多次请求，对账时数不清到底打了几次。
"""
from __future__ import annotations

from urllib.parse import urljoin, urlsplit

import httpx

from ....config import get_settings
from ....models.official import (
    BLOCK_FORBIDDEN,
    BLOCK_LOGIN,
    BLOCK_NETWORK,
    BLOCK_NONE,
    BLOCK_NOT_FOUND,
    BLOCK_RATE_LIMIT,
    BLOCK_TIMEOUT,
    BLOCK_UNKNOWN,
)
from ...search.page_reader import is_public_http_url
from . import blocking
from .base import FeedHttp, FetchResult

# 与 page_reader 一致的量级：招聘页比博客大，给宽一些，但仍然封顶。
DEFAULT_MAX_BYTES = 3_000_000
DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0)
MAX_REDIRECTS = 3
# 只取这几种；其余（二进制、图片）直接当"不是我们要的东西"。
_TEXTUAL_CONTENT_TYPES = ("json", "text/", "xml", "html", "javascript")


def default_user_agent() -> str:
    """如实标识自己。

    **不伪装成浏览器**：需要浏览器的场景（JS 渲染、登录态）走 CDP 用真浏览器，那是真的，
    不是假装。伪装 UA 的唯一作用是让站点无法识别访问者身份，而这恰好也是站点最不欢迎的
    行为——代价则是我们在被误伤时连一个可追溯的联系方式都没有。
    """
    try:
        version = get_settings().app_version
    except Exception:  # noqa: BLE001 - 取版本失败不该让一次采集起不来
        version = "0"
    return f"ResumeForge/{version} (+local job seeker tool; official site collector)"


def _default_headers(extra: dict[str, str] | None) -> dict[str, str]:
    headers = {
        "User-Agent": default_user_agent(),
        "Accept": "application/json, text/html;q=0.9, */*;q=0.5",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if extra:
        headers.update(extra)
    return headers


def _classify_status(status_code: int, headers: dict[str, str]) -> tuple[str, str]:
    """按状态码定性，返回 ``(分类, 面向用户的诊断)``。"""
    if status_code == 200:
        return BLOCK_NONE, ""
    if status_code == 429:
        retry_after = headers.get("retry-after", "")
        hint = f"，站点建议 {retry_after} 秒后重试" if retry_after.isdigit() else ""
        return BLOCK_RATE_LIMIT, f"站点限流（HTTP 429）{hint}，本次采集无法确认是否抓全"
    if status_code == 403:
        return BLOCK_FORBIDDEN, "站点拒绝访问（HTTP 403），可能触发了风控或需登录"
    if status_code in {401, 407}:
        return BLOCK_LOGIN, f"需要登录后才能访问（HTTP {status_code}）"
    if status_code == 404:
        return BLOCK_NOT_FOUND, "接口不存在（HTTP 404）"
    if status_code >= 500:
        return BLOCK_UNKNOWN, f"站点服务端错误（HTTP {status_code}），稍后可重试"
    return BLOCK_UNKNOWN, f"未预期的响应状态（HTTP {status_code}）"


def _is_textual(content_type: str) -> bool:
    if not content_type:
        return True  # 站点没给类型时不据此拒绝，靠后面的内容判定
    return any(marker in content_type for marker in _TEXTUAL_CONTENT_TYPES)


class HttpxFeedHttp(FeedHttp):
    """基于 httpx 的取回实现。

    持有一个连接池，**跨一次采集的多次请求复用**（适配器翻页时会打很多次同一站点）。
    用完必须 ``aclose()``；作为异步上下文管理器用最省心。
    """

    def __init__(
        self,
        *,
        timeout: httpx.Timeout | None = None,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_redirects: int = MAX_REDIRECTS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = timeout or DEFAULT_TIMEOUT
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        # 测试注入 MockTransport，生产为 None（走真实网络）。
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> HttpxFeedHttp:
        self._ensure_client()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                # 跳转自己跟，每一跳都要重新过 SSRF 校验（见模块说明）。
                follow_redirects=False,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict | None = None,
        headers: dict[str, str] | None = None,
        max_bytes: int | None = None,
    ) -> FetchResult:
        # 适配器覆盖上限时以它为准；0 或负数视为没给，回落到构造时的默认值。
        limit = max_bytes if max_bytes and max_bytes > 0 else self._max_bytes
        try:
            return await self._request_following_redirects(
                method, url, params=params, json_body=json_body, headers=headers, limit=limit
            )
        except httpx.TimeoutException as exc:
            return FetchResult(block=BLOCK_TIMEOUT, detail=f"请求超时：{type(exc).__name__}")
        except httpx.HTTPError as exc:
            return FetchResult(
                block=BLOCK_NETWORK, detail=f"连接失败：{type(exc).__name__}"
            )

    async def _request_following_redirects(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None,
        json_body: dict | None,
        headers: dict[str, str] | None,
        limit: int,
    ) -> FetchResult:
        client = self._ensure_client()
        current = url
        current_params = params
        merged_headers = _default_headers(headers)

        for hop in range(self._max_redirects + 1):
            # 每一跳都校验：被跳转到的地址和用户直接给的地址一样不可信。
            if not is_public_http_url(_with_query(current, current_params)):
                return FetchResult(
                    block=BLOCK_FORBIDDEN,
                    detail=f"目标地址不是可访问的公网 http/https 地址，已拒绝：{_safe_host(current)}",
                )

            async with client.stream(
                method, current, params=current_params, json=json_body, headers=merged_headers
            ) as response:
                response_headers = {
                    key.casefold(): value for key, value in response.headers.items()
                }
                if response.is_redirect:
                    if hop >= self._max_redirects:
                        # 先在**这里**判定放弃。若靠"让循环自然结束、由函数末尾收尾"，
                        # 最后一跳会落到下面的状态码分类，用户看到的是
                        # "未预期的响应状态（HTTP 302）"——真正的原因（一直在跳转）被丢掉。
                        return FetchResult(
                            block=BLOCK_UNKNOWN,
                            status_code=response.status_code,
                            detail=f"跳转次数超过 {self._max_redirects} 次，已放弃",
                        )
                    location = response.headers.get("location", "")
                    if not location:
                        return FetchResult(
                            block=BLOCK_UNKNOWN,
                            status_code=response.status_code,
                            detail="跳转响应没有 Location 头",
                        )
                    current = urljoin(str(response.url), location)
                    # 跳转后不再重复携带原始 query/body：语义已由 Location 决定。
                    current_params = None
                    json_body = None
                    continue

                body = bytearray()
                truncated = False
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > limit:
                        truncated = True
                        break
                    body.extend(chunk)

                return self._classify(
                    response.status_code, bytes(body), response_headers, truncated, limit
                )

        # 正常情况下循环内部一定会 return（每一跳要么继续、要么给出结果）。走到这里只可能是
        # ``max_redirects`` 被传成了负数，导致 range 为空——给一个诚实的兜底而不是让函数返回 None。
        return FetchResult(
            block=BLOCK_UNKNOWN, detail=f"跳转上限配置无效（{self._max_redirects}），未发起请求"
        )

    def _classify(
        self,
        status_code: int,
        raw: bytes,
        headers: dict[str, str],
        truncated: bool,
        limit: int,
    ) -> FetchResult:
        block, detail = _classify_status(status_code, headers)
        text = raw.decode("utf-8", errors="replace")

        if block != BLOCK_NONE:
            return FetchResult(
                block=block, status_code=status_code, text=text, detail=detail, headers=headers
            )

        # 截断**先于**内容判定：它是关于"这份响应本身完不完整"的传输层事实，而不是从内容
        # 里读出来的结论。顺序反了会出现这种情况——首个分块就超过上限时正文为空，于是被
        # 空响应规则判成软封禁，真正的原因（截断）反而丢了。
        if truncated:
            return FetchResult(
                block=BLOCK_UNKNOWN,
                status_code=status_code,
                text=text,
                detail=f"响应体超过 {limit} 字节已截断，内容可能不完整",
                headers=headers,
            )

        content_type = headers.get("content-type", "").casefold()
        if not _is_textual(content_type):
            return FetchResult(
                block=BLOCK_UNKNOWN,
                status_code=status_code,
                detail=f"返回的不是文本内容（{content_type}）",
                headers=headers,
            )

        # 状态码正常 ≠ 内容是内容：验证码页、登录墙、空壳页都是 200。
        body_block = blocking.classify_html(text)
        if body_block != BLOCK_NONE:
            return FetchResult(
                block=body_block,
                status_code=status_code,
                text=text,
                detail=_body_block_detail(body_block),
                headers=headers,
            )

        return FetchResult(
            block=BLOCK_NONE,
            status_code=status_code,
            text=text,
            detail=detail,
            headers=headers,
        )


def _with_query(url: str, params: dict[str, str] | None) -> str:
    """把查询参数拼进 URL，供 SSRF 校验使用。

    校验必须看**带 query 的完整地址**：``is_public_http_url`` 会拒绝带 userinfo 的地址，
    这里保持一致，避免校验的是一个地址、请求的是另一个。
    """
    if not params:
        return url
    try:
        from urllib.parse import urlencode

        separator = "&" if urlsplit(url).query else "?"
        return f"{url}{separator}{urlencode(params)}"
    except (TypeError, ValueError):
        return url


def _safe_host(url: str) -> str:
    """只回显主机名，不把完整 URL 写进诊断（查询串里可能有站点令牌）。"""
    try:
        return urlsplit(url).hostname or "(无法解析)"
    except ValueError:
        return "(无法解析)"


def _body_block_detail(block: str) -> str:
    from ....models.official import BLOCK_LABELS

    return f"响应状态正常，但内容不是招聘数据：{BLOCK_LABELS.get(block, block)}"


__all__ = ["DEFAULT_MAX_BYTES", "HttpxFeedHttp", "default_user_agent"]
