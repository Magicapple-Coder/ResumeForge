"""官网采集地基：阻断分类与受限取回层。

这组用例守的是**对账结论的可信度**，所以断言的重点不是"函数返回了什么"，而是
"什么情况会被判成不可信"。其中三条最关键：

- 顶栏的「登录」链接**不能**把一次正常采集判成登录墙（否则功能永远报"无法确认"）；
- **跳转**到内网地址要和直接请求内网地址一样被拒（否则 SSRF 防护可被绕过）；
- 状态码 200 但内容是验证码页时**必须**判成阻断（否则会把拦截读成"这里没有岗位"）。
"""
from __future__ import annotations

import httpx
import pytest

from app.models.official import (
    BLOCK_CAPTCHA,
    BLOCK_FORBIDDEN,
    BLOCK_LOGIN,
    BLOCK_NETWORK,
    BLOCK_NONE,
    BLOCK_NOT_FOUND,
    BLOCK_RATE_LIMIT,
    BLOCK_SOFT,
    BLOCK_TIMEOUT,
    BLOCK_UNKNOWN,
    VERDICT_COMPLETE,
    VERDICT_INCOMPLETE,
    VERDICT_LABELS,
    VERDICT_UNKNOWN,
    VERDICTS,
    is_transport_failure,
)
from app.services.sites.official import blocking
from app.services.sites.official.http import HttpxFeedHttp

# 一个"看起来像真的"招聘列表页：有导航、有岗位、也有一个「登录」链接。
NORMAL_LISTING_PAGE = """
<!doctype html><html lang="zh-CN"><head><title>招聘 - 示例公司</title></head>
<body>
<nav><a href="/">首页</a><a href="/about">关于</a><a href="/login">登录</a></nav>
<main>
  <h1>社会招聘</h1>
  <ul>
    <li><a href="/jobs/1">大模型应用开发工程师</a><span>北京</span></li>
    <li><a href="/jobs/2">算法工程师</a><span>上海</span></li>
    <li><a href="/jobs/3">后端开发工程师</a><span>深圳</span></li>
    <li><a href="/jobs/4">数据分析师</a><span>杭州</span></li>
    <li><a href="/jobs/5">前端开发工程师</a><span>成都</span></li>
  </ul>
</main>
</body></html>
"""

CAPTCHA_PAGE = """
<!doctype html><html><head><title>安全验证</title></head>
<body><div class="geetest_panel">请完成安全验证后继续访问</div></body></html>
"""

LOGIN_WALL_PAGE = """
<!doctype html><html><head><title>登录</title></head>
<body><h1>请先登录后查看完整岗位信息</h1></body></html>
"""


@pytest.fixture(autouse=True)
def fake_dns(fake_public_dns):
    """本文件的用例都要走真实 SSRF 防护，因此都要固定域名解析（夹具在 conftest）。"""
    return fake_public_dns


def _client(handler, **kwargs) -> HttpxFeedHttp:
    return HttpxFeedHttp(transport=httpx.MockTransport(handler), **kwargs)


# ===== 阻断识别（纯函数）=====


def test_normal_listing_page_is_not_blocked():
    """顶栏有「登录」链接的**正常**招聘页必须判为正常。

    这是本模块最容易写错、后果最隐蔽的一条：marker 一旦包含「登录」这种单词，每次采集都会
    产出一个假的登录墙，对账于是永远停在「无法确认」，功能看起来"很保守"，实际是坏了。
    """
    assert blocking.classify_html(NORMAL_LISTING_PAGE) == BLOCK_NONE


def test_captcha_page_is_detected():
    assert blocking.classify_html(CAPTCHA_PAGE) == BLOCK_CAPTCHA


def test_login_wall_is_detected():
    assert blocking.classify_html(LOGIN_WALL_PAGE) == BLOCK_LOGIN


def test_javascript_shell_is_detected_as_soft_block():
    shell = (
        "<!doctype html><html><body><div id='root'></div>"
        "<noscript>You need to enable JavaScript to run this app.</noscript></body></html>"
    )
    assert blocking.classify_html(shell) == BLOCK_SOFT


def test_empty_body_is_soft_block():
    assert blocking.classify_html("   ") == BLOCK_SOFT


