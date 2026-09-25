"""阻断识别：把"取回的东西其实不是内容"这件事判出来。

**为什么单独成模块且全是纯函数**：这是对账结论的直接输入，判错的方向性代价不对称——

- **假阳性**（把正常页面判成阻断）→ 结论保守地降级为「无法确认」。用户看到的是"这次没抓准"，
  可以重试；
- **假阴性**（把阻断当成正常内容）→ 结论会**自信地报「已确认为全量」**，而实际上一条都没抓到。
  用户据此以为自己投完了所有岗位。

所以这里的取向是**宁可多判阻断**，但markers 必须足够具体，否则功能会退化成"永远无法确认"。
两边都不能走极端，所以 marker 只用**明确的整句或协议特征**，绝不用"登录""验证"这种单词——
导航栏里那个「登录」链接会让每一次采集都变成"需要登录"。

纯函数还有一个直接好处：这些判据能用真实抓到的页面原文离线回归（见
``services/browser/sample_recorder.py`` 的录制机制）。
"""
from __future__ import annotations

from .html_text import html_to_text
from ....models.official import (
    BLOCK_CAPTCHA,
    BLOCK_LOGIN,
    BLOCK_NONE,
    BLOCK_SOFT,
)

# 人机校验页的**整句**特征：在页面的**可见文字**里出现才算数。
# **用整句、不用单词**——导航栏里一个「登录」链接会让每次采集都误判。
CAPTCHA_TEXT_MARKERS = (
    "请完成安全验证",
    "请进行安全验证",
    "安全验证中",
    "人机验证",
    "滑动验证",
    "拖动滑块",
    "验证码错误",
    "请输入验证码",
    "点击完成验证",
    "are you a human",
    "verify you are human",
    "checking your browser",
)

# 人机校验的**库名 / 协议特征**。它们**不是**"这一页是人机校验"的证据：
# ``challenge-platform`` 是 Cloudflare 给**每个**受保护页面都注入的脚本，
# ``recaptcha`` / ``hcaptcha`` / ``turnstile`` 是任何带表单的正常页面都会加载的组件——
# 连样式表里一条 ``.g-recaptcha div{...}`` 都能命中。
#
# 所以它们只在**正文几乎为空**时才算数：真的人机校验页就是"几乎没有内容 + 加载了校验脚本"
# 这两件事同时成立。实测过的一次误判：某招聘板（728 KB、22 个岗位链接的正常列表页）被判成
# 人机校验——内联脚本里的 ``challenge-platform`` 与一条 CSS 里的 ``recaptcha``，于是那个
# **站点类型整体不可采**。判"被阻断"不是保守，是直接把源废掉。
CAPTCHA_SCRIPT_MARKERS = (
    "cf-challenge",
    "challenge-platform",
    "geetest",
    "hcaptcha",
    "recaptcha",
    "turnstile",
    "px-captcha",
)

# 登录墙特征。**「登录」两个字本身不是特征**——顶栏一个「登录」链接会让每次采集都误判。
LOGIN_MARKERS = (
    "请先登录",
    "请登录后",
    "登录后查看",
    "登录后可见",
    "未登录",
    "登录已过期",
    "登录状态失效",
    "sign in to continue",
    "please sign in",
    "login required",
    "session expired",
    "unauthorized",
)

# 空壳页特征：页面存在、状态码正常，但内容要靠 JS 渲染而挂载点里什么都没有。
# 这类要配合"正文很短"一起判，单独出现不足以定性（正常页面也可能有 noscript）。
SHELL_MARKERS = (
    "you need to enable javascript",
    "请开启 javascript",
    "请启用 javascript",
    "requires javascript",
    "enable javascript to continue",
)

# 正文短于此长度且带空壳特征，才判为软封禁。
_SHELL_MAX_TEXT_CHARS = 2_000

# 库名特征（``CAPTCHA_SCRIPT_MARKERS``）配合的正文长度上限。**比空壳那条严得多**：
# 人机校验页的正文是一两句话（实测一个典型的拦截页只有 58 个字符），而任何一个真的列表页
# 都在几百字符以上。取 300 是两侧余量都很大——用 2000 会把内容不多的正常页面一起判进去，
# 那正是这条判据要避免的。
_CAPTCHA_SCRIPT_MAX_TEXT_CHARS = 300


