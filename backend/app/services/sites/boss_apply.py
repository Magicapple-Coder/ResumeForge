"""BOSS 沟通入口、跨页导航、招呼语填写、可信点击与发送结果判定。

现版（2026 年实测）交互形态，与旧实现的两点根本差异：

1. **入口按钮只响应可信用户事件**。岗位详情页的「立即沟通 / 继续沟通」对
   ``element.click()`` 这类 ``isTrusted=false`` 的合成事件没有反应（页面纹丝不动），
   必须用 CDP ``Input.dispatchMouseEvent`` 在按钮真实坐标上发起鼠标按下/抬起。
2. **点击后是整页跳转到 ``/web/geek/chat`` 聊天页**，不是在岗位详情页里弹出聊天层。
   聊天输入框是 ``#chat-input``（``div.chat-input[contenteditable=true]``），发送按钮是
   ``button.btn-send``（空内容时带 ``disabled`` class）。因此流程必须能跨导航等待，
   不能再用"仍停留在岗位页"作为成功前提。

两条 2026-09-20 真实投递失败换来的加固（都用真实浏览器复现验证过）：

3. **点击前必须确保窗口可见**。浏览器窗口最小化 / 被完全遮挡 / 位于未激活的虚拟桌面时，
   页面 ``document.visibilityState`` 为 ``"hidden"``，BOSS 对这种页面上的点击**静默忽略**
   （真实用户不可能点击看不见的页面）——事件以 ``isTrusted=true`` 正常到达按钮，但页面
   毫无反应，投递最终在"等聊天输入框"上超时。``Page.bringToFront`` 救不了最小化的窗口，
   必须走 ``Browser.setWindowBounds``（见 ``cdp_client.WindowAwareMixin``）。
4. **点击后兼容"聊天页开在新标签页"**。真实环境里见过聊天页以新标签页打开、原标签页
   停在岗位详情的情况；等待循环会比对点击前后的标签页快照，把**新出现**的聊天标签页
   收养为后续填写/发送的目标。只收养新标签页：点击前就已存在的聊天标签页（可能是用户
   自己开着的旧会话）绝不能碰，否则招呼语会发进错误的会话。
5. **兼容"新会话不跳聊天页"的对话框形态**（2026-09-20 真实发现）：对从未沟通过的岗位，
   点击「立即沟通」后 BOSS 在**详情页内弹出打招呼对话框**（``.startchat-dialog``，输入框是
   ``.dialog-container textarea``，发送按钮是 ``div.send-message``——不是 button、类名不含
   btn）。BOSS 打开对话框时会**自动发出**用户在站点里配置的默认招呼语（对话框显示
   「已发送 …」），我们的招呼语作为追加消息填写发送。成功判定必须排除"对话框开着、
   草稿没发出去"的反例（见 ``_submit_state_script``）。

发送按钮同样用可信点击；发送成功以聊天页出现包含招呼语的**本人消息气泡**（或对话框
「已发送」态）为准。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from ...models.apply import FAILURE_GREETING_MISSING, FAILURE_SELECTOR_INVALID
from ..browser.cdp_client import CdpClient, CdpError
from ..browser.page_ready import wait_for_page_state
from .base import ApplyOutcome, SiteFailure
from .boss_page import (
    CHAT_PAGE_PATH,
    _SELECTORS,
    _as_payload,
    _blocker_js,
    _current_url,
    blocker_failure,
    detect_blocker,
    same_target_page,
    selector_diagnostic,
)

logger = logging.getLogger(__name__)

# 可信鼠标事件在按下/抬起之间的短暂停顿（秒），给页面事件处理留出时间。
_TRUSTED_CLICK_STEP_SECONDS = 0.06


def _entry_script(marker: str, *, click: bool) -> str:
    action = "node.click();" if click else ""
    return f"""(() => {{ /* {marker} */
  const ENTRY = {json.dumps(_SELECTORS["apply_entry"])};
{_blocker_js()}
  const labels = ['立即沟通', '继续沟通', '开始沟通', '投递简历', '立即申请'];
  const candidates = [...new Set([
    ...document.querySelectorAll(ENTRY),
    ...document.querySelectorAll("button, a, [role='button']")
  ])];
  const visible = (node) => !!(node && node.getClientRects().length);
  const label = (node) => ((node.innerText || node.textContent ||
    node.getAttribute('aria-label') || node.getAttribute('title') || '')).trim();
  const node = candidates.find((item) => visible(item) &&
    !item.disabled && labels.some((word) => label(item).includes(word)));
  if (node) {{ {action} }}
  return JSON.stringify({{
    ok: !!node, found: !!node, matched: node ? 1 : 0,
    label: node ? label(node) : '', url: location.href,
    title: document.title || '',
    captcha: shown(CAPTCHA),
    login_required: shown(LOGIN)
  }});
}})()"""


def _apply_entry_script() -> str:
    return _entry_script("rf:apply-entry", click=False)


def _click_apply_script() -> str:
    """旧的合成点击探针，仅保留用于离线对照；生产流程已改用可信鼠标事件。"""
    return _entry_script("rf:click-apply", click=True)


def _entry_rect_script() -> str:
    """定位沟通入口并返回其视口中心坐标（供可信鼠标点击）。"""
    return f"""(() => {{ /* rf:entry-rect */
  const ENTRY = {json.dumps(_SELECTORS["apply_entry"])};
{_blocker_js()}
  const labels = ['立即沟通', '继续沟通', '开始沟通', '投递简历', '立即申请'];
  const candidates = [...new Set([
    ...document.querySelectorAll(ENTRY),
    ...document.querySelectorAll("button, a, [role='button']")
  ])];
  const visible = (node) => {{
    if (!node || node.disabled) return false;
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return rect.width > 5 && rect.height > 5 &&
      style.display !== 'none' && style.visibility !== 'hidden';
  }};
  const label = (node) => ((node.innerText || node.textContent ||
    node.getAttribute('aria-label') || node.getAttribute('title') || '')).trim();
  const node = candidates.find((item) => visible(item) &&
    labels.some((word) => label(item).includes(word)));
  let rect = null;
  if (node) {{ node.scrollIntoView({{ block: 'center' }}); rect = node.getBoundingClientRect(); }}
  return JSON.stringify({{
    ok: !!node, found: !!node, matched: node ? 1 : 0,
    label: node ? label(node) : '',
    x: rect ? rect.x + rect.width / 2 : 0,
    y: rect ? rect.y + rect.height / 2 : 0,
    width: rect ? rect.width : 0, height: rect ? rect.height : 0,
    url: location.href, title: document.title || '',
    captcha: shown(CAPTCHA), login_required: shown(LOGIN)
  }});
}})()"""


# 定位聊天输入框的公共 JS 片段（**填写与状态检查必须用同一份**，否则"检查说找到了、
# 填写却找不到"，两边各改一次就会漂移）。要求调用方先定义好 ``INPUT``。
#
# 三步走，**每一步都比上一步更宽松，但都守在"聊天/对话框容器内"**：
# 1. 现有的类选择器（覆盖现版与几个历史形态）；
# 2. 找**可见且未禁用**的那个（而不是第一个命中的）；
# 3. 站点把输入框的类名换掉时的兜底：在聊天 / 对话框容器里找 textarea / contenteditable。
#
# **容器兜底只认 textarea 与 contenteditable，绝不接受 `<input>`**——这一条是 2026-09-21 在
# 真实聊天页上实测撞出来的：聊天页在没有打开会话时**根本没有输入框**，而 `.chat-container`
# 里有一个「搜索30天内的联系人」的 `<input class="boss-search-input">`，它可见、未禁用、
# 尺寸也正常，于是"容器内找输入框"会**稳稳地命中搜索框**——差一步就把招呼语打进站点的搜索框。
# 消息框（textarea / contenteditable）与搜索框（input）在形态上本来就是两类，用这个区分比
# 用容器范围可靠得多。**选择器那条路仍然接受 input**（它可能是 `#chat-input` 这类明确命中的），
# 只是额外挡掉"看起来是搜索框"的——收紧兜底不能顺手把既有能力也砍掉。
#
# 这条纪律的方向始终是**"宁可不做，也不能做错"**：找不到会如实报"页面结构可能已变化"并停下，
# 而认错一次就是一条发错地方的消息。
_CHAT_INPUT_FINDER_JS = """
  const CHAT_SCOPES = ['.chat-container', '.chat-content', '.chat-box', '.dialog-wrap',
    '.dialog-container', '[class*=chat-]', '[class*=dialog]'];
  const SEARCH_WORDS = ['搜索', '查找', 'search'];
  const rectVisible = (node) => {
    if (!node) return false;
    const rect = node.getBoundingClientRect();
    return rect.width > 5 && rect.height > 5;
  };
  const looksLikeSearch = (node) => {
    const hint = (node.getAttribute('placeholder') || '') + ' ' +
      (node.getAttribute('aria-label') || '') + ' ' +
      ((node.getAttribute('class') || '') + ' ' + (node.getAttribute('type') || '')).toLowerCase();
    return SEARCH_WORDS.some((word) => hint.includes(word));
  };
  const basic = (node) => !!node && !node.disabled && !node.readOnly &&
    !looksLikeSearch(node) && rectVisible(node);
  // 选择器路径：**信我们自己的选择器**（它覆盖现版与几个历史形态，输入框可能是 input），
  // 只额外挡掉"看起来是搜索框"的，免得哪天选择器写宽了误伤。
  const usableBySelector = (node) => {
    if (!basic(node)) return false;
    if (node.isContentEditable) return true;
    const tag = (node.tagName || '').toLowerCase();
    if (tag === 'textarea') return true;
    if (tag === 'input') {
      const kind = (node.getAttribute('type') || 'text').toLowerCase();
      return kind === 'text' || kind === 'search';
    }
    return false;
  };
  // 容器兜底：**只认 textarea 与 contenteditable**。消息框不是这两者就是 input，
  // 而 input 在聊天页上十有八九是"搜索联系人"——实测就是这么撞上的。
  const usableByContainer = (node) => {
    if (!basic(node)) return false;
    const tag = (node.tagName || '').toLowerCase();
    return node.isContentEditable || tag === 'textarea';
  };
  const findChatInput = () => {
    const direct = [...document.querySelectorAll(INPUT)].find(usableBySelector);
    if (direct) return { node: direct, matched_by: 'selector' };
    for (const scope of CHAT_SCOPES) {
      for (const box of document.querySelectorAll(scope)) {
        const hit = [...box.querySelectorAll("textarea, [contenteditable='true']")]
          .find(usableByContainer);
        if (hit) return { node: hit, matched_by: 'container' };
      }
    }
    return { node: null, matched_by: '' };
  };