@pytest.mark.parametrize(
    "text",
    [
        "<!doctype html><html><body>x</body></html>",
        "<html><body>x</body></html>",
        # 省略 <html> 的页面很常见：片段、服务端模板拼的局部页、部分 CMS 输出。
        # 要求这个标签会把合法网页判成"不是网页"，而调用方拿到这个结论会直接放弃这一页。
        "<div><a href='/jobs/1'>岗位</a></div>",
        '  \n <p>招聘</p>',
    ],
)
def test_looks_like_html_accepts_markup(text):
    assert blocking.looks_like_html(text) is True


@pytest.mark.parametrize("text", ['{"jobs": []}', "%PDF-1.4", "", "   ", "纯文本，没有标记"])
def test_looks_like_html_rejects_non_markup(text):
    assert blocking.looks_like_html(text) is False


def test_captcha_wins_over_login_when_both_present():
    """两类特征同时出现时取更具体的那个：告诉用户"去过验证"比"去登录"更可操作。"""
    both = "<html><body>请先登录请完成安全验证</body></html>"
    assert blocking.classify_html(both) == BLOCK_CAPTCHA


# ===== 受限取回 =====


async def test_private_target_is_rejected_without_any_request(fake_dns):
    """直接请求内网地址：拒绝，且**一个字节都不发出去**。"""
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return httpx.Response(200, text="should never happen")

    async with _client(handler) as client:
        result = await client.request("GET", "http://127.0.0.1:8080/jobs")

    assert result.block == BLOCK_FORBIDDEN
    assert sent == []


async def test_redirect_to_private_address_is_rejected(fake_dns):
    """跳转到内网要和直接请求内网一样被拦。

    ``follow_redirects=True`` 交给 httpx 内部跟跳转时这一步是**不校验**的——一个公网地址
    就能把本机应用变成打内网的跳板。本模块手动跟跳转正是为了堵这个口子。
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://internal.example/secret"})

    async with _client(handler) as client:
        result = await client.request("GET", "https://careers.example/jobs")

    assert result.block == BLOCK_FORBIDDEN
    # 诊断带上主机名是有用的（用户要知道拦的是哪个目标），但**路径与查询串不能外泄**。
    assert "internal.example" in result.detail
    assert "/secret" not in result.detail


async def test_rate_limit_is_classified_and_hints_retry_after(fake_dns):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "120"}, text="slow down")

    async with _client(handler) as client:
        result = await client.request("GET", "https://careers.example/jobs")

    assert result.block == BLOCK_RATE_LIMIT
    assert "120" in result.detail
    assert is_transport_failure(result.block) is True


async def test_forbidden_and_login_statuses_are_distinguished(fake_dns):
    statuses = {403: BLOCK_FORBIDDEN, 401: BLOCK_LOGIN}

    for status_code, expected in statuses.items():
        def handler(request: httpx.Request, code=status_code) -> httpx.Response:
            return httpx.Response(code, text="nope")

        async with _client(handler) as client:
            result = await client.request("GET", "https://careers.example/jobs")
        assert result.block == expected, status_code


async def test_404_is_a_negative_answer_not_a_block(fake_dns):
    """404 表示"这个端点不存在"，不是"我们被拦了"。

    探测依赖这个区别：它要把"这家公司不用这套系统"和"这家公司拦了我们"分开，混在一起
    会让探测把被风控的站点误判成不匹配。
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    async with _client(handler) as client:
        result = await client.request("GET", "https://api.example/v1/boards/nope/jobs")

    assert result.block == BLOCK_NOT_FOUND
    assert is_transport_failure(BLOCK_NOT_FOUND) is False


async def test_http_200_with_captcha_body_is_blocked(fake_dns):
    """**状态码 200 不等于拿到了内容。**

    拦截页普遍以 200 返回；不识别它，对账就会把"被拦住"读成"这里没有岗位"，然后自信地
    报告"已确认为全量"。
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=CAPTCHA_PAGE, headers={"content-type": "text/html"})

    async with _client(handler) as client:
        result = await client.request("GET", "https://careers.example/jobs")

    assert result.block == BLOCK_CAPTCHA
    assert is_transport_failure(result.block) is True


async def test_oversized_body_escalates_to_unverified(fake_dns):
    """截断的响应必须升格成"不可信"。

    否则对账会拿一份缺了尾巴的数据去对总数，把站点的问题算成我们自己的漏抓。
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="x" * 500, headers={"content-type": "application/json"})

    async with _client(handler, max_bytes=100) as client:
        result = await client.request("GET", "https://api.example/v1/jobs")

    assert result.block == BLOCK_UNKNOWN
    assert "截断" in result.detail


