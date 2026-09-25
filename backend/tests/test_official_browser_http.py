"""HTTP 取回是空壳时改用真实浏览器重取。

**这一层最要紧的性质是"失败要留痕"**：升级失败时必须把原因写进结果，而不是安静地返回那个空壳。
空壳会被上层读成"这里没有岗位"，而真实原因是"我们没能渲染它"——那正是漏抓被伪装成正常结果
的典型形态。
"""
from __future__ import annotations

from typing import Any

import pytest

from app.models.official import (
    BLOCK_CAPTCHA,
    BLOCK_FORBIDDEN,
    BLOCK_NETWORK,
    BLOCK_NONE,
    BLOCK_RATE_LIMIT,
    BLOCK_TIMEOUT,
)
from app.services.browser.cdp_client import CdpClient, CdpError
from app.services.browser.page_ready import ReadyWait
from app.services.sites.official.base import FeedHttp, FetchResult
from app.services.sites.official.browser_http import (
    BrowserRenderedHttp,
    BrowserUpgradeHttp,
    RenderFailed,
)

URL = "https://acme.example/careers"
FAST_WAIT = ReadyWait(timeout=0.05, poll_interval=0.001)


@pytest.fixture(autouse=True)
def _public_dns(fake_public_dns):
    """浏览器取回同样要过 SSRF 防护，而那道防护要解析域名。"""
    return fake_public_dns

SPA_SHELL = '<html><body><div id="root"></div><script src="/a.js"></script></body></html>'
RENDERED = (
    "<html><body><div id='root'><main><h1>社会招聘</h1><ul>"
    + "".join(f"<li><a href='/jobs/{i}'>岗位 {i}</a></li>" for i in range(20))
    + "</ul></main></div></body></html>"
)