"""


def _greeting_state_script() -> str:
    return f"""(() => {{ /* rf:greeting-state */
  const INPUT = {json.dumps(_SELECTORS["greeting_input"])};
{_CHAT_INPUT_FINDER_JS}
{_blocker_js()}
  const hit = findChatInput();
  const node = hit.node;
  return JSON.stringify({{
    url: location.href, title: document.title || '',
    found: !!node, matched: node ? 1 : 0,
    matched_by: hit.matched_by,
    required: !!(node && (node.required || node.getAttribute('required') !== null)),
    kind: node ? (node.isContentEditable ? 'contenteditable' : node.tagName.toLowerCase()) : '',
    captcha: shown(CAPTCHA),
    login_required: shown(LOGIN)
  }});
}})()"""


def _chat_state_script() -> str:
    """点击沟通入口后的页面状态：是否已到聊天页、输入框是否可用、当前会话是谁。

    ready 判据只看"可见的聊天输入框"——现版是整页跳转到 ``/web/geek/chat``，
    但保留对"页内聊天弹层"形态的兼容；``on_chat`` / ``position`` / ``name`` 仅作诊断。
    """
    return f"""(() => {{ /* rf:chat-state */
  const INPUT = {json.dumps(_SELECTORS["greeting_input"])};
{_blocker_js()}
  const url = location.href;
  const onChat = /\\/web\\/geek\\/chat/.test(url);
  const visible = (node) => {{
    if (!node || node.disabled) return false;
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return rect.width > 5 && rect.height > 5 &&
      style.display !== 'none' && style.visibility !== 'hidden';
  }};
  const node = [...document.querySelectorAll(INPUT)].find(visible);
  const text = (sel) => {{
    const hit = document.querySelector(sel);
    return hit ? (hit.innerText || '').trim() : '';
  }};
  // 可见的模态弹窗（隐藏的模板不计）：新会话可能出现"发送简历/完善简历"之类的拦截。
  const dialog = [...document.querySelectorAll(
      '.dialog-wrap, [role=dialog], .dialog-container, .modal-mask, [class*=modal]'
    )].filter(visible).map((n) => (n.innerText || '').trim()).filter(Boolean)[0] || '';
  return JSON.stringify({{
    url, title: document.title || '',
    on_chat: onChat,
    found: !!node, input_found: !!node, matched: node ? 1 : 0,
    kind: node ? (node.isContentEditable ? 'contenteditable' : node.tagName.toLowerCase()) : '',
    position: text('.position-name, .chat-position-content .position-name').slice(0, 60),
    name: text('.name-text, .chat-person .name, .geek-chat-name').slice(0, 30),
    dialog: dialog.slice(0, 120),
    captcha: shown(CAPTCHA),
    login_required: shown(LOGIN)
  }});
}})()"""


def _fill_greeting_script(greeting: str) -> str:
    return f"""(() => {{ /* rf:fill-greeting */
  const INPUT = {json.dumps(_SELECTORS["greeting_input"])};
  const TEXT = {json.dumps(greeting)};
{_CHAT_INPUT_FINDER_JS}
  const hit = findChatInput();
  const node = hit.node;
  if (!node) return JSON.stringify({{ ok: false, matched: 0, matched_by: '',
    url: location.href, title: document.title }});
  node.focus();
  if (node.isContentEditable) {{
    node.textContent = TEXT;
  }} else {{
    const owner = node.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype :
      HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(owner, 'value');
    if (setter && setter.set) setter.set.call(node, TEXT); else node.value = TEXT;
  }}
  try {{
    node.dispatchEvent(new InputEvent('input', {{
      bubbles: true, inputType: 'insertText', data: TEXT
    }}));
  }} catch (error) {{
    node.dispatchEvent(new Event('input', {{ bubbles: true }}));
  }}
  node.dispatchEvent(new Event('change', {{ bubbles: true }}));
  const value = node.isContentEditable ? node.textContent : node.value;
  return JSON.stringify({{ ok: value === TEXT, matched: 1, value,
    matched_by: hit.matched_by,
    url: location.href, title: document.title }});
}})()"""


def _send_rect_script() -> str:
    """定位聊天页发送按钮并返回坐标；空内容时按钮带 ``disabled`` class，一并上报。"""
    return f"""(() => {{ /* rf:send-rect */
  const SEND = {json.dumps(_SELECTORS["greeting_send"])};
{_blocker_js()}
  const visible = (node) => {{
    if (!node) return false;
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return rect.width > 5 && rect.height > 5 &&
      style.display !== 'none' && style.visibility !== 'hidden';
  }};
  const label = (node) => ((node.innerText || node.textContent ||
    node.getAttribute('aria-label') || node.getAttribute('title') || '')).trim();
  const candidates = [...new Set([
    ...document.querySelectorAll(SEND),
    ...document.querySelectorAll("button, [role='button']")
  ])];
  const sendWords = ['发送', '发出', '发送消息'];
  const isSend = (node) => !node.disabled &&
    !node.classList.contains('disabled') &&
    sendWords.some((word) => label(node).includes(word));
  const node = candidates.find((item) => visible(item) && isSend(item));
  const anySend = candidates.find((item) => visible(item) &&
    sendWords.some((word) => label(item).includes(word)));
  let rect = null;
  if (node) {{ node.scrollIntoView({{ block: 'center' }}); rect = node.getBoundingClientRect(); }}
  return JSON.stringify({{
    ok: !!node, found: !!node,
    matched: candidates.filter((n) => visible(n) &&
      sendWords.some((w) => label(n).includes(w))).length,
    disabled: !!anySend && !node,
    label: node ? label(node) : (anySend ? label(anySend) : ''),
    x: rect ? rect.x + rect.width / 2 : 0,
    y: rect ? rect.y + rect.height / 2 : 0,
    width: rect ? rect.width : 0, height: rect ? rect.height : 0,
    url: location.href, title: document.title || '',
    captcha: shown(CAPTCHA), login_required: shown(LOGIN)
  }});
}})()"""


def _click_send_script() -> str:
    """旧的合成点击探针，仅保留用于离线对照；生产流程已改用可信鼠标事件。"""
    return f"""(() => {{ /* rf:click-send */
  const SEND = {json.dumps(_SELECTORS["greeting_send"])};
  const scope = document.querySelector(
    '.dialog-container, .chat-container, .conversation-container, [class*=chat]'
  ) || document;
  const candidates = [...new Set([
    ...scope.querySelectorAll(SEND),
    ...scope.querySelectorAll("button, [role='button']")
  ])];
  const label = (node) => ((node.innerText || node.textContent ||
    node.getAttribute('aria-label') || node.getAttribute('title') || '')).trim();
  const node = candidates.find((item) => item.getClientRects().length &&
    !item.disabled && ['发送', '发出', '发送消息'].some((word) => label(item).includes(word)));
  if (node) node.click();
  return JSON.stringify({{
    ok: !!node, matched: node ? 1 : 0, label: node ? label(node) : '',
    url: location.href, title: document.title || ''
  }});
}})()"""


def _click_script(selector: str, marker: str) -> str:
    return f"""(() => {{ /* {marker} */
  const node = document.querySelector({json.dumps(selector)});
  if (!node) return JSON.stringify({{ ok: false, matched: 0 }});
  node.click();
  return JSON.stringify({{ ok: true, matched: 1 }});
}})()"""


def _submit_state_script(greeting: str = "") -> str:
    return f"""(() => {{ /* rf:submit-state */
{_blocker_js()}
  const TEXT = {json.dumps(greeting.strip())};
  const MINE = {json.dumps(_SELECTORS["my_message"])};
  const body = (document.body && document.body.innerText) || '';
  const successWords = ['发送成功', '沟通成功', '消息已发送'];
  const outgoing = [...document.querySelectorAll(MINE)];
  const sentMessage = !!TEXT && outgoing.some((node) =>
    (node.innerText || node.textContent || '').trim().includes(TEXT));
  const toastSuccess = successWords.some((word) => body.includes(word));
  // startchat 打招呼对话框（2026-09-20 实测的新会话形态：点击沟通后不跳聊天页，
  // 而是详情页弹出对话框）。三种"已发出"的形态都算成功：
  //   a) 对话框关闭（发送成功的常规收尾）；
  //   b) 对话框切到「已发送」预览态且草稿已不在输入框里；
  //   c) 预览文本里出现我们刚发的那句话。
  // 反例必须排除：对话框开着、输入框里还躺着我们没发出去的草稿（点击没生效）——不算。
  const dialogState = (() => {{
    const dialog = document.querySelector('.startchat-dialog, .dialog-container');
    if (!dialog) return {{ present: false, visible: false, text: '', draft: '' }};
    const visible = !!dialog.getClientRects().length;
    const text = visible ? (dialog.innerText || '') : '';
    const ta = dialog.querySelector('textarea');
    const draft = ta ? (ta.value || '').trim() : '';
    return {{ present: true, visible, text, draft }};
  }})();
  const dialogSent =
    (dialogState.present && !dialogState.visible) ||
    (dialogState.visible && dialogState.text.includes('已发送') && dialogState.draft !== TEXT) ||
    (dialogState.visible && !!TEXT && dialogState.text.includes(TEXT));
  return JSON.stringify({{
    url: location.href, title: document.title || '',
    captcha: shown(CAPTCHA),
    login_required: shown(LOGIN),
    sent_message: sentMessage || dialogSent,
    success: sentMessage || toastSuccess || dialogSent,
    matched: outgoing.length
  }});
}})()"""


def classify_submit_state(state: dict[str, Any], greeting: str = "") -> ApplyOutcome:
    blocker = detect_blocker(state)
    if blocker is not None:
        raise blocker_failure(blocker, state)
    if state.get("success"):
        return ApplyOutcome(success=True, greeting_sent=greeting)
    raise SiteFailure(
        FAILURE_SELECTOR_INVALID,
        selector_diagnostic(state, "发送结果确认（已出现本人消息或“发送成功”提示）"),
        url=state.get("url") or "",
        title=state.get("title") or "",
    )


class BossApplyMixin:
    """BOSS 自动沟通流程：可信点击沟通入口 → 跨页进入聊天页 → 填招呼语 → 可信点击发送。"""

    def _wait_state(
        self,
        client: CdpClient,
        initial: dict[str, Any],
        script: str,
        *,
        ready,
        expected: str,
        probe_override=None,
    ) -> dict[str, Any]:
        first = True

        def _probe() -> Any:
            nonlocal first
            if first:
                first = False
                return initial
            if probe_override is not None:
                try:
                    return probe_override()
                except CdpError:
                    return {}
            try:
                value = _as_payload(client.evaluate(script))
            except CdpError:
                # 点击入口会触发整页导航，导航瞬间的 evaluate 可能短暂失败——
                # 这属于"新文档还没就绪"，按未就绪继续轮询，而不是直接打死整个投递。
                return {}
            return value if isinstance(value, dict) else {}

        def _blocker(state: dict[str, Any]) -> SiteFailure | None:
            kind = detect_blocker(state)
            return blocker_failure(kind, state) if kind is not None else None

        def _timeout(state: dict[str, Any]) -> SiteFailure:
            return SiteFailure(
                FAILURE_SELECTOR_INVALID,
                selector_diagnostic(state, expected),
                url=state.get("url") or "",
                title=state.get("title") or "",
            )

        return wait_for_page_state(
            _probe,
            is_ready=ready,
            blocker=_blocker,
            on_timeout=_timeout,
            config=self._ready_wait,
        )

    def _ensure_apply_entry(self, state: dict[str, Any]) -> None:
        blocker = detect_blocker(state)
        if blocker is not None:
            raise blocker_failure(blocker, state)
        present = state.get("found")
        if present is None:
            present = int(state.get("matched", 0) or 0) > 0
        if not present:
            raise SiteFailure(
                FAILURE_SELECTOR_INVALID,
                selector_diagnostic(state, "“立即沟通 / 继续沟通”入口"),
                url=state.get("url") or "",
                title=state.get("title") or "",
            )

    def _trusted_click(self, client: CdpClient, x: float, y: float) -> None:
        """在视口坐标上发起可信鼠标点击（``Input.dispatchMouseEvent``）。

        BOSS 现版按钮忽略合成 ``element.click()``（isTrusted=false），只认真实输入事件。
        点击前先做**窗口可见性保障**（2026-09-20 真实失败根因：窗口最小化/被遮挡时页面
        ``visibilityState`` 为 ``hidden``，BOSS 对隐藏页面上的点击静默忽略——事件正常到达、
        页面毫无反应）。``Page.bringToFront`` 与移动事件失败不致命；按下/抬起失败则抛出
        （归为网络类失败）。
        """
        try:
            client.send("Page.enable")
            client.send("Page.bringToFront")
        except CdpError:
            pass
        ensure = getattr(client, "ensure_page_visible", None)
        if ensure is not None and not ensure():
            # 无法还原窗口（无头/远程会话等）不在这里打死流程：继续点击并把情况写日志，
            # 真正点不动时由既有的等待超时给出带 URL/标题的诊断。
            logger.warning("未能把投递专用浏览器窗口恢复到可见状态，点击可能不会生效")
        client.send(
            "Input.dispatchMouseEvent",
            {"type": "mouseMoved", "x": x, "y": y, "button": "none", "buttons": 0},
        )
        time.sleep(_TRUSTED_CLICK_STEP_SECONDS)
        client.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": x,
                "y": y,
                "button": "left",
                "buttons": 1,
                "clickCount": 1,
            },
        )
        time.sleep(_TRUSTED_CLICK_STEP_SECONDS)
        client.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "x": x,
                "y": y,
                "button": "left",
                "buttons": 0,
                "clickCount": 1,
            },
        )

    def _page_snapshot(self, client: CdpClient) -> set[str]:
        """当前全部 page 目标的 id 快照（供"点击后新开标签页"比对）。"""
        try:
            return {
                str(item.get("id", ""))
                for item in client.list_targets()
                if item.get("type") == "page"
            }
        except CdpError:
            return set()

    def open_apply(self, client: CdpClient, job: Any) -> None:
        url = getattr(job, "source_url", "") or ""
        if not url:
            raise SiteFailure(FAILURE_SELECTOR_INVALID, "该岗位没有投递链接，无法自动投递")
        _current_url(client)
        client.navigate(url)
        initial = _as_payload(client.evaluate(_apply_entry_script()))
        state = initial if isinstance(initial, dict) else {}
        state = self._wait_state(
            client,
            state,
            _apply_entry_script(),
            ready=lambda item: bool(item.get("found"))
            and same_target_page(str(item.get("url") or ""), url),
            expected="“立即沟通 / 继续沟通”入口",
        )
        self._ensure_apply_entry(state)

    def _wait_entry_rect(self, client: CdpClient) -> dict[str, Any]:
        """在岗位详情页拿到沟通入口的真实坐标。"""
        try:
            initial = _as_payload(client.evaluate(_entry_rect_script()))
        except CdpError:
            initial = {}
        state = initial if isinstance(initial, dict) else {}
        state = self._wait_state(
            client,
            state,
            _entry_rect_script(),
            ready=lambda item: bool(item.get("found"))
            and float(item.get("width", 0) or 0) > 0,
            expected="可点击的“立即沟通 / 继续沟通”入口",
        )
        self._ensure_apply_entry(state)
        return state

    def _wait_chat_ready(
        self, client: CdpClient, *, known_page_ids: set[str] | None = None
    ) -> dict[str, Any]:
        """点击入口后等待聊天页（或页内聊天层）的输入框可用。

        ``known_page_ids`` 是点击**前**的 page 目标 id 快照。等待期间若当前页迟迟没有
        聊天输入框、而浏览器里**新出现**了一个聊天页标签页（id 不在快照里），就切换过去
        继续等待——聊天页开在新标签页是真实环境里出现过的形态。只收养新标签页：点击前
        就存在的聊天标签页可能是用户自己开着的旧会话，绝不能碰，否则招呼语会发错会话。
        """
        try:
            initial = _as_payload(client.evaluate(_chat_state_script()))
        except CdpError:
            # 点击入口触发整页导航，第一次探测就可能撞上"执行上下文已销毁"。
            initial = {}
        state = initial if isinstance(initial, dict) else {}

        adopted: dict[str, bool] = {"done": False}

        def _probe() -> dict[str, Any]:
            value = _as_payload(client.evaluate(_chat_state_script()))
            if isinstance(value, dict) and value.get("input_found"):
                return value
            # 当前页还没就绪：若允许，把"点击后新出现的聊天标签页"收养过来再探一次。
            if known_page_ids is not None and not adopted["done"]:
                adopted["done"] = True  # 无论结果如何只尝试一次，避免反复跳标签页
                candidate = self._new_chat_tab_id(client, known_page_ids)
                if candidate:
                    switch = getattr(client, "switch_to_target", None)
                    if switch is not None and switch(candidate):
                        logger.info("聊天页在新标签页打开，已切换过去继续投递")
                        try:
                            value = _as_payload(client.evaluate(_chat_state_script()))
                        except CdpError:
                            value = {}
            return value if isinstance(value, dict) else {}

        state = self._wait_state(
            client,
            state,
            _chat_state_script(),
            probe_override=_probe,
            ready=lambda item: bool(item.get("input_found")),
            expected="聊天页输入框（点击沟通后进入 /web/geek/chat）",
        )
        return state

    def _new_chat_tab_id(self, client: CdpClient, known_page_ids: set[str]) -> str:
        """在标签页列表里找出点击后新出现的聊天页目标 id；没有返回空串。"""
        try:
            targets = client.list_targets()
        except CdpError:
            return ""
        for item in targets:
            if item.get("type") != "page":
                continue
            target_id = str(item.get("id", ""))
            url = str(item.get("url") or "")
            if not target_id or target_id in known_page_ids:
                continue
            if CHAT_PAGE_PATH in url:
                return target_id
        return ""

    def _wait_send_ready(self, client: CdpClient) -> dict[str, Any]:
        """填入招呼语后等待发送按钮变为可用（disabled class 移除），返回其坐标。"""
        try:
            initial = _as_payload(client.evaluate(_send_rect_script()))
        except CdpError:
            initial = {}
        state = initial if isinstance(initial, dict) else {}
        state = self._wait_state(
            client,
            state,
            _send_rect_script(),
            ready=lambda item: bool(item.get("found"))
            and not item.get("disabled")
            and float(item.get("width", 0) or 0) > 0,
            expected="可点击的“发送”按钮（填入招呼语后启用）",
        )
        return state

    def fill_and_submit(
        self, client: CdpClient, data: dict[str, Any], greeting: str
    ) -> ApplyOutcome:
        greeting = (greeting or "").strip()

        # 1) 岗位详情页：定位沟通入口坐标（open_apply 已确认过入口，这里取坐标并再验一次）。
        entry = self._wait_entry_rect(client)

        # 2) 招呼语是 BOSS 沟通链路的必填内容；在点击入口之前就拦下，避免无谓建立会话。
        if not greeting:
            raise SiteFailure(
                FAILURE_GREETING_MISSING,
                "该岗位投递必须填写招呼语：请在投递队列里为它填写，或设置默认招呼语",
                url=entry.get("url") or "",
                title=entry.get("title") or "",
            )

        # 3) 可信点击沟通入口（合成 click 对现版按钮无效），随后整页跳转到聊天页。
        #    快照点击前的标签页集合：聊天页若开在**新**标签页里，等待循环要靠它收养；
        #    点击前就存在的聊天标签页不属于这次投递，绝不能碰。
        page_ids_before_click = self._page_snapshot(client)
        self._trusted_click(client, float(entry["x"]), float(entry["y"]))
        self._wait_chat_ready(client, known_page_ids=page_ids_before_click)

        # 4) 在聊天页写入招呼语。
        filled = _as_payload(client.evaluate(_fill_greeting_script(greeting)))
        fill_state = filled if isinstance(filled, dict) else {}
        if fill_state.get("ok") is not True:
            raise SiteFailure(
                FAILURE_SELECTOR_INVALID,
                selector_diagnostic(fill_state, "可写入的聊天输入框"),
                url=fill_state.get("url") or "",
                title=fill_state.get("title") or "",
            )

        # 5) 等发送按钮启用后可信点击。
        send = self._wait_send_ready(client)
        self._trusted_click(client, float(send["x"]), float(send["y"]))

        # 6) 等待本人消息气泡出现作为发送成功凭据。
        initial_result = _as_payload(client.evaluate(_submit_state_script(greeting)))
        result = initial_result if isinstance(initial_result, dict) else {}
        result = self._wait_state(
            client,
            result,
            _submit_state_script(greeting),
            ready=lambda item: bool(item.get("success")),
            expected="发送结果确认（已出现本人消息或“发送成功”提示）",
        )
        return classify_submit_state(result, greeting=greeting)


__all__ = [
    "BossApplyMixin",
    "_apply_entry_script",
    "_chat_state_script",
    "_click_apply_script",
    "_click_script",
    "_click_send_script",
    "_entry_rect_script",
    "_fill_greeting_script",
    "_greeting_state_script",
    "_send_rect_script",
    "_submit_state_script",
    "classify_submit_state",
]