async def test_timeout_is_classified(fake_dns):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow")

    async with _client(handler) as client:
        result = await client.request("GET", "https://careers.example/jobs")

    assert result.block == BLOCK_TIMEOUT


async def test_connection_error_is_classified(fake_dns):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    async with _client(handler) as client:
        result = await client.request("GET", "https://careers.example/jobs")

    assert result.block == BLOCK_NETWORK


async def test_non_textual_response_is_rejected(fake_dns):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"})

    async with _client(handler) as client:
        result = await client.request("GET", "https://careers.example/jobs")

    assert result.block == BLOCK_UNKNOWN
    assert "image/png" in result.detail


async def test_server_error_is_a_transport_failure_not_an_empty_answer(fake_dns):
    """5xx 绝不能读成"这里没有更多了"。

    站点故障与"列表到底了"是完全不同的两件事，而对账只看后者就会把一次被截断的采集
    报成"已确认为全量"。
    """
    for status_code in (500, 502, 503):
        def handler(request: httpx.Request, code=status_code) -> httpx.Response:
            return httpx.Response(code, text="oops")

        async with _client(handler) as client:
            result = await client.request("GET", "https://api.example/v1/jobs")
        assert result.block == BLOCK_UNKNOWN, status_code
        assert is_transport_failure(result.block) is True
        assert str(status_code) in result.detail


async def test_unexpected_status_is_not_silently_treated_as_success(fake_dns):
    """没见过的状态码走"未知异常"，不装作成功。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(418, text="teapot")

    async with _client(handler) as client:
        result = await client.request("GET", "https://api.example/v1/jobs")

    assert result.block == BLOCK_UNKNOWN
    assert "418" in result.detail


async def test_retry_after_is_only_quoted_when_it_is_a_number(fake_dns):
    """``Retry-After`` 也可能是 HTTP 日期串，直接写进"建议 N 秒后重试"会变成一句胡话。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429, headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}, text="slow"
        )

    async with _client(handler) as client:
        result = await client.request("GET", "https://api.example/v1/jobs")

    assert result.block == BLOCK_RATE_LIMIT
    assert "建议" not in result.detail


async def test_missing_content_type_does_not_reject_a_valid_response(fake_dns):
    """站点没给 Content-Type 时**不能**据此拒绝：那是把对方的疏忽当成我们的失败。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"jobs": []}')

    async with _client(handler) as client:
        result = await client.request("GET", "https://api.example/v1/jobs")

    assert result.ok is True


async def test_redirect_without_location_is_not_a_success(fake_dns):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302)

    async with _client(handler) as client:
        result = await client.request("GET", "https://api.example/v1/jobs")

    assert result.block == BLOCK_UNKNOWN
    assert "Location" in result.detail


async def test_redirect_loop_is_given_up_on(fake_dns):
    """无限跳转必须被截断，而且要如实报"放弃了"而不是转成某个看似正常的结果。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://api.example/next"})

    async with _client(handler, max_redirects=2) as client:
        result = await client.request("GET", "https://api.example/v1/jobs")

    assert result.block == BLOCK_UNKNOWN
    assert "跳转次数" in result.detail


async def test_custom_headers_are_merged_over_the_defaults(fake_dns):
    """适配器可以覆盖默认请求头——有的接口对 Accept 有要求。"""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.headers))
        return httpx.Response(200, text="{}", headers={"content-type": "application/json"})

    async with _client(handler) as client:
        await client.request(
            "GET", "https://api.example/v1/jobs", headers={"Accept": "application/vnd.custom+json"}
        )

    assert seen["accept"] == "application/vnd.custom+json"
    # 没被覆盖的默认头仍在。
    assert "resumeforge" in seen["user-agent"].casefold()


async def test_successful_json_body_is_passed_through(fake_dns):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text='{"jobs": []}', headers={"content-type": "application/json"}
        )

    async with _client(handler) as client:
        result = await client.request("GET", "https://api.example/v1/jobs")

    assert result.ok is True
    assert result.json() == {"jobs": []}
    assert result.json is not None


