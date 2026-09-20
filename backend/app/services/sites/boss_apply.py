"""BOSS 沟通入口、招呼语填写与发送结果判定。"""
from __future__ import annotations

import json
from typing import Any

from ...models.apply import FAILURE_GREETING_MISSING, FAILURE_SELECTOR_INVALID
from ..browser.cdp_client import CdpClient
from ..browser.page_ready import wait_for_page_state
from .base import ApplyOutcome, SiteFailure
from .boss_page import (
    _blocker_js,
    _SELECTORS,
    _as_payload,
    _current_url,
    _js,
    blocker_failure,
    detect_blocker,
    same_target_page,
    selector_diagnostic,
)


def _entry_script(marker: str, *, click: bool) -> str:
    action = "node.click();" if click else ""
    return f"""(() => {{ /* {marker} */
  const ENTRY = {_js(_SELECTORS["apply_entry"])};
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
    return _entry_script("rf:click-apply", click=True)


def _greeting_state_script() -> str:
    return f"""(() => {{ /* rf:greeting-state */
  const INPUT = {_js(_SELECTORS["greeting_input"])};
{_blocker_js()}
  const nodes = [...document.querySelectorAll(INPUT)];
  const node = nodes.find((item) => item.getClientRects().length && !item.disabled);
  return JSON.stringify({{
    url: location.href, title: document.title || '',
    found: !!node, matched: node ? 1 : 0,
    required: !!(node && (node.required || node.getAttribute('required') !== null)),
    kind: node ? (node.isContentEditable ? 'contenteditable' : node.tagName.toLowerCase()) : '',
    captcha: shown(CAPTCHA),
    login_required: shown(LOGIN)
  }});
}})()"""


def _fill_greeting_script(greeting: str) -> str:
    return f"""(() => {{ /* rf:fill-greeting */
  const INPUT = {_js(_SELECTORS["greeting_input"])};
  const TEXT = {json.dumps(greeting)};
  const node = [...document.querySelectorAll(INPUT)]
    .find((item) => item.getClientRects().length && !item.disabled);
  if (!node) return JSON.stringify({{ ok: false, matched: 0 }});
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
  return JSON.stringify({{ ok: value === TEXT, matched: 1, value }});
}})()"""


def _click_send_script() -> str:
    return f"""(() => {{ /* rf:click-send */
  const SEND = {_js(_SELECTORS["greeting_send"])};
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
  const node = document.querySelector({_js(selector)});
  if (!node) return JSON.stringify({{ ok: false, matched: 0 }});
  node.click();
  return JSON.stringify({{ ok: true, matched: 1 }});
}})()"""


def _submit_state_script(greeting: str = "") -> str:
    return f"""(() => {{ /* rf:submit-state */
{_blocker_js()}
  const TEXT = {json.dumps(greeting.strip())};
  const body = (document.body && document.body.innerText) || '';
  const successWords = ['发送成功', '沟通成功', '消息已发送'];
  const outgoing = [...document.querySelectorAll(
    '.message-item.myself, .message-item.is-self, .chat-message.is-self, ' +
    '[data-from=self], [class*=message][class*=self]'
  )];
  const sentMessage = !!TEXT && outgoing.some((node) =>
    (node.innerText || node.textContent || '').trim().includes(TEXT));
  const toastSuccess = successWords.some((word) => body.includes(word));
  return JSON.stringify({{
    url: location.href, title: document.title || '',
    captcha: shown(CAPTCHA),
    login_required: shown(LOGIN),
    sent_message: sentMessage, success: sentMessage || toastSuccess,
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
    """BOSS 自动沟通流程。"""

    def _wait_state(
        self,
        client: CdpClient,
        initial: dict[str, Any],
        script: str,
        *,
        ready,
        expected: str,
    ) -> dict[str, Any]:
        first = True

        def _probe() -> Any:
            nonlocal first
            if first:
                first = False
                return initial
            value = _as_payload(client.evaluate(script))
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

    def fill_and_submit(
        self, client: CdpClient, data: dict[str, Any], greeting: str
    ) -> ApplyOutcome:
        entry = _as_payload(client.evaluate(_apply_entry_script()))
        self._ensure_apply_entry(entry if isinstance(entry, dict) else {})

        click = _as_payload(client.evaluate(_click_apply_script()))
        click_state = click if isinstance(click, dict) else {}
        # 兼容旧桥接层仅回传 found；真实脚本始终回传明确的 ok。
        if not (click_state.get("ok") is True or click_state.get("found") is True):
            raise SiteFailure(
                FAILURE_SELECTOR_INVALID,
                selector_diagnostic(click_state, "可点击的“立即沟通 / 继续沟通”入口"),
                url=click_state.get("url") or "",
                title=click_state.get("title") or "",
            )

        initial = _as_payload(client.evaluate(_greeting_state_script()))
        composer = initial if isinstance(initial, dict) else {}
        composer = self._wait_state(
            client,
            composer,
            _greeting_state_script(),
            ready=lambda item: bool(item.get("found")),
            expected="聊天输入框（textarea 或 contenteditable）",
        )
        # BOSS 当前是聊天沟通链路，不读取页面上的通用表单控件；否则岗位详情页的搜索框、
        # 登录输入框会被误当成投递字段。保留 data 参数以维持 SiteAdapter 公共签名。
        if composer.get("required") and not greeting.strip():
            raise SiteFailure(
                FAILURE_GREETING_MISSING,
                "该岗位投递必须填写招呼语：请在投递队列里为它填写，或设置默认招呼语",
                url=composer.get("url") or "",
                title=composer.get("title") or "",
            )

        if not greeting.strip():
            client.evaluate(_click_script(_SELECTORS["submit_button"], "rf:click-submit"))
            result = _as_payload(client.evaluate(_submit_state_script()))
            if isinstance(result, dict) and not (
                result.get("success") or detect_blocker(result)
            ):
                result = _as_payload(client.evaluate(_submit_state_script()))
            return classify_submit_state(
                result if isinstance(result, dict) else {}, greeting=greeting
            )

        filled = _as_payload(client.evaluate(_fill_greeting_script(greeting)))
        fill_state = filled if isinstance(filled, dict) else {}
        if fill_state.get("ok") is not True:
            raise SiteFailure(
                FAILURE_SELECTOR_INVALID,
                selector_diagnostic(fill_state, "可写入的聊天输入框"),
                url=fill_state.get("url") or "",
                title=fill_state.get("title") or "",
            )

        clicked = _as_payload(client.evaluate(_click_send_script()))
        click_send = clicked if isinstance(clicked, dict) else {}
        if click_send.get("ok") is not True:
            raise SiteFailure(
                FAILURE_SELECTOR_INVALID,
                selector_diagnostic(click_send, "真实的“发送”按钮"),
                url=click_send.get("url") or "",
                title=click_send.get("title") or "",
            )

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
    "_fill_greeting_script",
    "classify_submit_state",
]
