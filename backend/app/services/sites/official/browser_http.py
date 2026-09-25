"""HTTP 取回来是空壳时，改用真实浏览器重取。

**为什么做成传输层的装饰器**：与 ``RobotsAwareHttp`` 同一个形状——适配器拿到的仍然只是一个
``FeedHttp``，它不知道（也不需要知道）背后有一次升级。把判断塞进适配器，等于让每个适配器都
各写一遍"这一页要不要渲染"，而漏写的那个就静默漏抓。

**用真浏览器，不是伪装成浏览器**：这条路径打开的是用户本机已装的那个浏览器（投递台用的同一个
实例，用户可能已经在里面登录过站点）。它不伪造任何东西——那本来就是浏览器。

**浏览器没在跑时如实说明**：这一页读不出内容的原因会写进 ``detail``，而不是安静地返回一个空页
（空页会被读成"这里没有岗位"，而真实原因是"我们没能渲染它"）。这是本模块最要紧的一条：
升级失败必须留下痕迹。
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

from ...browser.cdp_client import CdpClient, CdpError
from ...browser.page_ready import ReadyWait, wait_for_page_state
from ...search.page_reader import is_public_http_url
from ....models.official import (
    BLOCK_CAPTCHA,
    BLOCK_FORBIDDEN,
    BLOCK_LOGIN,
    BLOCK_NETWORK,
    BLOCK_NONE,
    BLOCK_TIMEOUT,
)
from .base import BROWSER_ACTION_PARAM, BROWSER_PAGE_PARAM, FeedHttp, FetchResult
from .blocking import classify_html
from .rendering import needs_rendering

logger = logging.getLogger(__name__)

# 渲染后的页面通常远大于接口响应（DOM 里带着全部样式与脚本）。封顶防止单页撑爆内存。
MAX_BYTES = 6_000_000
# 交给浏览器的等待预算：比站点采集用得宽——陌生站点的首屏差异很大，而这里没有站点知识
# 可以据以提前判断。
RENDER_WAIT = ReadyWait(timeout=20.0, poll_interval=0.5)

_PROBE_SCRIPT = "document.documentElement.outerHTML"

# 正式取回用的脚本：渲染后的 DOM，但**把 ``<style>`` 里的 CSS 文本清空**。
#
# 为什么非清不可：不少站点把整站的 CSS 内联进 ``<style>``。实测一个真实招聘站——整页
# 6.8 MB，其中 **5.8 MB 是 768 个 `<style>` 的文本**，``<body>`` 只有 66 KB。而下面的
# ``MAX_BYTES`` 是**按字节从头截**的，于是截出来的那 6 MB 全是样式表：正文连同全部岗位
# 链接一起被切掉，上层看到的是"这一页一条站内链接都没有"——**一句关于页面的假话**，
# 而真正的原因在我们自己的截断上。清掉之后同一页只剩 1 MB 出头。
#
# 清掉是安全的，因为**没有任何一级抽取读 CSS 文本**：``html_to_text`` 明确跳过 ``style``；
# 结构化数据在 ``<script>`` 里（**不动**）；岗位链接与文字在 DOM 结构里。改的还只是**取回的
# 那份副本**——在克隆节点上清，用户面前那个标签页的样式一个字都不动。
_CONTENT_SCRIPT = """
(() => {
  const clone = document.documentElement.cloneNode(true);
  for (const element of clone.querySelectorAll('style')) element.textContent = '';
  return clone.outerHTML;
})()
"""

_PAGE_MARKER_SCRIPT = """
(() => {
  const active = document.querySelector(
    '[aria-current="page"], .atsx-pagination-item-active, [data-page-active="true"]'
  );
  const links = Array.from(document.querySelectorAll('a[href]'))
    .slice(0, 12)
    .map((node) => node.getAttribute('href') || '')
    .join('|');
  const text = (document.body?.innerText || '').slice(0, 400);
  return String(active?.textContent || '') + '|' + links + '|' + text;
})()
"""


def _is_robots_url(url: str) -> bool:
    """robots.txt 是规则文本，不应因为返回了 HTML 错误页而升级到浏览器。"""
    try:
        return urlsplit(url).path.rstrip("/").casefold() == "/robots.txt"
    except ValueError:
        return False


class RenderFailed(Exception):
    """浏览器渲染没能在预算内产出可用内容。"""


class RenderBlocked(RenderFailed):
    """渲染出来的页面上出现了验证码 / 登录墙。

    单独一类是为了**把分类带出来**：它和"页面上什么都没有"是两件完全不同的事，若都收敛成
    "超时"，报告里就分不出"这个站点要求人机校验"与"我们的渲染预算不够"——而这两者的下一步
    动作完全相反（前者交给用户手动过验证，后者值得重试或放宽预算）。
    """

    def __init__(self, block: str, detail: str) -> None:
        super().__init__(detail)
        self.block = block


class BrowserRenderedHttp(FeedHttp):
    """用真实浏览器取回页面内容。

    **只支持 GET**：CDP 取回的本质是"打开这个地址，再把渲染后的 DOM 交出来"——没有别的动词。
    非 GET 直接返回分类，不假装支持。
    """

    def __init__(self, client: CdpClient, *, wait: ReadyWait = RENDER_WAIT) -> None:
        self._client = client
        self._wait = wait

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
        raw_params = params or {}
        action = str(raw_params.get(BROWSER_ACTION_PARAM) or "").strip()
        target_page = _page_number(raw_params.get(BROWSER_PAGE_PARAM))
        navigation_url = _url_with_params(
            url,
            {
                key: value
                for key, value in raw_params.items()
                if key not in {BROWSER_ACTION_PARAM, BROWSER_PAGE_PARAM}
            },
        )
        del json_body, headers  # 浏览器自己带会话与请求头，我们不该覆盖
        if method.upper() != "GET":
            return FetchResult(block=BLOCK_NETWORK, detail="浏览器取回只支持 GET")
        # **同样过 SSRF 防护**：浏览器是我们驱动的，把一个用户可控的地址交给它去打开，
        # 与本机自己发请求是同一类风险（甚至更隐蔽——它带着用户的 Cookie 与内网可达性）。
        if not is_public_http_url(navigation_url):
            return FetchResult(
                block=BLOCK_FORBIDDEN, detail="目标地址不是可访问的公网 http/https 地址，已拒绝"
            )
        # CDP 客户端是**阻塞**的（WebSocket 同步收发），丢进线程跑：直接调用会卡住事件循环，
        # 而采集期间事件循环还要服务接口轮询与停止请求。
        return await asyncio.to_thread(
            self._fetch_blocking, navigation_url, max_bytes or MAX_BYTES, action, target_page
        )

    def _fetch_blocking(
        self, url: str, max_bytes: int, action: str = "", target_page: int = 1
    ) -> FetchResult:
        try:
            self._client.navigate(url)
            state = wait_for_page_state(
                probe=lambda: {"html": self._read_html()},
                is_ready=lambda captured: not needs_rendering(str(captured.get("html") or "")),
                blocker=_blocker,
                on_timeout=lambda captured: RenderFailed(
                    f"浏览器已在 {self._wait.timeout:.0f} 秒内打开该地址，但内容仍未渲染出来"
                ),
                config=self._wait,
            )
            for _ in range(max(1, target_page - 1) if action else 0):
                # 某些站点会忽略隐藏标签页上的程序化 click（用户真实点击不可能发生在
                # hidden 页面上）。导航后页面可能再次变成 hidden，所以要在每次交互式翻页前
                # 重新确保窗口可见；不具备这项可选能力的假客户端继续走原来的 DOM 路径。
                self._ensure_page_visible()
                before_html = str(state.get("html") or "")
                before_marker = self._read_marker()
                if not self._click_action(action):
                    return FetchResult(
                        block=BLOCK_TIMEOUT,
                        status_code=200,
                        detail=f"浏览器页面没有可用的「{action}」控件，无法继续翻页",
                    )
                state = wait_for_page_state(
                    probe=lambda: {
                        "html": self._read_html(),
                        "marker": self._read_marker(),
                    },
                    is_ready=lambda captured: (
                        not needs_rendering(str(captured.get("html") or ""))
                        and (
                            str(captured.get("marker") or "") != before_marker
                            or str(captured.get("html") or "") != before_html
                        )
                    ),
                    blocker=_blocker,
                    on_timeout=lambda captured: RenderFailed(
                        f"浏览器点击「{action}」后，在 {self._wait.timeout:.0f} 秒内没有得到下一页内容"
                    ),
                    config=self._wait,
                )
        except RenderBlocked as exc:
            return FetchResult(block=exc.block, detail=str(exc))
        except RenderFailed as exc:
            return FetchResult(block=BLOCK_TIMEOUT, detail=str(exc))
        except CdpError as exc:
            return FetchResult(block=BLOCK_NETWORK, detail=f"浏览器取回失败：{exc}")
        except Exception as exc:  # noqa: BLE001 - 浏览器侧什么都可能抛，收敛成分类
            logger.exception("浏览器取回时发生意外错误")
            return FetchResult(block=BLOCK_NETWORK, detail=f"浏览器取回失败：{type(exc).__name__}")

        # 就绪判定读的是**原样的 DOM**（判据看文字与脚本，不看 CSS 文本，两者等价且更省），
        # 这里再取一次，取的是清掉样式文本的那一份。
        html = self._read_content() or str(state.get("html") or "")
        if len(html.encode("utf-8", errors="replace")) > max_bytes:
            return FetchResult(
                block=BLOCK_NONE,
                status_code=200,
                text=html[:max_bytes],
                detail="渲染后的页面超过上限已截断，内容可能不完整",
            )
        return FetchResult(block=BLOCK_NONE, status_code=200, text=html)

    def _read_html(self) -> str:
        value = self._client.evaluate(_PROBE_SCRIPT)
        return value if isinstance(value, str) else ""

    def _read_content(self) -> str:
        """取回正文那一份（样式文本已清空）。取不到时返回空串，调用方回退到原样 DOM。"""
        value = self._client.evaluate(_CONTENT_SCRIPT)
        return value if isinstance(value, str) else ""

    def _read_marker(self) -> str:
        value = self._client.evaluate(_PAGE_MARKER_SCRIPT)
        return value if isinstance(value, str) else str(value or "")

    def _ensure_page_visible(self) -> None:
        ensure_visible = getattr(self._client, "ensure_page_visible", None)
        if not callable(ensure_visible):
            return
        try:
            if not ensure_visible():
                logger.debug("浏览器页面仍不可见，继续尝试交互式翻页")
        except Exception:  # noqa: BLE001 - 可见性保障是增强能力，失败不应掩盖点击诊断
            logger.debug("浏览器页面可见性保障失败", exc_info=True)

    def _click_action(self, action: str) -> bool:
        import json

        script = f"""
        (() => {{
          const wanted = {json.dumps(action, ensure_ascii=False)};
          const labels = new Set([wanted, wanted === "下一页" ? "Next" : ""]);
          const nodes = Array.from(document.querySelectorAll("[title], [aria-label], button, a, li"));
          const control = nodes.find((node) => {{
            const label = String(node.getAttribute("title") || node.getAttribute("aria-label") || "")
              .trim();
            if (!labels.has(label)) return false;
            const disabled = node.getAttribute("aria-disabled") === "true"
              || node.disabled === true
              || String(node.className || "").split(/\\s+/).some((item) => /disabled/i.test(item));
            return !disabled;
          }});
          if (!control) return {{ clicked: false }};
          const target = control.matches("button, a")
            ? control
            : control.querySelector("button, a") || control;
          target.click();
          return {{ clicked: true }};
        }})()
        """
        value = self._client.evaluate(script)
        return isinstance(value, dict) and bool(value.get("clicked"))


_BLOCKER_LABELS = {BLOCK_CAPTCHA: "安全验证", BLOCK_LOGIN: "登录墙"}


def _blocker(state: dict[str, Any]) -> Exception | None:
    """渲染出来的页面上出现验证码或登录墙就**立刻**停下，不傻等满超时。

    复用 ``classify_html`` 的判据：那几个特征在"取回的 HTML"和"渲染后的 DOM"上是同一件事。
    """
    block = classify_html(str(state.get("html") or ""))
    if block in _BLOCKER_LABELS:
        return RenderBlocked(block, f"浏览器打开后出现{_BLOCKER_LABELS[block]}")
    return None


def _page_number(value: Any) -> int:
    try:
        return max(1, int(str(value or "1")))
    except (TypeError, ValueError):
        return 1


def _url_with_params(url: str, params: dict[str, str]) -> str:
    if not params:
        return url
    parsed = urlsplit(url)
    query = urlencode(params)
    merged_query = f"{parsed.query}&{query}" if parsed.query else query
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, merged_query, parsed.fragment)
    )


class BrowserUpgradeHttp(FeedHttp):
    """先用 HTTP 取；取回来是"需要渲染"的空壳时，改用浏览器重取。

    ``client_factory`` 返回 ``None`` 表示浏览器没在跑——此时**如实说明**，而不是安静地返回
    那个空壳。空壳会被上层读成"这里没有岗位"，而真实原因是"我们没能渲染它"。
    """

    def __init__(
        self,
        inner: FeedHttp,
        client_factory: Callable[[], CdpClient | None],
        *,
        wait: ReadyWait = RENDER_WAIT,
    ) -> None:
        self._inner = inner
        self._client_factory = client_factory
        self._wait = wait

    async def aclose(self) -> None:
        """把底层 HTTP 连接池的关闭动作透传出来。"""
        await self._inner.aclose()

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
        request_params = dict(params or {})
        action = str(request_params.pop(BROWSER_ACTION_PARAM, "") or "").strip()
        target_page = request_params.pop(BROWSER_PAGE_PARAM, "")
        result = await self._inner.request(
            method,
            url,
            params=request_params or None,
            json_body=json_body,
            headers=headers,
            max_bytes=max_bytes,
        )
        # 只在**取回成功但内容是空壳**时升级。取回失败（被限流、超时）说明问题在传输上，
        # 换个浏览器重取一样会失败，只是白花几秒。
        # robots.txt 是给解析器读的规则文本，不是需要执行脚本的网页。真实站点经常用 HTTP 200
        # 返回一个 HTML 版 404；若把它交给浏览器升级，浏览器不可用时会把一次可解析的规则读取
        # 误报成“探测被阻断”。
        if not result.ok or _is_robots_url(url) or (not action and not needs_rendering(result.text)):
            return result

        client = self._client_factory()
        if client is None:
            return FetchResult(
                block=result.block,
                status_code=result.status_code,
                text=result.text,
                # 措辞只说**确定的事**：拿不到客户端可能是没启动，也可能是别的原因，
                # 这里判不出是哪个，所以不写"没有在运行"这种替用户下结论的话——
                # 上一版就是这么写的，而当时真实原因是个导入错误，那句话把人引到了
                # 一个跟问题无关的地方（去投递台点启动，点几次都没用）。
                detail=(
                    f"{result.detail}；这一页需要浏览器渲染才有内容，"
                    "而这次没能用上浏览器——请确认它已启动后重试"
                ).strip("；"),
                headers=result.headers,
            )

        browser_params = dict(request_params)
        if action:
            browser_params[BROWSER_ACTION_PARAM] = action
        if target_page:
            browser_params[BROWSER_PAGE_PARAM] = target_page
        rendered = await BrowserRenderedHttp(client, wait=self._wait).request(
            method, url, params=browser_params or None
        )
        if rendered.ok:
            logger.info("HTTP 取回是空壳，改用浏览器渲染成功")
            return rendered
        # 升级也失败：把两条原因都带上，用户才知道到底卡在哪一步。
        return FetchResult(
            block=rendered.block,
            status_code=rendered.status_code,
            detail=f"浏览器渲染失败（{rendered.detail}）；HTTP 取回的内容也读不出岗位",
        )


__all__ = [
    "MAX_BYTES",
    "RENDER_WAIT",
    "BrowserRenderedHttp",
    "BrowserUpgradeHttp",
    "RenderBlocked",
    "RenderFailed",
]