# ===== 分类集合的语义 =====


def test_transport_failures_exclude_negative_answers():
    """「不知道那边有什么」才是传输侧失败；"明确没有"不是。

    这条集合是对账终止判定的分流依据，多一个或少一个都会让结论偏一个方向。
    """
    assert is_transport_failure(BLOCK_NONE) is False
    assert is_transport_failure(BLOCK_NOT_FOUND) is False

    for block in (BLOCK_RATE_LIMIT, BLOCK_FORBIDDEN, BLOCK_CAPTCHA, BLOCK_LOGIN, BLOCK_SOFT):
        assert is_transport_failure(block) is True, block

    assert is_transport_failure(BLOCK_TIMEOUT) is True
    assert is_transport_failure(BLOCK_NETWORK) is True
    assert is_transport_failure(BLOCK_UNKNOWN) is True


def test_every_block_has_a_user_facing_label():
    """分类要展示给用户，缺标签会直接漏出内部枚举值。"""
    from app.models.official import BLOCK_LABELS

    for block in (
        BLOCK_NONE,
        BLOCK_RATE_LIMIT,
        BLOCK_FORBIDDEN,
        BLOCK_CAPTCHA,
        BLOCK_LOGIN,
        BLOCK_SOFT,
        BLOCK_TIMEOUT,
        BLOCK_NETWORK,
        BLOCK_NOT_FOUND,
        BLOCK_UNKNOWN,
    ):
        assert BLOCK_LABELS.get(block), block


def test_verdicts_are_three_states_without_percentages():
    """对账结论只有三态，**不出百分比分数**——与「进度不显示百分比」同一取向。"""
    assert set(VERDICTS) == {VERDICT_COMPLETE, VERDICT_INCOMPLETE, VERDICT_UNKNOWN}
    for verdict in VERDICTS:
        assert VERDICT_LABELS.get(verdict), verdict


def test_a_normal_page_that_merely_loads_a_captcha_library_is_not_blocked():
    """**判据跑在可见文字上，不跑在原始标记上。**（真实站点打出来的缺陷）

    Cloudflare 给每个受保护页面都注入 ``challenge-platform`` 脚本，带表单的页面都会加载
    ``recaptcha``——连样式表里一条 ``.g-recaptcha div{...}`` 都能命中。从前这两样在原始 HTML
    里一匹配就判"人机校验"，于是一整类站点（实测：一个 728 KB、22 个岗位链接的招聘板）
    被判成阻断、连采集按钮都点不动。

    判成阻断对用户**不是保守，是源废了**——保守的降级是"这次没抓准、可以重试"，
    而"识别不出来"意味着这个源根本进不去。
    """
    page = (
        "<!doctype html><html><head>"
        "<script>var _cf={'t':'x'};var a=document.createElement('script');"
        "a.src='/cdn-cgi/challenge-platform/scripts/jsd/main.js';"
        "document.getElementsByTagName('head')[0].appendChild(a);</script>"
        "<style>.g-recaptcha div,.h-captcha-spacing{display:block;margin:0 auto}</style>"
        "</head><body>"
        "<h1>Open roles</h1>"
        + "".join(
            f'<li><a href="/demo/{index}">Engineer {index}</a> · Remote</li>' for index in range(20)
        )
        + "</body></html>"
    )

    assert blocking.classify_html(page) == BLOCK_NONE


def test_a_real_challenge_page_is_still_caught():
    """反过来：真的校验页仍然要判出来——**几乎没有内容 + 加载了校验脚本**两条同时成立。

    库名本身不算证据，但"空白页 + 校验脚本"就是校验页的样子；少了这一半，整个判据会退化成
    "永远判不出人机校验"。
    """
    page = (
        "<!doctype html><html><head><title>Just a moment...</title>"
        "<script src='/cdn-cgi/challenge-platform/scripts/jsd/main.js'></script>"
        "</head><body><div id='cf-wrapper'></div></body></html>"
    )

    assert blocking.classify_html(page) == BLOCK_CAPTCHA


def test_challenge_wording_in_visible_text_is_enough():
    """校验页把话写在正文里时，不需要任何脚本特征。"""
    page = "<html><body><h1>Verify you are human</h1></body></html>"

    assert blocking.classify_html(page) == BLOCK_CAPTCHA
