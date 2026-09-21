"""BOSS 页面选择器、页面探针与等待诊断。"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote, urlparse

from ...models.apply import (
    FAILURE_CAPTCHA_REQUIRED,
    FAILURE_LOGIN_REQUIRED,
    FAILURE_SELECTOR_INVALID,
)
from ..browser.cdp_client import CdpClient
from ..browser.page_ready import wait_for_page_state
from .base import SiteFailure

BOSS_KEY = "boss"
BOSS_DISPLAY_NAME = "BOSS直聘"
BOSS_HOSTS = ("zhipin.com",)
BOSS_ENTRY_URL = "https://www.zhipin.com/"

SELECTOR_SEARCH_CARD = (
    "li.job-card-box, .job-card-wrapper, .job-list-container [data-jobid], "
    ".search-job-result .job-card, ul.rec-job-list > li"
)
# 岗位详情链接。**必须要求以 ``.html`` 结尾**，这是实测出来的：
# 页头有一个站点自己的导航项「职位搜索」，它的 href 正好是 ``https://www.zhipin.com/job_detail/``
# ——没有岗位 id、也没有 ``.html``，却能被 ``a[href*="/job_detail/"]`` 命中。它比岗位卡片**先**
# 渲染出来（实测 0.66s vs 卡片 ~2s+），于是"页面已就绪"被提前判真、网络订阅窗口随即关闭，
# joblist 接口（此时还没发出）永远收不到，整条"网络优先"路径静默失效、退回 DOM，最后采到的是
# 那条导航链接本身（标题「职位搜索」）。加上 ``[href$=".html"]`` 后两条链接被精确区分开。
# 常量本身仍保持"只认链接形状、不认 class"，卡片改版时这条兜底依然有效。
SELECTOR_JOB_LINK = 'a[href*="/job_detail/"][href$=".html"]'
SELECTOR_SEARCH_TITLE = "a.job-name, .job-name, .job-title"
SELECTOR_SEARCH_COMPANY = "span.boss-name, .company-name, .company-info .name"
SELECTOR_SEARCH_SALARY = ".salary, .red, .job-salary, .salary-text, [class*='salary']"
SELECTOR_SEARCH_LOCATION = "span.company-location, .job-area, .job-card-right .job-area"
SELECTOR_SEARCH_LINK = f"a.job-name, {SELECTOR_JOB_LINK}"
SELECTOR_SEARCH_NEXT = ".options-pages a:last-child, a.next"
SELECTOR_JOB_DESCRIPTION = (
    ".job-sec-text, .job-detail-section .text, [data-testid='job-description'], "
    ".job-detail-content"
)
SELECTOR_JOB_REQUIREMENTS = (
    "[data-testid='job-requirements'], .job-requirements, .job-detail-section.requirements .text"
)
SELECTOR_APPLY_ENTRY = (
    "a.btn-startchat, button.btn-startchat, .op-btn-chat, .btn-chat, "
    "[data-testid*='chat'], [class*='btn-startchat']"
)
SELECTOR_GREETING_INPUT = (
    ".dialog-container textarea, textarea.chat-input, #chat-input, "
    ".chat-input[contenteditable='true'], "
    "[contenteditable='true'][role='textbox'], "
    "[class*='editor'][contenteditable='true']"
)
# 现版聊天页（/web/geek/chat）的发送按钮是 ``<button type="send" class="... btn-send">``，
# 空内容时带 ``disabled`` class（不是 disabled 属性）；旧弹层选择器保留以兼容。
# 2026-09-20 真实发现的新形态：**新会话不跳聊天页**，而是详情页弹出「打招呼」对话框
# （``.dialog-wrap.startchat-dialog``），其发送按钮是 ``div.send-message``——不是 button、
# 类名不含 btn，全靠类选择器兜住（真实 DOM 实测）。
SELECTOR_GREETING_SEND = (
    "button.btn-send, button[type='send'], .dialog-container .btn-send, "
    ".chat-container .btn-send, .btn-sure-v2, .dialog-container .send-message, "
    ".send-message, "
    "button[aria-label*='发送'], [data-testid*='send']"
)
# 本人已发送消息的气泡：现版是 ``.message-item.item-myself``，旧版/其他容器一并保留。
# 系统消息（.item-system，如"你撤回了一条消息"）绝不能算本人消息。
SELECTOR_MY_MESSAGE = (
    ".message-item.item-myself, .message-item.myself, .message-item.is-self, "
    ".chat-message.is-self, [data-from=self]"
)
# 点击沟通入口后整页跳转到的聊天页路径。
CHAT_PAGE_PATH = "/web/geek/chat"
SELECTOR_SUBMIT_BUTTON = ".btn-submit, .btn-sure"
SELECTOR_FILE_INPUT = "input[type=file]"
SELECTOR_CAPTCHA = ".geetest_panel, .geetest_box, #nc_1_wrapper, .verify-wrap"
SELECTOR_LOGIN = ".login-dialog, .sign-form, .login-panel"
SELECTOR_SEARCH_EMPTY = (
    ".job-empty-wrapper, .search-empty, .empty-tip, .job-list-empty, .empty-wrapper"
)
SELECTOR_DETAIL_READY = (
    ".job-sec-text, .job-detail-section, .job-detail-box, "
    ".job-detail-body, .job-detail-content, [class*='job-detail'] .text"
)
SELECTOR_SEARCH_READY = f"{SELECTOR_SEARCH_CARD}, {SELECTOR_JOB_LINK}"

_SELECTORS = {
    "search_card": SELECTOR_SEARCH_CARD,
    "search_title": SELECTOR_SEARCH_TITLE,
    "search_company": SELECTOR_SEARCH_COMPANY,
    "search_salary": SELECTOR_SEARCH_SALARY,
    "search_location": SELECTOR_SEARCH_LOCATION,
    "search_link": SELECTOR_SEARCH_LINK,
    "search_next": SELECTOR_SEARCH_NEXT,
    "job_description": SELECTOR_JOB_DESCRIPTION,
    "job_requirements": SELECTOR_JOB_REQUIREMENTS,
    "apply_entry": SELECTOR_APPLY_ENTRY,
    "greeting_input": SELECTOR_GREETING_INPUT,
    "greeting_send": SELECTOR_GREETING_SEND,
    "my_message": SELECTOR_MY_MESSAGE,
    "chat_page_path": CHAT_PAGE_PATH,
    "submit_button": SELECTOR_SUBMIT_BUTTON,
    "file_input": SELECTOR_FILE_INPUT,
    "captcha": SELECTOR_CAPTCHA,
    "login": SELECTOR_LOGIN,
    "search_empty": SELECTOR_SEARCH_EMPTY,
    "detail_ready": SELECTOR_DETAIL_READY,
}


def _js(selector: str) -> str:
    return json.dumps(selector)


def _blocker_js() -> str:
    """"是否被拦截"的公共 JS 片段：定义 ``CAPTCHA`` / ``LOGIN`` 与 ``shown()``。

    **必须判可见性，只看存在与否是个致命的误报源。** BOSS 把登录弹窗的整套模板
    （``.sign-form.sign-sms`` / ``-scan`` / ``-register`` / ``-miniapp`` / ``-succ`` /
    ``-welcome`` 共 6 个）直接写在页面标记里、默认隐藏；岗位详情页尤其明显。用
    ``!!document.querySelector(LOGIN)`` 判定的话，**每打开一个岗位详情页都会被判成
    "需要登录"**，于是整批采集在抓完列表、开始补详情时当场失败——而用户其实是登录着的。
    实测：登录状态下打开任意详情页，这 6 个节点都在，但 ``getClientRects().length`` 全为 0。
    """
    return "".join(
        [
            f"  const CAPTCHA = {_js(_SELECTORS['captcha'])};\n",
            f"  const LOGIN = {_js(_SELECTORS['login'])};\n",
            "  const shown = (sel) => [...document.querySelectorAll(sel)]\n",
            "    .some((node) => !!(node && node.getClientRects().length));\n",
        ]
    )


def _page_probe_script() -> str:
    """返回当前页面状态（url / title / 是否有验证码或登录框）的探针。"""
    return "".join(
        [
            "(() => { /* rf:page-state */\n",
            _blocker_js(),
            "  return JSON.stringify({\n",
            "    url: location.href,\n",
            "    title: document.title || '',\n",
            "    captcha: shown(CAPTCHA),\n",
            "    login_required: shown(LOGIN),\n",
            "  });\n",
            "})()",
        ]
    )


def _url_probe_script() -> str:
    return "".join(
        [
            "(() => { /* rf:url */\n",
            "  return JSON.stringify({ url: location.href });\n",
            "})()",
        ]
    )


def _as_payload(value: Any) -> Any:
    """页面脚本返回的可能是 JSON 字符串，也可能是已解析的对象。"""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError as exc:
            raise SiteFailure(
                FAILURE_SELECTOR_INVALID,
                "页面返回的内容无法解析，可能页面结构已变化；请把这条信息反馈给维护者",
            ) from exc
    return value


def _current_url(client: CdpClient) -> str:
    state = _as_payload(client.evaluate(_url_probe_script()))
    if isinstance(state, dict):
        return str(state.get("url", ""))
    return ""


def query_params(query: str) -> dict[str, str]:
    """把查询串拆成参数表（不做 URL 解码）。"""
    params: dict[str, str] = {}
    for part in query.split("&"):
        if not part:
            continue
        name, _, value = part.partition("=")
        params[name] = value
    return params


def same_target_page(current: str, target: str) -> bool:
    """目标查询参数在当前同主机地址中全部相同，便视为目标页。"""
    try:
        current_parts, target_parts = urlparse(current), urlparse(target)
    except ValueError:
        return False
    if (current_parts.scheme, current_parts.netloc) != (
        target_parts.scheme,
        target_parts.netloc,
    ):
        return False
    if not target_parts.query:
        return current_parts.path.rstrip("/") == target_parts.path.rstrip("/")
    current_query = query_params(current_parts.query)
    for name, value in query_params(target_parts.query).items():
        if unquote(current_query.get(name, "")) != unquote(value):
            return False
    return True


def _readiness_script(selector: str) -> str:
    return "".join(
        [
            "(() => { /* rf:readiness */\n",
            f"  const TARGET = {_js(selector)};\n",
            f"  const EMPTY = {_js(SELECTOR_SEARCH_EMPTY)};\n",
            _blocker_js(),
            "  const body = (document.body && document.body.innerText) || '';\n",
            "  const emptyWords = ['没有找到', '暂无相关', '暂无职位', '未找到匹配', '没有相关', '换个关键词试试'];\n",
            "  let matched = 0;\n",
            "  try { matched = document.querySelectorAll(TARGET).length; } catch (e) { matched = 0; }\n",
            # 空态同样要求**可见**：站点若把空态容器作为模板藏在页面里，只看存在与否会让
            # 每一次搜索都被判成"确实没搜到"，于是安静地返回 0 条——正是最该避免的形态。
            "  const explicitlyEmpty = shown(EMPTY) || emptyWords.some((w) => body.includes(w));\n",
            "  return JSON.stringify({\n",
            "    url: location.href,\n",
            "    title: document.title || '',\n",
            "    ready_state: document.readyState || '',\n",
            "    matched: matched,\n",
            "    explicitly_empty: explicitlyEmpty,\n",
            "    captcha: shown(CAPTCHA),\n",
            "    login_required: shown(LOGIN),\n",
            "  });\n",
            "})()",
        ]
    )


def selector_diagnostic(state: dict[str, Any], expected: str) -> str:
    url = state.get("url") or "未知"
    title = state.get("title") or "未知"
    matched = state.get("matched", 0)
    return (
        f"页面结构可能已变化：未找到「{expected}」。"
        f"当前地址：{url}；页面标题：{title}；"
        f"匹配到的控件数：{matched}；期望：{expected}（例如文本含「立即沟通」或「投递」的入口）。"
        "请把这段信息反馈给维护者，以便更新站点选择器。"
    )


def detect_blocker(state: dict[str, Any]) -> str | None:
    if state.get("captcha"):
        return "captcha"
    if state.get("login_required"):
        return "login"
    return None


def blocker_failure(kind: str, state: dict[str, Any]) -> SiteFailure:
    url = state.get("url") or ""
    title = state.get("title") or ""
    if kind == "login":
        return SiteFailure(
            FAILURE_LOGIN_REQUIRED,
            "需要先登录 BOSS 直聘：请在弹出的浏览器窗口里扫码登录一次后再重试",
            url=url,
            title=title,
        )
    return SiteFailure(
        FAILURE_CAPTCHA_REQUIRED,
        "站点出现验证码或安全验证：请在浏览器窗口里手动完成验证，再恢复投递",
        url=url,
        title=title,
    )


def diagnostic_tail(state: dict[str, Any], expected: str) -> str:
    url = state.get("url") or "未知"
    title = state.get("title") or "未知"
    matched = state.get("matched", 0)
    return f"当前地址：{url}；页面标题：{title}；匹配到的控件数：{matched}；期望：{expected}"


def readiness_timeout_failure(
    state: dict[str, Any], expected: str, *, fresh: bool
) -> SiteFailure:
    tail = diagnostic_tail(state, expected)
    ready_state = str(state.get("ready_state", ""))
    if not fresh:
        headline = "页面没有切换到目标地址"
        advice = "请确认网络可以正常访问该站点后重试"
    elif ready_state == "complete":
        headline = "页面已加载但找不到岗位卡片，页面结构可能已变化"
        advice = "请把这段信息反馈给维护者，以便更新站点选择器"
    else:
        headline = "页面加载超时（可能网络较慢或被拦截），请稍后重试"
        advice = ""
    detail = f"{headline}。{tail}。"
    if advice:
        detail = f"{detail}{advice}。"
    return SiteFailure(
        FAILURE_SELECTOR_INVALID,
        detail,
        url=state.get("url") or "",
        title=state.get("title") or "",
    )


class BossPageMixin:
    """由搜索与投递流程共用的页面等待逻辑。"""

    def _await_ready(
        self,
        client: CdpClient,
        *,
        selector: str,
        expected: str,
        allow_empty: bool,
        target_url: str = "",
        previous_url: str = "",
    ) -> dict[str, Any]:
        ready_wait = self._ready_wait

        def _probe() -> Any:
            return _as_payload(client.evaluate(_readiness_script(selector)))

        def _fresh(state: dict[str, Any]) -> bool:
            url = str(state.get("url", ""))
            if target_url:
                if same_target_page(url, target_url):
                    return True
                # 旧文档防护只在能观测到导航前 URL 时才有意义。离线适配器测试和某些
                # 轻量 CDP 实现拿不到 previous_url；这时沿用原有兼容语义，交给内容就绪判据。
                if not previous_url:
                    return True
                return False
            return not previous_url or url != previous_url

        def _is_ready(state: dict[str, Any]) -> bool:
            if not _fresh(state):
                return False
            if int(state.get("matched", 0) or 0) > 0:
                return True
            return bool(allow_empty) and bool(state.get("explicitly_empty"))

        def _blocker(state: dict[str, Any]) -> SiteFailure | None:
            kind = detect_blocker(state)
            return blocker_failure(kind, state) if kind is not None else None

        def _on_timeout(state: dict[str, Any]) -> SiteFailure:
            return readiness_timeout_failure(state, expected, fresh=_fresh(state))

        return wait_for_page_state(
            _probe,
            is_ready=_is_ready,
            blocker=_blocker,
            on_timeout=_on_timeout,
            config=ready_wait,
        )


__all__ = [
    "BOSS_DISPLAY_NAME",
    "BOSS_ENTRY_URL",
    "BOSS_HOSTS",
    "BOSS_KEY",
    "CHAT_PAGE_PATH",
    "BossPageMixin",
    "SELECTOR_GREETING_SEND",
    "SELECTOR_MY_MESSAGE",
    "SELECTOR_SEARCH_READY",
    "_SELECTORS",
    "_as_payload",
    "_current_url",
    "_js",
    "blocker_failure",
    "detect_blocker",
    "diagnostic_tail",
    "query_params",
    "readiness_timeout_failure",
    "same_target_page",
    "selector_diagnostic",
]
