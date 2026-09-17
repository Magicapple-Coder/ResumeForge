"""通用表单理解与填写引擎（站点无关）。

它回答两个问题：
1. **页面上有哪些可见控件，各是什么类型**（文本 / 下拉 / 单选 / 复选框 / 富文本 / 文件上传）。
2. **简历与资料里的字段该填到哪个控件里**——靠 ``label`` / ``placeholder`` / ``aria-label`` /
   ``name`` / 邻近文本做启发式映射，而不是把某站点的选择器堆死。

这条"启发式映射 + 站点适配器兜底"的取舍是设计的关键决策：站点选择器会变，字段语义相对稳定，
所以**理解表单**用通用逻辑，**定位站点特有元素**才交给适配器。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from ..browser.cdp_client import CdpClient

logger = logging.getLogger(__name__)

CONTROL_TYPES = (
    "text",
    "textarea",
    "select",
    "radio",
    "checkbox",
    "richtext",
    "file",
    "unknown",
)

# 读取页面可见控件的脚本。给每个控件打上 data-rf-index，保证生成的 selector 唯一。
CONTROLS_SCRIPT = "".join(
    [
        "(() => { /* rf:form-controls */\n",
        "  const visible = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);\n",
        "  const text = (el) => (el ? (el.textContent || '').replace(/\\s+/g, ' ').trim() : '');\n",
        "  const labelFor = (el) => {\n",
        "    if (el.id) {\n",
        "      const l = document.querySelector('label[for=\"' + el.id + '\"]');\n",
        "      if (l) { return text(l); }\n",
        "    }\n",
        "    const wrap = el.closest('label');\n",
        "    if (wrap) { return text(wrap); }\n",
        "    return (el.getAttribute('aria-label') || '').trim();\n",
        "  };\n",
        "  const nodes = [...document.querySelectorAll('input, textarea, select, [contenteditable=\"true\"]')];\n",
        "  const out = [];\n",
        "  let idx = 0;\n",
        "  for (const el of nodes) {\n",
        "    const tag = el.tagName.toLowerCase();\n",
        "    let type = 'text';\n",
        "    if (tag === 'textarea') { type = 'textarea'; }\n",
        "    else if (tag === 'select') { type = 'select'; }\n",
        "    else if (el.getAttribute('contenteditable') === 'true') { type = 'richtext'; }\n",
        "    else {\n",
        "      const t = (el.getAttribute('type') || 'text').toLowerCase();\n",
        "      if (t === 'file') { type = 'file'; }\n",
        "      else if (t === 'radio') { type = 'radio'; }\n",
        "      else if (t === 'checkbox') { type = 'checkbox'; }\n",
        "      else if (t === 'hidden' || t === 'submit' || t === 'button') { continue; }\n",
        "    }\n",
        "    if (type !== 'file' && !visible(el)) { continue; }\n",
        "    el.setAttribute('data-rf-index', String(idx));\n",
        "    const container = el.closest('div, td, li, section, form');\n",
        "    out.push({\n",
        "      index: idx,\n",
        "      type: type,\n",
        "      name: el.getAttribute('name') || '',\n",
        "      label: labelFor(el),\n",
        "      placeholder: el.getAttribute('placeholder') || '',\n",
        "      aria_label: el.getAttribute('aria-label') || '',\n",
        "      required: el.required === true || el.getAttribute('aria-required') === 'true',\n",
        "      selector: '[data-rf-index=\"' + idx + '\"]',\n",
        "      options: tag === 'select'\n",
        "        ? [...el.options].map((o) => (o.textContent || '').trim())\n",
        "        : [],\n",
        "      nearby_text: text(container).slice(0, 120),\n",
        "    });\n",
        "    idx += 1;\n",
        "  }\n",
        "  return JSON.stringify({ url: location.href, title: document.title || '', controls: out });\n",
        "})()",
    ]
)


def _set_value_script(selector: str, value: str, *, textarea: bool) -> str:
    """给输入框赋值并触发 input/change 事件（用原生 setter，绕开前端框架的拦截）。"""
    proto = "HTMLTextAreaElement" if textarea else "HTMLInputElement"
    return "".join(
        [
            "(() => { /* rf:set-value */\n",
            f"  const el = document.querySelector({json.dumps(selector)});\n",
            "  if (!el) { return JSON.stringify({ ok: false }); }\n",
            f"  const setter = Object.getOwnPropertyDescriptor({proto}.prototype, 'value').set;\n",
            f"  setter.call(el, {json.dumps(value)});\n",
            "  el.dispatchEvent(new Event('input', { bubbles: true }));\n",
            "  el.dispatchEvent(new Event('change', { bubbles: true }));\n",
            "  return JSON.stringify({ ok: true });\n",
            "})()",
        ]
    )


def _set_rich_text_script(selector: str, value: str) -> str:
    return "".join(
        [
            "(() => { /* rf:set-richtext */\n",
            f"  const el = document.querySelector({json.dumps(selector)});\n",
            "  if (!el) { return JSON.stringify({ ok: false }); }\n",
            f"  el.textContent = {json.dumps(value)};\n",
            "  el.dispatchEvent(new Event('input', { bubbles: true }));\n",
            "  return JSON.stringify({ ok: true });\n",
            "})()",
        ]
    )


def _click_control_script(selector: str) -> str:
    return "".join(
        [
            "(() => { /* rf:click-control */\n",
            f"  const el = document.querySelector({json.dumps(selector)});\n",
            "  if (!el) { return JSON.stringify({ ok: false }); }\n",
            "  el.click();\n",
            "  return JSON.stringify({ ok: true });\n",
            "})()",
        ]
    )


@dataclass(frozen=True)
class Control:
    """页面上的一个可见控件。"""

    index: int
    type: str = "unknown"
    name: str = ""
    label: str = ""
    placeholder: str = ""
    aria_label: str = ""
    required: bool = False
    selector: str = ""
    options: tuple[str, ...] = ()
    nearby_text: str = ""

    def signature(self) -> str:
        """用于启发式匹配的文本指纹（小写，便于包含判断）。"""
        parts = (self.label, self.placeholder, self.aria_label, self.name, self.nearby_text)
        return " ".join(part for part in parts if part).casefold()


@dataclass(frozen=True)
class FieldMapping:
    """一条"字段 → 控件"的映射。"""

    control: Control
    field: str
    value: Any


# 字段 → 中文/英文同义词。顺序即匹配优先级（越靠前越先分配控件）。
FIELD_SYNONYMS: dict[str, tuple[str, ...]] = {
    "name": ("姓名", "真实姓名", "你的名字", "full name", "fullname", "your name"),
    "phone": ("手机号", "手机", "联系电话", "联系方式", "电话", "phone", "mobile"),
    "email": ("电子邮箱", "邮箱", "电子邮件", "邮件", "email", "e-mail"),
    "city": ("期望城市", "所在城市", "工作城市", "现居", "所在地", "城市", "city"),
    "salary": ("期望薪资", "期望月薪", "薪资", "薪酬", "月薪", "salary"),
    "experience": ("工作经验", "工作年限", "从业年限", "经验", "experience"),
    "education": ("最高学历", "学历", "education"),
    "job_intent": ("求职意向", "意向岗位", "应聘职位", "期望职位", "期望岗位"),
    "resume_file": ("上传简历", "简历附件", "简历文件", "附件简历", "简历", "resume"),
    "summary": ("自我评价", "自我介绍", "个人简介", "个人优势", "简介", "summary", "about"),
}

# 某字段更"适配"的控件类型（命中加权重分，避免把"姓名"填进下拉框）。
FIELD_PREFERRED_TYPES: dict[str, tuple[str, ...]] = {
    "resume_file": ("file",),
    "summary": ("textarea", "richtext"),
    "experience": ("select", "text"),
    "education": ("select", "text"),
}


class FormEngine:
    """通用表单理解与填写。"""

    def snapshot_controls(self, controls: list[dict[str, Any]]) -> list[Control]:
        """把页面快照里的原始控件描述转成 ``Control``（纯函数，便于离线测试）。"""
        result: list[Control] = []
        for raw in controls:
            if not isinstance(raw, dict):
                continue
            control_type = str(raw.get("type", "unknown"))
            if control_type not in CONTROL_TYPES:
                control_type = "unknown"
            try:
                index = int(raw.get("index", len(result)))
            except (TypeError, ValueError):
                index = len(result)
            options = raw.get("options")
            result.append(
                Control(
                    index=index,
                    type=control_type,
                    name=str(raw.get("name", "")),
                    label=str(raw.get("label", "")),
                    placeholder=str(raw.get("placeholder", "")),
                    aria_label=str(raw.get("aria_label", "")),
                    required=bool(raw.get("required", False)),
                    selector=str(raw.get("selector", "")),
                    options=tuple(str(item) for item in options) if isinstance(options, list) else (),
                    nearby_text=str(raw.get("nearby_text", "")),
                )
            )
        return result

    def read_controls(self, client: CdpClient, *, timeout: float | None = None) -> list[Control]:
        """在真实页面上读取控件清单。"""
        payload = client.evaluate(CONTROLS_SCRIPT, timeout=timeout)
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                logger.warning("表单控件快照无法解析")
                return []
        if not isinstance(payload, dict):
            return []
        controls = payload.get("controls")
        if not isinstance(controls, list):
            return []
        return self.snapshot_controls(controls)

    def match_fields(
        self, controls: list[Control], data: dict[str, Any]
    ) -> list[FieldMapping]:
        """把资料/简历字段启发式映射到控件上，一个控件只被分配一次。"""
        mappings: list[FieldMapping] = []
        used: set[int] = set()
        for field, synonyms in FIELD_SYNONYMS.items():
            if field not in data:
                continue
            value = data[field]
            if value is None or value == "":
                continue
            control = self._best_control(controls, synonyms, used, FIELD_PREFERRED_TYPES.get(field))
            if control is None:
                continue
            used.add(control.index)
            mappings.append(FieldMapping(control=control, field=field, value=value))
        return mappings

    @staticmethod
    def _best_control(
        controls: list[Control],
        synonyms: tuple[str, ...],
        used: set[int],
        preferred_types: tuple[str, ...] | None,
    ) -> Control | None:
        best: Control | None = None
        best_score = 0
        for control in controls:
            if control.index in used:
                continue
            signature = control.signature()
            if not signature:
                continue
            score = 0
            for synonym in synonyms:
                needle = synonym.casefold()
                if needle and needle in signature:
                    # 更长的同义词更具体（"工作经验" 比 "经验" 更可信）。
                    score = max(score, len(needle))
            if score <= 0:
                continue
            if preferred_types and control.type in preferred_types:
                score += 5
            if score > best_score:
                best_score = score
                best = control
        return best

    @staticmethod
    def unmapped_required(
        controls: list[Control], mappings: list[FieldMapping]
    ) -> list[Control]:
        """已映射之外、仍然必填的控件（调用方据此给出 warning 或保守跳过）。"""
        mapped = {mapping.control.index for mapping in mappings}
        return [
            control
            for control in controls
            if control.required and control.index not in mapped
        ]

    def apply(self, client: CdpClient, mappings: list[FieldMapping], *, timeout: float | None = None) -> None:
        """逐字段写入页面。"""
        for mapping in mappings:
            control = mapping.control
            if not control.selector:
                continue
            if control.type == "file":
                client.set_file_input(control.selector, [str(mapping.value)], timeout=timeout)
            elif control.type in ("radio", "checkbox"):
                client.evaluate(_click_control_script(control.selector), timeout=timeout)
            elif control.type == "richtext":
                client.evaluate(
                    _set_rich_text_script(control.selector, str(mapping.value)), timeout=timeout
                )
            else:
                client.evaluate(
                    _set_value_script(
                        control.selector, str(mapping.value), textarea=(control.type == "textarea")
                    ),
                    timeout=timeout,
                )


__all__ = [
    "CONTROL_TYPES",
    "CONTROLS_SCRIPT",
    "Control",
    "FIELD_PREFERRED_TYPES",
    "FIELD_SYNONYMS",
    "FieldMapping",
    "FormEngine",
]