def _contains_any(haystack: str, needles: tuple[str, ...]) -> str:
    """返回命中的第一个特征（小写比较），没命中返回空串。"""
    for needle in needles:
        if needle in haystack:
            return needle
    return ""


def looks_like_html(text: str) -> bool:
    """粗判响应体是不是 HTML。用于"期望 JSON 却拿到网页"这类协议错配。

    **判据是"第一个非空白字符是 ``<``"，不是"含有 ``<html``"**：省略 ``<html>`` 标签的
    页面很常见（片段、服务端模板拼接的局部页、部分 CMS 输出），要求那个标签会把合法网页
    判成"不是网页"，而调用方拿到这个结论会直接放弃这一页。
    """
    stripped = text.lstrip()
    return stripped.startswith("<")


def classify_html(text: str) -> str:
    """给一段 HTML 判阻断分类；正常内容返回 ``BLOCK_NONE``。

    只对**取回的正文**做判断，不涉及状态码（状态码那部分在 ``http.py``）。顺序有意为之：
    人机校验 → 登录墙 → 空壳页，因为一个页面可能同时像好几种，而前者的结论更具体、
    对用户更可操作（"去浏览器里过一下验证" 比 "内容疑似没渲染出来" 有用得多）。

    **判据一律跑在"可见文字"上，不跑在原始标记上。** 这一条是被真实站点打出来的：整句特征
    在 ``<script>`` / ``<style>`` 里同样会命中，而那里恰好堆着别人的库名——Cloudflare 的
    ``challenge-platform`` 脚本每个受保护页面都有，带表单的页面都加载 ``recaptcha``。
    跑到标记上的结果是"整个站点类型被误判成阻断"，而判成阻断对用户来说**不是保守，是源废了**。
    """
    visible = html_to_text(text).casefold()
    lowered = text.casefold()

    if _contains_any(visible, CAPTCHA_TEXT_MARKERS):
        return BLOCK_CAPTCHA
    if _contains_any(visible, LOGIN_MARKERS):
        return BLOCK_LOGIN
    # 库名特征要**配合"正文几乎为空"**才作数：见 ``CAPTCHA_SCRIPT_MARKERS`` 的说明。
    if (
        len(visible) < _CAPTCHA_SCRIPT_MAX_TEXT_CHARS
        and _contains_any(lowered, CAPTCHA_SCRIPT_MARKERS)
    ):
        return BLOCK_CAPTCHA

    # 空响应体：状态码 200 却一个字符都没有。它**不是**"这里没有岗位"，而是"我们什么都没
    # 拿到"，必须判成不可信。少数接口用空响应体表示翻到底，那种站点由适配器在调用本函数
    # **之前**按 status_code 处理（适配器知道自己的契约，本函数不知道）。
    if not text.strip():
        return BLOCK_SOFT

    shell_hit = _contains_any(lowered, SHELL_MARKERS)
    if shell_hit and len(text.strip()) < _SHELL_MAX_TEXT_CHARS:
        return BLOCK_SOFT
    # 正文几乎为空且带 HTML 骨架：多半是"渲染前"的页面。阈值取很小，避免把内容少的
    # 正常页面判进来——一个真的有岗位的页面不会只有几十个字符。
    if len(text.strip()) < 200 and "<" in text:
        return BLOCK_SOFT

    return BLOCK_NONE


def classify_json_payload(payload: object) -> str:
    """给一次"期望是 JSON 但解析失败/结构异常"的取回判分类。

    调用方在 ``json()`` 返回 ``None`` 时用它定性：能拿到正文却解析不出 JSON，通常是 WAF
    返回了一个 200 的错误页或空响应，而不是"这里没有岗位"。
    """
    del payload  # 目前只按"解析失败"这唯一事实定性，参数留作将来区分结构异常
    return BLOCK_SOFT


__all__ = [
    "CAPTCHA_SCRIPT_MARKERS",
    "CAPTCHA_TEXT_MARKERS",
    "LOGIN_MARKERS",
    "SHELL_MARKERS",
    "classify_html",
    "classify_json_payload",
    "looks_like_html",
]
