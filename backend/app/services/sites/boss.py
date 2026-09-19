"""BOSS 直聘站点适配器。

**改版应急**：本文件所有选择器都集中在顶部的常量里（``_SELECTORS`` 及其成员），业务
逻辑只引用常量名。站点改版时**只改这里的常量**（必要时给 ``FormEngine`` 的启发式加一条
兜底），不动业务层、不动数据模型，并用一条离线 DOM 快照测试钉住新版结构。

一类特殊失败：**选择器 / 投递入口失效**（``selector_invalid``）。它必须带可操作诊断
（当前 URL / 页面标题 / 匹配到的控件数 / 期望控件的候选描述），因为这段诊断会直接给
用户看、用户再把它反馈给我们来收敛选择器。

说明：BOSS 直聘的真实 DOM 与投递流程无法在开发环境联调，选择器为"尽力而为"，首次真机
试用后按用户回传的诊断收敛。应用**不做任何"绕过验证码 / 代替登录"**的实现。
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, unquote, urlparse

from ...models.apply import (
    FAILURE_CAPTCHA_REQUIRED,
    FAILURE_GREETING_MISSING,
    FAILURE_LOGIN_REQUIRED,
    FAILURE_SELECTOR_INVALID,
)
from ..apply.form_engine import FormEngine
from ..browser.cdp_client import CdpClient, CdpError
from ..browser.page_ready import ReadyWait, wait_for_page_state
from .boss_network import DETAIL_MARKERS, SEARCH_MARKERS
from .boss_text import (
    looks_like_salary,
    normalize_text,
    split_job_sections,
    split_title_salary,
)
from .base import (
    ApplyOutcome,
    CollectQuery,
    RiskProfile,
    SearchPage,
    SearchResult,
    SiteAdapter,
    SiteFailure,
)

logger = logging.getLogger(__name__)

BOSS_KEY = "boss"
BOSS_DISPLAY_NAME = "BOSS直聘"
BOSS_HOSTS = ("zhipin.com",)
# 入口地址：启动投递专用浏览器时先打开首页，用户才能在这里扫码登录。
BOSS_ENTRY_URL = "https://www.zhipin.com/"

# 订阅哪一个 CDP 事件：只要响应头，不要请求体（那个事件会把每个请求的完整 payload 推过来，
# 数据量大而且我们不需要）。
NETWORK_RESPONSE_EVENT = "Network.responseReceived"

# ===== 选择器常量（站点改版时只改这里）=====
#
# **每一条都是多候选并列**，任一命中即可用。这不是"多写几个好看"，而是改版存活率的
# 关键：BOSS 的岗位卡片 class 从 `job-card-wrapper` 换成了 `job-card-box`（左边列表面板
# 那种新版布局），只留旧 class 的结果就是 `matched: 0` —— 于是"页面明明正常"却被判成
# 采集失败。并列候选让"改了一半"的页面仍然能用。
SELECTOR_SEARCH_CARD = (
    "li.job-card-box, .job-card-wrapper, ul.rec-job-list > li, .job-list-container .job-card-box"
)
# 岗位详情链接。它比任何卡片 class 都稳——改版可以换 class，但"点进去看岗位"这件事
# 必须有个链接，所以它是兜底路径的锚点。
SELECTOR_JOB_LINK = 'a[href*="/job_detail/"]'
SELECTOR_SEARCH_TITLE = "a.job-name, .job-name, .job-title"
SELECTOR_SEARCH_COMPANY = "span.boss-name, .company-name, .company-info .name"
# 薪资单独定位。新版列表把薪资与岗位名放在同一个节点里，这条匹配不到时会由
# `split_title_salary` 从标题尾部把薪资拆出来（见 boss_text）。
SELECTOR_SEARCH_SALARY = ".salary, .red, .job-salary, .salary-text, [class*='salary']"
SELECTOR_SEARCH_LOCATION = "span.company-location, .job-area, .job-card-right .job-area"
SELECTOR_SEARCH_LINK = f"a.job-name, {SELECTOR_JOB_LINK}, a"
SELECTOR_SEARCH_NEXT = ".options-pages a:last-child, a.next"
SELECTOR_JOB_DESCRIPTION = ".job-sec-text, .job-detail-section .text"
SELECTOR_JOB_REQUIREMENTS = ".job-detail-section:last-child .text"
SELECTOR_APPLY_ENTRY = "a.btn-startchat, .btn-startchat, .op-btn-chat, .btn-chat, [class*='btn-startchat']"
SELECTOR_GREETING_INPUT = ".dialog-container textarea, textarea.chat-input, #chat-input"
SELECTOR_GREETING_SEND = ".dialog-container .btn-send, .btn-sure-v2, button[type='send']"
SELECTOR_SUBMIT_BUTTON = ".btn-submit, .btn-sure"
SELECTOR_FILE_INPUT = "input[type=file]"
SELECTOR_CAPTCHA = ".geetest_panel, .geetest_box, #nc_1_wrapper, .verify-wrap"
SELECTOR_LOGIN = ".login-dialog, .sign-form, .login-panel"
# 明确的"无结果"标志：页面加载完成且呈现空状态时用它区分"关键词真的搜不到"与"没抓到"。
SELECTOR_SEARCH_EMPTY = ".job-empty-wrapper, .search-empty, .empty-tip, .job-list-empty, .empty-wrapper"
# 岗位详情"可抓取"的兜底选择器集合（任一命中即说明详情内容已渲染出来）。
#
# **刻意不含 `.job-name`**：详情页顶部/推荐位也有岗位名，用它判定会让等待在 JD 的 XHR 回来
# 之前就"就绪"，于是网络层提前收网、拿不到详情接口的响应——真实故障里 18 条采集岗位有 8 条
# 描述为空，就是这个过早就绪。这里只认真正属于 JD 正文的容器。
SELECTOR_DETAIL_READY = (
    ".job-sec-text, .job-detail-section, .job-detail-box, "
    ".job-detail-body, .job-detail-content, [class*='job-detail'] .text"
)
# 「这一页可以采集了」的判定选择器：卡片**或**岗位详情链接存在即可。
#
# 比 ``SELECTOR_SEARCH_CARD`` 宽一档是刻意的：改版只换了卡片 class 时，链接仍然在，
# 于是这次等待被认成"就绪"，网络层与兜底脚本立刻接手；若死守卡片选择器，页面明明
# 已经好了也要干等满 15 秒，最后报一句"页面结构可能已变化"。
SELECTOR_SEARCH_READY = f"{SELECTOR_SEARCH_CARD}, {SELECTOR_JOB_LINK}"

# 集中成一张表，业务代码统一从这里取（便于改版时一处替换）。
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
    "submit_button": SELECTOR_SUBMIT_BUTTON,
    "file_input": SELECTOR_FILE_INPUT,
    "captcha": SELECTOR_CAPTCHA,
    "login": SELECTOR_LOGIN,
    "search_empty": SELECTOR_SEARCH_EMPTY,
    "detail_ready": SELECTOR_DETAIL_READY,
}


def _js(selector: str) -> str:
    return json.dumps(selector)


def _page_probe_script() -> str:
    """返回当前页面状态（url / title / 是否有验证码或登录框）的探针。"""
    return "".join(
        [
            "(() => { /* rf:page-state */\n",
            f"  const CAPTCHA = {_js(_SELECTORS['captcha'])};\n",
            f"  const LOGIN = {_js(_SELECTORS['login'])};\n",
            "  return JSON.stringify({\n",
            "    url: location.href,\n",
            "    title: document.title || '',\n",
            "    captcha: !!document.querySelector(CAPTCHA),\n",
            "    login_required: !!document.querySelector(LOGIN),\n",
            "  });\n",
            "})()",
        ]
    )


def _url_probe_script() -> str:
    """导航前记录当前页地址：用来判断"新文档是否已经接管"，避免读到旧页面的内容。"""
    return "".join(
        [
            "(() => { /* rf:url */\n",
            "  return JSON.stringify({ url: location.href });\n",
            "})()",
        ]
    )


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
    """当前地址是否**就是**目标那一页。

    判据：**目标地址里的每个查询参数，都能在当前地址里取到相同的值**（且同主机）。
    而不是整串相等，也不是"路径相同"——两头都试过，各有一个真实故障：

    - **整串相等太严**：站点会规范化查询串（补默认参数、调换顺序、``/web/geek/job``
      跳成 ``/web/geek/jobs``）。拼出来的目标与浏览器实际落地的地址永远不完全一致，
      于是**每一次正常导航都被误判成"没切换"**，等满超时后报"页面没有切换到目标地址"
      ——页面其实早就渲染好了（真实反馈里就是这么发生的）。
    - **只看路径太松**：``?page=1`` 与 ``?page=2`` 路径完全相同，会把"还停在上一页"
      认成"已到位"，翻页于是读到上一页的内容。

    带参数的比较正好卡在中间：既容纳站点的规范化（多出来的参数、顺序变化、路径改名都
    不影响），又要求页码 / 关键词这些**真正区分页面**的参数一致。目标没有查询参数时
    （例如站点入口页）无从比较，返回 ``False``，交由调用方的其它判据处理。
    """
    try:
        current_parts, target_parts = urlparse(current), urlparse(target)
    except ValueError:
        return False
    if not target_parts.query:
        return False
    if (current_parts.scheme, current_parts.netloc) != (
        target_parts.scheme,
        target_parts.netloc,
    ):
        return False
    current_query = query_params(current_parts.query)
    for name, value in query_params(target_parts.query).items():
        # 解码后再比：同一个值可能被编码成不同的百分比串（`%E5%90%8E%E7%AB%AF` 与原文）。
        if unquote(current_query.get(name, "")) != unquote(value):
            return False
    return True


def _readiness_script(selector: str) -> str:
    """轮询用探针：在**导航之后**判定当前页是否已经"可用于采集/投递"。

    它同时回答三个问题，供等待原语一次判定：
    - 目标选择器是否已经匹配到内容（``matched``）；
    - 是否出现需要登录 / 验证码的拦截（``captcha`` / ``login_required``）；
    - 是否**明确**处于"无结果"状态（``explicitly_empty``）——这是唯一允许"匹配 0 个仍然合法"
      的情形；否则匹配 0 个一律按"页面没 load 好 / 选择器失效"处理。
    """
    return "".join(
        [
            "(() => { /* rf:readiness */\n",
            f"  const TARGET = {_js(selector)};\n",
            f"  const EMPTY = {_js(SELECTOR_SEARCH_EMPTY)};\n",
            f"  const CAPTCHA = {_js(_SELECTORS['captcha'])};\n",
            f"  const LOGIN = {_js(_SELECTORS['login'])};\n",
            "  const body = (document.body && document.body.innerText) || '';\n",
            "  const emptyWords = ['没有找到', '暂无相关', '暂无职位', '未找到匹配', '没有相关', '换个关键词试试'];\n",
            "  let matched = 0;\n",
            "  try { matched = document.querySelectorAll(TARGET).length; } catch (e) { matched = 0; }\n",
            "  const explicitlyEmpty = !!document.querySelector(EMPTY) || emptyWords.some((w) => body.includes(w));\n",
            "  return JSON.stringify({\n",
            "    url: location.href,\n",
            "    title: document.title || '',\n",
            "    ready_state: document.readyState || '',\n",
            "    matched: matched,\n",
            "    explicitly_empty: explicitlyEmpty,\n",
            "    captcha: !!document.querySelector(CAPTCHA),\n",
            "    login_required: !!document.querySelector(LOGIN),\n",
            "  });\n",
            "})()",
        ]
    )


def _apply_entry_script() -> str:
    """定位"立即沟通 / 投递"入口，返回匹配数量与页面状态。"""
    return "".join(
        [
            "(() => { /* rf:apply-entry */\n",
            f"  const ENTRY = {_js(_SELECTORS['apply_entry'])};\n",
            f"  const CAPTCHA = {_js(_SELECTORS['captcha'])};\n",
            f"  const LOGIN = {_js(_SELECTORS['login'])};\n",
            "  const nodes = [...document.querySelectorAll(ENTRY)];\n",
            "  return JSON.stringify({\n",
            "    url: location.href,\n",
            "    title: document.title || '',\n",
            "    matched: nodes.length,\n",
            "    found: nodes.length > 0,\n",
            "    captcha: !!document.querySelector(CAPTCHA),\n",
            "    login_required: !!document.querySelector(LOGIN),\n",
            "  });\n",
            "})()",
        ]
    )


def _collect_script() -> str:
    """采集搜索结果列表一页。"""
    return "".join(
        [
            "(() => { /* rf:collect */\n",
            f"  const CARD = {_js(_SELECTORS['search_card'])};\n",
            f"  const TITLE = {_js(_SELECTORS['search_title'])};\n",
            f"  const COMPANY = {_js(_SELECTORS['search_company'])};\n",
            f"  const SALARY = {_js(_SELECTORS['search_salary'])};\n",
            f"  const LOCATION = {_js(_SELECTORS['search_location'])};\n",
            f"  const LINK = {_js(_SELECTORS['search_link'])};\n",
            "  const pick = (root, sel) => { const n = root.querySelector(sel);\n",
            "    return n ? (n.textContent || '').trim() : ''; };\n",
            "  const items = [...document.querySelectorAll(CARD)].map((card) => {\n",
            "    const a = card.querySelector(LINK);\n",
            "    return {\n",
            "      title: pick(card, TITLE),\n",
            "      company: pick(card, COMPANY),\n",
            "      salary: pick(card, SALARY),\n",
            "      location: pick(card, LOCATION),\n",
            "      url: a ? a.href : '',\n",
            "    };\n",
            "  });\n",
            "  const next = document.querySelector(" + _js(_SELECTORS["search_next"]) + ");\n",
            "  return JSON.stringify({\n",
            "    url: location.href,\n",
            "    title: document.title || '',\n",
            "    items,\n",
            "    has_next: !!(next && !next.classList.contains('disabled')),\n",
            "  });\n",
            "})()",
        ]
    )


def _collect_links_script() -> str:
    """最后一道兜底：**只按岗位详情链接**抓，拿到标题与地址。

    卡片 class 改名是最常见的失效方式，而"点进去看岗位"的链接几乎不会消失，所以它是
    DOM 这条路上最稳的锚点。代价是拿不到公司 / 薪资 / 地点（它们在不同层级的兄弟节点里，
    没有卡片结构就无从定位）——但那三样空着，也比因为一个 class 改名就报"什么都抓不到"
    强得多：用户至少能看到"抓到了哪些岗位"，而不是面对一个静默的 0。
    """
    return "".join(
        [
            "(() => { /* rf:collect-links */\n",
            f"  const LINK = {_js(SELECTOR_JOB_LINK)};\n",
            "  const seen = new Set();\n",
            "  const items = [];\n",
            "  for (const a of document.querySelectorAll(LINK)) {\n",
            "    const href = a.href || '';\n",
            "    if (!href || seen.has(href)) continue;\n",
            "    seen.add(href);\n",
            "    items.push({ title: (a.textContent || '').trim(), company: '',\n",
            "      salary: '', location: '', url: href });\n",
            "  }\n",
            "  const next = document.querySelector(" + _js(_SELECTORS["search_next"]) + ");\n",
            "  return JSON.stringify({\n",
            "    url: location.href,\n",
            "    title: document.title || '',\n",
            "    items,\n",
            "    has_next: !!(next && !next.classList.contains('disabled')),\n",
            "  });\n",
            "})()",
        ]
    )


def _detail_script() -> str:
    """抓取岗位详情（标题 / 公司 / 描述 / 任职要求）。"""
    return "".join(
        [
            "(() => { /* rf:detail */\n",
            f"  const TITLE = {_js(_SELECTORS['search_title'])};\n",
            f"  const COMPANY = {_js(_SELECTORS['search_company'])};\n",
            f"  const DESC = {_js(_SELECTORS['job_description'])};\n",
            f"  const REQ = {_js(_SELECTORS['job_requirements'])};\n",
            "  const pick = (sel) => { const n = document.querySelector(sel);\n",
            "    return n ? (n.textContent || '').trim() : ''; };\n",
            "  return JSON.stringify({\n",
            "    url: location.href,\n",
            "    title: document.title || '',\n",
            "    job_title: pick(TITLE),\n",
            "    company: pick(COMPANY),\n",
            "    description: pick(DESC),\n",
            "    requirements: pick(REQ),\n",
            "  });\n",
            "})()",
        ]
    )


def _greeting_state_script() -> str:
    """招呼语输入框是否存在、是否必填。"""
    return "".join(
        [
            "(() => { /* rf:greeting-state */\n",
            f"  const INPUT = {_js(_SELECTORS['greeting_input'])};\n",
            "  const node = document.querySelector(INPUT);\n",
            "  return JSON.stringify({\n",
            "    url: location.href,\n",
            "    title: document.title || '',\n",
            "    found: !!node,\n",
            "    required: !!(node && (node.required || node.getAttribute('required') !== null)),\n",
            "  });\n",
            "})()",
        ]
    )


def _fill_greeting_script(greeting: str) -> str:
    return "".join(
        [
            "(() => { /* rf:fill-greeting */\n",
            f"  const INPUT = {_js(_SELECTORS['greeting_input'])};\n",
            f"  const TEXT = {json.dumps(greeting)};\n",
            "  const node = document.querySelector(INPUT);\n",
            "  if (!node) { return JSON.stringify({ ok: false }); }\n",
            "  node.focus();\n",
            "  node.value = TEXT;\n",
            "  node.dispatchEvent(new Event('input', { bubbles: true }));\n",
            "  node.dispatchEvent(new Event('change', { bubbles: true }));\n",
            "  return JSON.stringify({ ok: true });\n",
            "})()",
        ]
    )


def _click_script(selector: str, marker: str) -> str:
    return "".join(
        [
            f"(() => {{ /* {marker} */\n",
            f"  const SEL = {_js(selector)};\n",
            "  const node = document.querySelector(SEL);\n",
            "  if (!node) { return JSON.stringify({ ok: false }); }\n",
            "  node.click();\n",
            "  return JSON.stringify({ ok: true });\n",
            "})()",
        ]
    )


def _submit_state_script() -> str:
    """提交后读取结果标志（成功文案 / 验证码 / 登录失效 / 仍停在表单页）。"""
    return "".join(
        [
            "(() => { /* rf:submit-state */\n",
            f"  const CAPTCHA = {_js(_SELECTORS['captcha'])};\n",
            f"  const LOGIN = {_js(_SELECTORS['login'])};\n",
            f"  const INPUT = {_js(_SELECTORS['greeting_input'])};\n",
            "  const body = (document.body && document.body.innerText) || '';\n",
            "  const successWords = ['发送成功', '已投递', '沟通成功', '消息已发送'];\n",
            "  return JSON.stringify({\n",
            "    url: location.href,\n",
            "    title: document.title || '',\n",
            "    captcha: !!document.querySelector(CAPTCHA),\n",
            "    login_required: !!document.querySelector(LOGIN),\n",
            "    success: successWords.some((w) => body.includes(w)),\n",
            "    matched: document.querySelectorAll(INPUT).length,\n",
            "  });\n",
            "})()",
        ]
    )


# ===== 纯函数：解析与判定（可离线单测）=====


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


def selector_diagnostic(state: dict[str, Any], expected: str) -> str:
    """构造"选择器/入口失效"的可操作诊断（这段会直接展示给用户）。"""
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
    """识别"需要登录"与"需要验证码"两类拦截，返回 ``login`` / ``captcha`` / ``None``。"""
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
    """超时诊断的公共尾部（当前地址 / 页面标题 / 匹配控件数 / 期望控件）。

    这段会直接展示给用户，用户再反馈给我们来收敛选择器——所以四要素都要齐全。
    """
    url = state.get("url") or "未知"
    title = state.get("title") or "未知"
    matched = state.get("matched", 0)
    return f"当前地址：{url}；页面标题：{title}；匹配到的控件数：{matched}；期望：{expected}"


def readiness_timeout_failure(
    state: dict[str, Any], expected: str, *, fresh: bool
) -> SiteFailure:
    """等待超时（除拦截外的**唯一**失败路径）时，按观测到的证据给出不同文案。

    三种证据对应三种该做什么：

    - **陈旧文档**（``fresh`` 为假：地址始终没切到目标页）→「页面没有切换到目标地址」；
    - **已切到新文档、``readyState === 'complete'``、却仍无目标卡片且无"无结果"标志**
      →「页面已加载但找不到岗位卡片，页面结构可能已变化」（可把诊断反馈给维护者）；
    - **其余**（文档尚未 ``complete`` / 网络慢 / 被拦截）→「页面加载超时…，请稍后重试」。

    **绝不**把这三种都笼统说成"结构变化"——那会把"网络慢"误报成"选择器失效"。三种情况都附带
    同一段可操作诊断（当前地址 / 页面标题 / 匹配控件数 / 期望控件）。
    """
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


def classify_submit_state(state: dict[str, Any], greeting: str = "") -> ApplyOutcome:
    """根据提交后的页面状态判定投递结果；失败抛 ``SiteFailure``。

    判定顺序：先看登录失效、再看验证码、再看成功标志，都没有则判为选择器失效并给出诊断。
    """
    blocker = detect_blocker(state)
    if blocker is not None:
        raise blocker_failure(blocker, state)
    if state.get("success"):
        return ApplyOutcome(success=True, greeting_sent=greeting)
    raise SiteFailure(
        FAILURE_SELECTOR_INVALID,
        selector_diagnostic(state, "投递成功标志（如「发送成功 / 已投递」）"),
        url=state.get("url") or "",
        title=state.get("title") or "",
    )


def parse_search_payload(
    payload: dict[str, Any], page: int, unmapped_conditions: list[str] | None = None
) -> SearchPage:
    """把采集脚本的原始结果解析成 ``SearchPage``。"""
    if not isinstance(payload, dict):
        raise SiteFailure(FAILURE_SELECTOR_INVALID, "搜索结果返回了无法解析的内容")
    items = payload.get("items")
    results: list[SearchResult] = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            # DOM 里读到的文本被反爬混淆过（私用区数字、`boss`/`kanzhun`/`直聘` 水印、
            # 康熙部首），必须**先还原再做判断**——否则"全栈工程师\ue032\ue033-\ue032\ue036K"
            # 无论怎么切都切不出薪资。
            title, title_salary = split_title_salary(item.get("title", ""))
            salary = normalize_text(item.get("salary", ""))
            if not looks_like_salary(salary):
                # 薪资元素没取到，或取到的是一个同时含岗位名的容器（新版列表把两者放在
                # 同一个节点里）。这时用标题尾部拆出来的那份；拆不出来就**留空**——
                # 留空好过把岗位名当成薪资写进库里。
                salary = title_salary
            results.append(
                SearchResult(
                    title=title,
                    company=normalize_text(item.get("company", "")),
                    location=normalize_text(item.get("location", "")),
                    salary=salary,
                    url=str(item.get("url", "")),
                    source=BOSS_DISPLAY_NAME,
                )
            )
    return SearchPage(
        results=results,
        page=page,
        has_next=bool(payload.get("has_next")),
        unmapped_conditions=list(unmapped_conditions or []),
    )


def parse_job_detail(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SiteFailure(FAILURE_SELECTOR_INVALID, "岗位详情返回了无法解析的内容")
    # DOM 读到的 JD 同样被反爬混淆过（水印 token / 康熙部首），先还原再切分。
    dom_requirements = normalize_text(payload.get("requirements", ""))
    description, split_requirements = split_job_sections(payload.get("description", ""))
    return {
        "job_title": normalize_text(payload.get("job_title", "")),
        "company": normalize_text(payload.get("company", "")),
        "description": description,
        # DOM 单独取到了「任职要求」容器就用它；没有就用在描述里切出来的那一段。
        "requirements": dom_requirements or split_requirements,
        "url": str(payload.get("url", "")),
    }


def _with_response_bodies(
    client: CdpClient, events: list[dict[str, Any]]
) -> list[Any]:
    """对拦到的目标接口发 ``Network.getResponseBody``，把解析后的响应体取回来。

    只对**我们关心的两个接口路径**取体：一个页面上会加载几十个请求（图片、脚本、
    埋点），逐个取体既慢又占内存。
    """
    from ..browser.network_capture import MAX_PARSED_RESPONSES, collect_bodies, response_urls

    wanted = {
        url
        for markers in (SEARCH_MARKERS, DETAIL_MARKERS)
        for url in response_urls(events, markers=markers)
    }
    body_events: list[dict[str, Any]] = []
    fetched: set[str] = set()
    for event in events:
        if len(body_events) >= MAX_PARSED_RESPONSES:
            break
        if event.get("method") != "Network.responseReceived":
            continue
        # requestId 在 params 里，不在事件根上——取错位置会让这里永远一条都取不到，
        # 而失败方式是"安静地退回 DOM"，从外面完全看不出来。
        params = event.get("params")
        if not isinstance(params, dict):
            continue
        request_id = str(params.get("requestId") or "")
        if not request_id or request_id in fetched:
            continue
        response = params.get("response")
        url = str(response.get("url") or "") if isinstance(response, dict) else ""
        if url not in wanted:
            continue
        try:
            result = client.send("Network.getResponseBody", {"requestId": request_id})
        except CdpError:
            # 响应体可能已经不在缓存里（页面跳走、被回收）。跳过这一条就好，
            # 其余响应仍然可用。
            logger.debug("取响应体失败（可能已被回收）：%s", url)
            continue
        fetched.add(request_id)
        body_events.append(
            {"method": "Network.getResponseBody", "requestId": request_id, "result": result}
        )

    if not body_events:
        return []
    # 解析时仍要带上 responseReceived，才能把 requestId 还原成 URL。
    return collect_bodies([*events, *body_events])


class BossAdapter(SiteAdapter):
    """BOSS 直聘适配器。"""

    key = BOSS_KEY
    display_name = BOSS_DISPLAY_NAME
    hosts = BOSS_HOSTS
    entry_url = BOSS_ENTRY_URL
    supports_collect = True
    supports_apply = True
    # 这三个条件走**本地筛选**而不是查询参数：BOSS 把它们做成不透明的数字编码，
    # 猜错就是静默返回错误结果。而列表接口本来就返回每条岗位的学历要求、经验要求与
    # 薪资数字（见 ``boss_network.parse_search_response`` 的 ``extra``），采完之后按
    # 这些字段筛即可，无需编码表，而且筛掉几条都能如实报出来。
    post_filter_conditions = ("薪资", "经验", "学历")

    # "保存抓到的站点原文"要保存的两个接口：搜索列表与岗位详情。片段与解析路径共用同一组
    # markers（``boss_network`` 里定义），改一处即可同时作用于解析与样例保存——站点知识只有一份。
    # **加新站点 / 改这里时务必确认：该接口的响应体里不含凭据**——它会被原样落盘（落盘字段只有
    # url_path / captured_at / body，不含 headers/Cookie/请求体，但 body 是原文）。若某站点把
    # 令牌放进响应体，就绝不能把它列进 sample_markers。
    sample_markers = (("search", SEARCH_MARKERS), ("detail", DETAIL_MARKERS))

    def __init__(self, *, ready_wait: ReadyWait | None = None) -> None:
        # 等待参数可注入：生产用默认值，离线测试可传一个极短的超时/间隔。
        self._ready_wait = ready_wait or ReadyWait()

    def risk_profile(self) -> RiskProfile:
        # 风控参数：岗位之间至少间隔 25 秒、每小时不超过 60 次（由任务运行器执行）。
        return RiskProfile(
            key=self.key,
            min_interval_seconds=25,
            max_per_hour=60,
            needs_login=True,
            notes="BOSS 直聘对高频操作敏感，投递间隔过短可能触发验证码或临时限制。",
        )

    # ===== 页面就绪等待（采集与详情共用）=====

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
        """导航之后轮询直到页面可采集，或按约定失败。

        - **必须等新文档接管**：``Page.navigate`` 只是**发起**导航，返回时旧文档可能仍在，
          直接抓会读到上一页的内容（分页场景会读到上一页并错算 ``has_next``）。所以要有
          "这确实是目标那一页"的证据，二者取一：目标地址里的查询参数（关键词 / 城市 / 页码）
          在当前地址里都取到相同的值（见 ``same_target_page``），或地址相对导航前已经变化。
          早先这里要求"地址与拼出来的目标**整串相等**"，而站点会规范化查询串
          （``/web/geek/job`` → ``/web/geek/jobs``），于是**一次正常的导航被误判成没切换**，
          等满超时后报出"页面没有切换到目标地址"——真实反馈里就是这么发生的。
        - 目标选择器匹配到内容 → 就绪；``allow_empty`` 时"明确无结果"也算就绪；
        - 出现登录失效 / 验证码 → **立刻**抛对应 ``SiteFailure``，不傻等满超时；
        - **超时是唯一的失败时限**：``readyState === 'complete'`` **不代表** SPA 该渲染的内容
          已经渲染完（BOSS 的岗位卡片是 ``complete`` 之后由 XHR 异步渲染的），所以**不**按
          ``readyState`` 提前判失败——否则首屏稍慢就会误报"结构变化"。等满超时后再由
          ``readiness_timeout_failure`` 按证据给出诊断（没切换地址 / 未加载完 / 已加载但无卡片），
          **绝不**当成"采到 0 个"静默成功。
        """
        ready_wait = self._ready_wait

        def _probe() -> Any:
            # 这是一次 CDP 调用：外层 StopAwareCdpClient 会在这里插停止检查点。
            return _as_payload(client.evaluate(_readiness_script(selector)))

        def _fresh(state: dict[str, Any]) -> bool:
            url = str(state.get("url", ""))
            # 目标地址里的查询参数（关键词 / 城市 / 页码）都取到相同的值 → 就是目标那一页。
            # 这条对站点的查询串规范化免疫，同时仍然拦得住"还停在上一页"。
            if target_url and same_target_page(url, target_url):
                return True
            # 没有记录导航前地址时无法判断新旧，只能放行（测试 / 首次导航）。
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
            # 超时是唯一的失败时限：按证据区分"没切换地址 / 未加载完 / 已加载但无卡片"。
            return readiness_timeout_failure(state, expected, fresh=_fresh(state))

        return wait_for_page_state(
            _probe,
            is_ready=_is_ready,
            blocker=_blocker,
            on_timeout=_on_timeout,
            config=ready_wait,
        )

    # ===== 采集 =====

    def build_search_url(self, query: CollectQuery, page: int) -> str:
        keyword = quote((query.keywords[0] if query.keywords else "").strip(), safe="")
        city = quote((query.city or "").strip(), safe="")
        base = f"https://www.zhipin.com/web/geek/job?query={keyword}&city={city}"
        return f"{base}&page={max(page, 1)}"

    def unmapped_conditions(self, query: CollectQuery) -> list[str]:
        """这里返回的是**真的没能生效**的条件。

        薪资 / 经验 / 学历**不在这里**：它们由采集器在采集后按接口字段本地筛选
        （见 ``post_filter_conditions``），属于"换了一种方式生效"。只有采集器发现
        连接口字段也拿不到时，才会把它们回报成"未能判断"——那是另一回事，
        而且界面会分别说清楚，不会混成一句"未生效"。
        """
        return []

    def _capture_network(
        self, client: CdpClient, action: Callable[[], Any]
    ) -> tuple[list[Any], Any]:
        """执行 ``action``（导航**并等到页面可用**）并收集其中的网络响应。

        返回 ``(已解析的响应体, action 的返回值)``；不支持订阅时安静返回空列表。

        **网络响应优先、DOM 兜底**：接口返回的字段比 DOM 全，而且不受渲染时序与字体
        反爬影响。但接口路径随时可能变，所以这条路失败时一律退回 DOM——两条路并存，
        不二选一。

        两条容易写错的时序：

        - **订阅要早于导航**：列表接口的响应在页面加载过程中就回来了，导航之后再订阅
          会漏掉第一批；
        - **取走与停止要晚于等待结束**：``Page.navigate`` 只是**发起**导航，返回时页面
          还没开始跑 XHR。导航完就取走并停止订阅，等于永远拦不到东西——而失败方式是
          **静默退回 DOM**，从外面完全看不出来。所以等待必须由 ``action`` 一起做完。

        ``action`` 的异常**照常向上抛**：等待本身就是采集的一部分，它的失败（页面没
        就绪 / 需要登录 / 选择器失效）不能被"网络这条路失败不影响采集"的兜底吞掉。
        """
        starter = getattr(client, "start_event_capture", None)
        drain = getattr(client, "drain_events", None)
        if starter is None or drain is None:
            return [], action()
        stop = getattr(client, "stop_event_capture", None)
        starter([NETWORK_RESPONSE_EVENT])
        try:
            result = action()
            # 取走必须在 stop 之前：停止订阅会连缓冲区一起清掉。
            events = list(drain())
        finally:
            if stop is not None:
                stop()
        try:
            return _with_response_bodies(client, events), result
        except Exception:  # noqa: BLE001 - 网络这条路失败不该影响采集本身
            logger.debug("解析网络响应时出错，将退回 DOM 解析", exc_info=True)
            return [], result

    def collect_search(self, client: CdpClient, query: CollectQuery, page: int) -> SearchPage:
        # 复用当前标签页导航（不每页新开标签），再**等页面真的可用于采集**才抓取。
        target = self.build_search_url(query, page)
        previous = _current_url(client)

        # 页面等待的结果**先记下来、不立刻抛**：在宣布"页面没好"之前，网络层可能已经把
        # 岗位列表拿到手了。真实故障正是这样——DOM 选择器过期（卡片 class 从
        # `job-card-wrapper` 改成 `job-card-box`），接口明明返回了数据，却在等待阶段
        # 直接抛失败，于是采集永远成功不了。
        outcome: dict[str, Any] = {"state": {}, "failure": None}

        def _load() -> dict[str, Any]:
            client.navigate(target)
            try:
                outcome["state"] = self._await_ready(
                    client,
                    # 就绪判定用**宽一档**的选择器（卡片或岗位链接）：改版只换了卡片
                    # class 时，页面明明已经好了，也不至于干等满超时。
                    selector=SELECTOR_SEARCH_READY,
                    expected="岗位卡片（如 li.job-card-box / .job-card-wrapper，或岗位详情链接）",
                    allow_empty=True,
                    target_url=target,
                    previous_url=previous,
                )
            except SiteFailure as exc:
                outcome["failure"] = exc
            return outcome["state"]

        # 导航与等待都在订阅期间完成：接口响应要等页面跑起来才回来。
        responses, state = self._capture_network(client, _load)

        # ① 首选：从接口响应里解析（字段更全，且不受渲染时序与 DOM 改版影响）。**放在"DOM
        #    说无结果"的判断之前**：接口拿到了岗位就说明这次搜索有结果，此时 DOM 匹配 0 个
        #    只说明页面没渲染出来（或选择器失效）——按 DOM 判空会把"抓到了"说成"没搜到"。
        from .boss_network import looks_like_search, parse_search_response, search_has_more
        from ..browser.network_capture import first_json_with

        network_items = first_json_with(responses, looks_like_search)
        parsed = parse_search_response(network_items) if network_items is not None else None
        if parsed:
            has_more = search_has_more(network_items)
            return SearchPage(
                results=[
                    SearchResult(
                        title=item["title"],
                        company=item["company"],
                        location=item["location"],
                        salary=item["salary"],
                        url=item["url"],
                        source=BOSS_DISPLAY_NAME,
                        extra=item.get("extra") or {},
                    )
                    for item in parsed
                ],
                page=page,
                # 接口里的翻页标志优先：等待用的那个探针根本不报 has_next，
                # 一路取它会让"永远没有下一页"，翻页在第 1 页就停住。
                has_next=has_more if has_more is not None else bool(state.get("has_next")),
                unmapped_conditions=self.unmapped_conditions(query),
            )

        # ② 接口没拿到、而页面等待已判定失败 → 如实抛出那次失败（带可操作诊断）。
        failure = outcome["failure"]
        if failure is not None:
            raise failure

        if int(state.get("matched", 0) or 0) <= 0:
            # 走到这里意味着页面**明确**处于"无结果"状态：关键词确实搜不到，返回空页是合法的。
            return SearchPage(
                results=[],
                page=page,
                has_next=False,
                unmapped_conditions=self.unmapped_conditions(query),
            )

        # ③ 兜底一：按卡片结构解析 DOM。
        payload = _as_payload(client.evaluate(_collect_script()))
        payload = payload if isinstance(payload, dict) else {}
        blocker = detect_blocker(payload)
        if blocker is not None:
            raise blocker_failure(blocker, payload)
        dom_page = parse_search_payload(payload, page, self.unmapped_conditions(query))
        if dom_page.results:
            return dom_page

        # ④ 兜底二：卡片没匹配到，但页面等待认为"有内容"（多半是靠岗位链接判定就绪的）
        #    → 换一套只依赖链接的脚本再试一次。只有标题与地址，但绝不把"抓不到"说成"没有"。
        link_payload = _as_payload(client.evaluate(_collect_links_script()))
        link_payload = link_payload if isinstance(link_payload, dict) else {}
        link_items = link_payload.get("items")
        if isinstance(link_items, list) and link_items:
            return parse_search_payload(link_payload, page, self.unmapped_conditions(query))

        # ⑤ 三轮都没拿到任何岗位：如实报错并附诊断，**不**静默返回 0 条。静默的 0 是最坏的
        #    结果——用户会以为"关键词没搜到"，而实际上是工具坏了。
        raise SiteFailure(
            FAILURE_SELECTOR_INVALID,
            selector_diagnostic(payload, "岗位卡片（如 li.job-card-box / .job-card-wrapper）"),
            url=str(payload.get("url") or ""),
            title=str(payload.get("title") or ""),
        )

    def fetch_job_detail(self, client: CdpClient, url: str) -> dict[str, Any]:
        # 同样要等页面就绪，否则会在空白文档上抓到空内容（或读到上一个岗位页的残留）。
        # 等待包在订阅期间：详情接口的响应要等页面跑起来才回来。
        previous = _current_url(client)

        def _load() -> None:
            client.navigate(url)
            self._await_ready(
                client,
                selector=_SELECTORS["detail_ready"],
                expected="岗位详情内容（如 .job-sec-text）",
                allow_empty=False,
                target_url=url,
                previous_url=previous,
            )

        responses, _ = self._capture_network(client, _load)

        # ① 首选：详情接口带回**完整 JD**（DOM 只渲染出摘要，而采集器会把这里的描述
        #    写进 Job.description，岗位匹配读到的就是全文）以及技能标签、HR 活跃时间。
        from .boss_network import looks_like_detail, parse_detail_response
        from ..browser.network_capture import first_json_with

        network_detail = first_json_with(responses, looks_like_detail)
        if network_detail is not None:
            parsed = parse_detail_response(network_detail)
            if parsed is not None:
                # 接口没给详情页地址时用调用方传进来的那个。
                parsed["url"] = parsed.get("url") or url
                return parsed

        # ② 兜底：DOM 解析。
        payload = _as_payload(client.evaluate(_detail_script()))
        return parse_job_detail(payload if isinstance(payload, dict) else {})

    # ===== 投递 =====

    def _ensure_apply_entry(self, state: dict[str, Any]) -> None:
        blocker = detect_blocker(state)
        if blocker is not None:
            raise blocker_failure(blocker, state)
        present = state.get("found")
        if present is None:
            # 就绪探针返回的是 matched（数量），没有 found 字段。
            present = int(state.get("matched", 0) or 0) > 0
        if not present:
            raise SiteFailure(
                FAILURE_SELECTOR_INVALID,
                selector_diagnostic(state, "「立即沟通 / 投递」入口"),
                url=state.get("url") or "",
                title=state.get("title") or "",
            )

    def open_apply(self, client: CdpClient, job: Any) -> None:
        url = getattr(job, "source_url", "") or ""
        if not url:
            raise SiteFailure(
                FAILURE_SELECTOR_INVALID, "该岗位没有投递链接，无法自动投递"
            )
        # 复用同一标签页导航到岗位详情，并等到入口真正出现。
        previous = _current_url(client)
        client.navigate(url)
        self._await_ready(
            client,
            selector=_SELECTORS["apply_entry"],
            expected="「立即沟通 / 投递」入口",
            allow_empty=False,
            target_url=url,
            previous_url=previous,
        )
        state = _as_payload(client.evaluate(_apply_entry_script()))
        self._ensure_apply_entry(state if isinstance(state, dict) else {})

    def fill_and_submit(
        self, client: CdpClient, data: dict[str, Any], greeting: str
    ) -> ApplyOutcome:
        engine = FormEngine()
        # 1) 确认入口仍在（页面可能已跳走）。
        entry_state = _as_payload(client.evaluate(_apply_entry_script()))
        self._ensure_apply_entry(entry_state if isinstance(entry_state, dict) else {})
        # 2) 点击投递入口，弹出沟通 / 表单。
        client.evaluate(_click_script(_SELECTORS["apply_entry"], "rf:click-apply"))
        # 3) 通用表单理解 + 填写（站点无关）。
        controls = engine.read_controls(client)
        mappings = engine.match_fields(controls, data)
        engine.apply(client, mappings)
        # 4) 招呼语。
        greeting_state = _as_payload(client.evaluate(_greeting_state_script()))
        greeting_state = greeting_state if isinstance(greeting_state, dict) else {}
        if greeting_state.get("required") and not greeting.strip():
            raise SiteFailure(
                FAILURE_GREETING_MISSING,
                "该岗位投递必须填写招呼语：请在投递队列里为它填写，或设置默认招呼语",
                url=greeting_state.get("url") or "",
                title=greeting_state.get("title") or "",
            )
        if greeting.strip() and greeting_state.get("found"):
            client.evaluate(_fill_greeting_script(greeting))
        # 5) 提交并读取结果。
        client.evaluate(_click_script(_SELECTORS["submit_button"], "rf:click-submit"))
        result_state = _as_payload(client.evaluate(_submit_state_script()))
        return classify_submit_state(
            result_state if isinstance(result_state, dict) else {}, greeting=greeting
        )


__all__ = [
    "BOSS_DISPLAY_NAME",
    "BOSS_HOSTS",
    "BOSS_KEY",
    "BossAdapter",
    "blocker_failure",
    "classify_submit_state",
    "detect_blocker",
    "diagnostic_tail",
    "parse_job_detail",
    "parse_search_payload",
    "readiness_timeout_failure",
    "selector_diagnostic",
]