class FakeCdp(CdpClient):
    """一个有"当前页面 HTML"的假浏览器。

    ``content_html`` 是**清掉样式文本那一份**（真实浏览器里由取正文的脚本在克隆节点上做）。
    这个假实现按表达式里有没有 ``cloneNode`` 分派，与真实浏览器按脚本内容返回不同结果一致
    ——写死成"两个脚本返回同一个值"的话，"取回的是清过样式的那一份"就没法验了。
    """

    def __init__(
        self,
        *,
        html: str = RENDERED,
        content_html: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.html = html
        self.content_html = html if content_html is None else content_html
        self.error = error
        self.navigated: list[str] = []
        self.evaluations: list[str] = []

    def list_targets(self) -> list[dict[str, Any]]:  # pragma: no cover - 本模块用不到
        return []

    def new_tab(self, url: str = "about:blank") -> str:  # pragma: no cover
        return "t"

    def send(self, method, params=None, *, timeout=None) -> dict[str, Any]:  # pragma: no cover
        return {}

    def navigate(self, url: str, *, timeout: float | None = None) -> dict[str, Any]:
        if self.error is not None:
            raise self.error
        self.navigated.append(url)
        return {}

    def evaluate(self, expression: str, *, timeout: float | None = None) -> Any:
        self.evaluations.append(expression)
        if "cloneNode" in expression:
            return self.content_html
        return self.html


class PaginatedCdp(FakeCdp):
    """模拟一个点击「下一页」后替换列表 DOM 的分页器。"""

    PAGE_ONE = "<html><body><a href='/jobs/1'>岗位 1</a></body></html>"
    PAGE_TWO = "<html><body><a href='/jobs/2'>岗位 2</a></body></html>"
    PAGE_THREE = "<html><body><a href='/jobs/3'>岗位 3</a></body></html>"

    def __init__(self) -> None:
        super().__init__(html=self.PAGE_ONE)
        self.page = 1
        self.ensure_calls = 0

    def ensure_page_visible(self, *, timeout_seconds: float = 8.0) -> bool:
        del timeout_seconds
        self.ensure_calls += 1
        return True

    def evaluate(self, expression: str, *, timeout: float | None = None) -> Any:
        if "const wanted" in expression:
            self.page = min(self.page + 1, 3)
            self.html = {1: self.PAGE_ONE, 2: self.PAGE_TWO, 3: self.PAGE_THREE}[self.page]
            self.content_html = self.html
            return {"clicked": True}
        if "const active" in expression:
            return f"{self.page}|marker"
        return super().evaluate(expression, timeout=timeout)


class _Http(FeedHttp):
    def __init__(self, result: FetchResult) -> None:
        self._result = result
        self.calls: list[str] = []

    async def request(self, method, url, *, params=None, json_body=None, headers=None,
                      max_bytes=None):
        del method, params, json_body, headers, max_bytes
        self.calls.append(url)
        return self._result


# ===== 浏览器取回本身 =====


async def test_renders_and_returns_the_dom():
    client = FakeCdp()
    result = await BrowserRenderedHttp(client, wait=FAST_WAIT).request("GET", URL)

    assert result.ok is True
    assert "岗位 0" in result.text
    assert client.navigated == [URL]


async def test_returns_the_dom_with_inline_css_text_stripped():
    """取回的是**清掉 ``<style>`` 文本**的那一份，不是原样的 DOM。

    真实站点上踩到过：某招聘站整页 6.8 MB，其中 **5.8 MB 是 768 个 ``<style>`` 的文本**，
    ``<body>`` 只有 66 KB。而字节上限是**从头截**的，于是截出来的那 6 MB 全是样式表——
    正文连同全部岗位链接一起被切掉，上层看到的是"这一页一条站内链接都没有"。那是**一句关于
    页面的假话**：页面里明明有 18 个岗位链接，问题出在我们自己的截断上。

    没有任何一级抽取读 CSS 文本（``html_to_text`` 明确跳过 ``style``，结构化数据在 ``<script>``
    里，链接与文字在 DOM 结构里），所以清掉它不改变任何抽取结果。
    """
    css = "<style>" + ("body{margin:0}" * 50) + "</style>"
    with_css = f"<html><head>{css}</head><body><a href='/jobs/1'>岗位一</a></body></html>"
    without_css = "<html><head><style></style></head><body><a href='/jobs/1'>岗位一</a></body></html>"
    client = FakeCdp(html=with_css, content_html=without_css)

    result = await BrowserRenderedHttp(client, wait=FAST_WAIT).request("GET", URL)

    assert result.ok is True
    assert result.text == without_css
    assert "margin" not in result.text
    # 链接本身一个字都不能少——清的是样式，不是内容。
    assert "/jobs/1" in result.text


async def test_styles_are_stripped_on_a_copy_not_on_the_users_tab():
    """**在克隆节点上清**：投递台那个浏览器是用户自己的窗口，取回不能把它改花。

    这一条只能验到"脚本确实用了克隆"（JS 真正跑起来的行为由真实站点那次验证），
    但它是这条约束在离线用例里唯一可守的地方——写成直接改 ``document`` 的话，
    用户面前那个标签页会在采集期间被剥掉全部样式。
    """
    client = FakeCdp()
    await BrowserRenderedHttp(client, wait=FAST_WAIT).request("GET", URL)

    content_scripts = [item for item in client.evaluations if "querySelectorAll" in item]
    assert content_scripts, "没有取正文的那一步"
    for script in content_scripts:
        assert "cloneNode" in script


async def test_waits_until_the_page_actually_renders():
    """``navigate`` 只是让浏览器**开始**加载；立刻取 DOM 会拿到空壳。"""

    class SlowCdp(FakeCdp):
        def __init__(self) -> None:
            super().__init__(html=SPA_SHELL)
            self.polls = 0

        def evaluate(self, expression: str, *, timeout=None) -> Any:
            self.polls += 1
            # 前两次还没渲染完，第三次才有内容。
            return RENDERED if self.polls >= 3 else SPA_SHELL

    client = SlowCdp()
    result = await BrowserRenderedHttp(
        client, wait=ReadyWait(timeout=2.0, poll_interval=0.001)
    ).request("GET", URL)

    assert result.ok is True
    assert "岗位 0" in result.text
    assert client.polls >= 3, "应当在渲染出来之前反复探过"


async def test_timeout_is_reported_as_a_timeout_not_an_empty_page():
    """一直渲染不出来 → 超时分类，而不是"这一页是空的"。"""
    result = await BrowserRenderedHttp(FakeCdp(html=SPA_SHELL), wait=FAST_WAIT).request("GET", URL)

    assert result.block == BLOCK_TIMEOUT
    assert "渲染" in result.detail


async def test_captcha_during_rendering_stops_immediately():
    """渲染出来是验证码页时立刻失败，不傻等满超时（等满只是白白拖慢每一次采集）。"""
    captcha = "<html><body><div>请完成安全验证后继续访问</div></body></html>"
    result = await BrowserRenderedHttp(
        FakeCdp(html=captcha), wait=ReadyWait(timeout=5.0, poll_interval=0.001)
    ).request("GET", URL)

    # **分类要准**：它和"渲染预算不够"的下一步动作完全相反——
    # 前者交给用户手动过验证，后者值得重试或放宽预算。
    assert result.block == BLOCK_CAPTCHA
    assert "安全验证" in result.detail


async def test_browser_failure_is_classified():
    result = await BrowserRenderedHttp(
        FakeCdp(error=CdpError("连不上调试端口")), wait=FAST_WAIT
    ).request("GET", URL)

    assert result.block == BLOCK_NETWORK
    assert "浏览器" in result.detail


async def test_only_get_is_supported():
    """CDP 取回的本质是"打开这个地址再把 DOM 交出来"，没有别的动词——不假装支持。"""
    result = await BrowserRenderedHttp(FakeCdp(), wait=FAST_WAIT).request("POST", URL)
    assert result.block == BLOCK_NETWORK
    assert "GET" in result.detail


async def test_browser_action_clicks_the_next_page_and_waits_for_new_dom():
    client = PaginatedCdp()

    result = await BrowserRenderedHttp(client, wait=FAST_WAIT).request(
        "GET",
        URL,
        params={
            "__resumeforge_browser_action": "下一页",
            "__resumeforge_browser_page": "3",
        },
    )

    assert result.ok is True
    assert "岗位 3" in result.text
    assert "岗位 1" not in result.text
    assert client.page == 3
    assert client.ensure_calls == 2


async def test_private_addresses_are_refused():
    """**同样过 SSRF 防护**：把一个用户可控的地址交给浏览器去打开，与本机自己发请求是同一类
    风险——甚至更隐蔽，因为它带着用户的 Cookie 与内网可达性。"""
    client = FakeCdp()
    result = await BrowserRenderedHttp(client, wait=FAST_WAIT).request(
        "GET", "http://127.0.0.1:8080/admin"
    )

    assert result.block == BLOCK_FORBIDDEN
    assert client.navigated == [], "被拒绝的地址一个字节都不该交给浏览器"


# ===== 升级装饰器 =====


async def test_normal_pages_pass_through_untouched():
    """不是空壳就原样返回——升级只该在真的需要时发生，否则每一页都慢几秒。"""
    inner = _Http(FetchResult(block=BLOCK_NONE, status_code=200, text=RENDERED))
    upgraded: list[str] = []
    http = BrowserUpgradeHttp(inner, lambda: upgraded.append("called") or FakeCdp())

    result = await http.request("GET", URL)

    assert result.text == RENDERED
    assert upgraded == [], "正常页面不该去动浏览器"


async def test_transport_failures_are_not_upgraded():
    """取回失败（被限流、超时）说明问题在传输上——换个浏览器一样会失败，只是白花几秒。"""
    inner = _Http(FetchResult(block=BLOCK_RATE_LIMIT, status_code=429, detail="限流"))
    called: list[str] = []
    http = BrowserUpgradeHttp(inner, lambda: called.append("x") or FakeCdp())

    result = await http.request("GET", URL)

    assert result.block == BLOCK_RATE_LIMIT
    assert called == []


async def test_shell_is_upgraded_to_the_browser():
    inner = _Http(FetchResult(block=BLOCK_NONE, status_code=200, text=SPA_SHELL))
    client = FakeCdp()
    http = BrowserUpgradeHttp(inner, lambda: client, wait=FAST_WAIT)

    result = await http.request("GET", URL)

    assert result.ok is True
    assert "岗位 0" in result.text
    assert client.navigated == [URL]


async def test_missing_browser_is_reported_not_silently_empty():
    """**本模块最要紧的一条**：拿不到浏览器时，空壳不能被当成"这里没有岗位"。

    升级失败必须留下痕迹——否则漏抓会被伪装成一个合法的空结果。
    """
    inner = _Http(FetchResult(block=BLOCK_NONE, status_code=200, text=SPA_SHELL))
    http = BrowserUpgradeHttp(inner, lambda: None, wait=FAST_WAIT)

    result = await http.request("GET", URL)

    assert "浏览器" in result.detail
    assert "需要浏览器渲染" in result.detail
    # 这里**只能**说"没能用上"，不能说"浏览器没有在运行"：拿不到客户端可能是没启动，
    # 也可能是别的原因（导入坏了、CDP 连不上），这一层判不出是哪个。替用户下结论的措辞
    # 只会把他引到一个跟问题无关的地方——上一版就是"请在投递台启动它"，而当时真实原因
    # 是个导入错误，点几次启动都没用。
    assert "没有在运行" not in result.detail


async def test_failed_upgrade_carries_both_reasons():
    """升级也失败时，两条原因都要带上——用户才知道卡在哪一步。"""
    inner = _Http(FetchResult(block=BLOCK_NONE, status_code=200, text=SPA_SHELL))
    http = BrowserUpgradeHttp(
        inner, lambda: FakeCdp(error=CdpError("端口不通")), wait=FAST_WAIT
    )

    result = await http.request("GET", URL)

    assert result.ok is False
    assert "浏览器渲染失败" in result.detail
    assert "HTTP 取回" in result.detail


def test_render_failed_is_a_distinct_error_type():
    """它只在本模块内部流转（被转成 FetchResult），不是一个要往外抛的业务异常。"""
    assert issubclass(RenderFailed, Exception)


@pytest.mark.parametrize("html", [RENDERED, "<html><body><h1>404</h1></body></html>"])
async def test_pages_that_need_no_rendering_skip_the_browser(html):
    inner = _Http(FetchResult(block=BLOCK_NONE, status_code=200, text=html))
    called: list[str] = []
    http = BrowserUpgradeHttp(inner, lambda: called.append("x") or FakeCdp())

    await http.request("GET", URL)

    assert called == []
