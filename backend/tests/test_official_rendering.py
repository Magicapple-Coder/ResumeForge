"""判定一个页面要不要靠浏览器渲染。

判据两边都不能误伤，而**两个方向的后果差得很远**：

- 判成"要渲染"而其实不用 → 白开一次浏览器，慢几秒；
- 判成"不用渲染"而其实要 → 这一页什么都读不出来，而报告里不会有任何异常迹象
  （空列表是个合法结果），于是漏抓被伪装成"这里没有岗位"。

所以用例的重点是第二条：**SPA 空壳必须被认出来**，同时**正常的短页面不能被误判**。
"""
from __future__ import annotations

import pytest

from app.services.sites.official.rendering import needs_rendering

# 一个真实的 SPA 空壳：DOM 很小、页面结构完整，但内容要等 JS 渲染。
SPA_SHELL = (
    "<!doctype html><html><head><title>招聘</title></head>"
    '<body><div id="root"></div><script src="/static/app.js"></script></body></html>'
)

# 预渲染过的同一页：挂载点里已经有内容了。
PRERENDERED = (
    "<!doctype html><html><head><title>招聘</title></head><body>"
    '<div id="root"><main><h1>社会招聘</h1><ul>'
    + "".join(f'<li><a href="/jobs/{index}">岗位 {index}</a></li>' for index in range(20))
    + "</ul></main></div></body></html>"
)

RICH_PAGE = (
    "<html><body><main><h1>社会招聘</h1><p>"
    + "这是职位描述。" * 100
    + "</p></main></body></html>"
)


def test_spa_shell_needs_rendering():
    assert needs_rendering(SPA_SHELL) is True


def test_prerendered_page_does_not_need_rendering():
    """挂载点里有内容 = 已经渲染过了，不该白白再开一次浏览器。"""
    assert needs_rendering(PRERENDERED) is False


def test_content_rich_page_does_not_need_rendering():
    assert needs_rendering(RICH_PAGE) is False


@pytest.mark.parametrize(
    "html",
    [
        '<html><body><div id="app"></div></body></html>',
        '<html><body><div id="__next"></div></body></html>',
        '<html><body><main id="app-root"></main></body></html>',
    ],
)
def test_common_mount_points_are_recognised(html):
    assert needs_rendering(html) is True


def test_js_required_notice_is_recognised():
    html = (
        "<html><body><div id='x'></div>"
        "<noscript>You need to enable JavaScript to run this app.</noscript></body></html>"
    )
    assert needs_rendering(html) is True


def test_empty_framework_data_script_is_recognised():
    """框架的数据脚本在、里面却几乎没数据——服务端没有预渲染。"""
    html = (
        "<html><head><script id='__NEXT_DATA__' type='application/json'>{}</script></head>"
        "<body><div id='root'></div></body></html>"
    )
    assert needs_rendering(html) is True


def test_populated_data_script_with_rendered_dom_is_not_flagged():
    """数据脚本有内容 **且** DOM 已渲染 → 送去渲染纯属浪费。"""
    html = (
        "<html><head><script id='__NEXT_DATA__' type='application/json'>"
        '{"props":{"pageProps":{"jobs":[{"title":"岗位一"}]}}}</script></head>'
        "<body><div id='root'><h1>社会招聘</h1><ul><li>岗位一</li></ul></div></body></html>"
    )
    assert needs_rendering(html) is False


def test_data_script_alone_does_not_replace_rendering():
    """**数据脚本里有内容、不等于用户看得到内容。**

    这一页的 ``__NEXT_DATA__`` 带着完整首屏数据，但 ``#root`` 是空的——DOM 还没渲染。
    本模块不解析框架的私有数据格式，所以对它来说内容仍然要等浏览器渲染出来。
    """
    html = (
        "<html><head><script id='__NEXT_DATA__' type='application/json'>"
        '{"props":{"pageProps":{"jobs":[{"title":"岗位一"}]}}}</script></head>'
        "<body><div id='root'></div></body></html>"
    )
    assert needs_rendering(html) is True


# ===== 反过来：短但正常的页面不能被误判 =====


def test_short_but_ordinary_page_is_not_flagged():
    """**只要文字少就送去渲染是错的**：404 页、跳转页、真的没有岗位的空列表页都文字很少，
    而它们本来就有结论。判据必须同时要求"有前端渲染的痕迹"。"""
    for html in (
        "<html><body><h1>404 Not Found</h1><p>页面不存在</p></body></html>",
        "<html><body><p>该职位已下线</p></body></html>",
        "<html><body><ul></ul><p>当前没有在招岗位</p></body></html>",
        "<html><body>纯文本响应</body></html>",
    ):
        assert needs_rendering(html) is False, html


def test_empty_html_is_not_flagged():
    """空响应由阻断识别去管（那是"我们什么都没拿到"），不该在这里再判一次。"""
    assert needs_rendering("") is False
    assert needs_rendering("   ") is False


def test_class_accounts_are_not_mistaken_for_mount_points():
    """``class="app"`` 之类不是挂载点——按 id 认就是为了避开这种。"""
    html = "<html><body><div class='app'><p>内容</p></div></body></html>"
    assert needs_rendering(html) is False


# ===== 真实站点打出来的两种写法（2026-09 实测）=====


def test_mount_point_with_unquoted_attribute_is_recognised():
    """``<div id=app></div>``——**属性值不加引号**是压缩器最常见的写法。

    实测的一个真实招聘站（腾讯）整页只有 2238 个字符、可读文字 0，写法正是这样；
    只认带引号的形式会把它漏掉，于是那一页永远不渲染、永远读不出岗位，而报告里没有任何迹象。
    """
    html = '<!DOCTYPE html><html><head><title>搜索</title></head><body><div id=app></div>' \
           '<script src="/static/js/main.js"></script></body></html>'

    assert needs_rendering(html) is True


def test_mount_point_holding_only_a_comment_is_recognised():
    html = '<html><body><div id="app"><!--<?- html ?>--></div></body></html>'

    assert needs_rendering(html) is True


def test_a_page_whose_content_is_all_in_scripts_is_recognised():
    """**挂载点 id 是站点自己起的，穷举认不全。**

    实测的另一个真实招聘站把挂载点叫 ``bd``（不是 root/app/__nuxt 任何一个），整页 925 KB、
    可读文字 0——体积几乎全在脚本里。这条判据不看 id 叫什么：页面很大、文字几乎没有、
    体积都在脚本里，那就是内容还没渲染进来。
    """
    payload = "y" * 9000
    html = (
        '<html><body><div id="bd"><!--<?- html ?>--></div>'
        + f'<script>var data = {{"jobs": ["{payload}"]}};</script>' * 3
        + "</body></html>"
    )

    assert needs_rendering(html) is True


def test_a_small_page_with_a_couple_of_scripts_is_still_not_rendered():
    """反过来：文字很少、也带脚本，但脚本就那么点——那是正文，不是空壳。

    这条守的是成本：只要"文字少"就送去渲染，等于给每一次正常的空结果白开一次浏览器。
    """
    for html in (
        '<html><body><p>当前没有在招岗位</p><script src="/a.js"></script></body></html>',
        '<html><body>该职位已下线<script>track("x")</script></body></html>',
    ):
        assert needs_rendering(html) is False, html
