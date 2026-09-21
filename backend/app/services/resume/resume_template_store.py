"""用户自制简历模板：持久化、清洗与校验。

自制模板是**用户自己写的 HTML**，比内置模板多两层保护：

1. **清洗**：去掉 `<script>` 与可能外链资源的标签。预览和导出都要在浏览器里打开，
   模板不需要脚本（页数自适应的脚本由我们追加），而脚本是最容易写坏的一环。
2. **沙箱渲染**：用 Jinja 的 ``SandboxedEnvironment``，模板里拿不到任意 Python 对象。

模板名与内置模板共用一个命名空间：重名时拒绝保存，否则"选择模板"会指向不确定的一版。
"""
from __future__ import annotations

import logging
import re

from sqlalchemy.orm import Session

from ...models.resume_template import (
    TEMPLATE_KIND_FORMAT,
    TEMPLATE_KIND_STYLE,
    TEMPLATE_KINDS,
    ResumeTemplate,
)
from .resume_templates import (
    DEFAULT_TEMPLATE,
    FORMAT_PRESETS,
    RESUME_TEMPLATES,
    validated_format_config,
)

logger = logging.getLogger(__name__)

MAX_USER_TEMPLATES = 40
MAX_TEMPLATE_HTML_CHARS = 200_000
MAX_TEMPLATE_NAME_CHARS = 40

# 模板名：中文、字母、数字、连字符与下划线，不能以符号开头。
_NAME_RE = re.compile(r"^[\w\u4e00-\u9fff][\w\u4e00-\u9fff\- ]*$")
# 需要剥离的标签：脚本与任何会发起网络请求的元素。
_STRIP_TAG_RE = re.compile(
    r"<\s*(script|iframe|object|embed|base|link)\b[^>]*>.*?<\s*/\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
_STRIP_SELF_CLOSING_RE = re.compile(
    r"<\s*(iframe|object|embed|base|link)\b[^>]*/?>",
    re.IGNORECASE,
)
# 带 http-equiv 的 meta 单独剥：它是**空元素**，永远没有闭合标签，放进上面那条
# 成对匹配的正则里等于永远不生效。它能做两件坏事：refresh 自动跳转到外部地址，
# 以及自带一条 CSP 把应用补的那条顶掉。
_STRIP_META_EQUIV_RE = re.compile(r"<\s*meta\b[^>]*http-equiv\s*=[^>]*>", re.IGNORECASE)
# 单独收尾的 <script src="..."></script> 之类（上面那条要求成对出现，这里兜底）。
_ORPHAN_SCRIPT_RE = re.compile(r"<\s*/?\s*script\b[^>]*>", re.IGNORECASE)
_CSP_META = (
    '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
    "img-src data: blob:; style-src 'unsafe-inline'; script-src 'nonce-{{ csp_nonce }}'; "
    "base-uri 'none'; form-action 'none'\" />"
)


class TemplateError(ValueError):
    """模板不合法：消息直接展示给用户。"""


def sanitize_template_html(html: str) -> str:
    """去掉会执行代码或发起网络请求的内容，并补齐 CSP 与字符集声明。"""
    cleaned = _STRIP_TAG_RE.sub("", html or "")
    cleaned = _STRIP_SELF_CLOSING_RE.sub("", cleaned)
    cleaned = _ORPHAN_SCRIPT_RE.sub("", cleaned)
    cleaned = _STRIP_META_EQUIV_RE.sub("", cleaned)
    if "<meta" not in cleaned.lower() or "charset" not in cleaned.lower():
        cleaned = cleaned.replace(
            "<head>", '<head>\n<meta charset="utf-8" />', 1
        ) if "<head>" in cleaned else cleaned
    # 无条件补上应用的 CSP。此前是"文档里已经出现 Content-Security-Policy 字样就跳过"，
    # 于是模板只要在注释或属性里带上这个词（或自带一条宽松的 CSP meta），就能让应用这条
    # 完全不注入——没有 CSP 之后，事件属性里的脚本会照常执行。
    if "</head>" in cleaned:
        cleaned = cleaned.replace("</head>", f"{_CSP_META}\n</head>", 1)
    else:
        cleaned = f"{_CSP_META}\n{cleaned}"
    return cleaned


def validate_template_name(name: str) -> str:
    """校验自制模板名：非空、长度上限、不与现有模板重名。"""
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise TemplateError("模板名称不能为空")
    if len(cleaned) > MAX_TEMPLATE_NAME_CHARS:
        raise TemplateError(f"模板名称不能超过 {MAX_TEMPLATE_NAME_CHARS} 个字符")
    if not _NAME_RE.match(cleaned):
        raise TemplateError("模板名称只能包含中文、字母、数字、空格、下划线与连字符")
    return cleaned


def validate_template_html(html: str) -> str:
    """校验自制模板 HTML：必须含占位符、拦截脚本注入。"""
    cleaned = (html or "").strip()
    if len(cleaned) < 40:
        raise TemplateError("模板内容太短，请提供完整的 HTML 模板")
    if len(cleaned) > MAX_TEMPLATE_HTML_CHARS:
        raise TemplateError("模板内容过大，请精简后再导入")
    body = cleaned.replace("</head>", "\n</head>", 1)
    if "</head>" not in body and "<body" not in cleaned.lower():
        raise TemplateError("模板必须是一个完整的 HTML 页面（含 <head> 与 <body>）")
    return cleaned


def find_by_name(db: Session, name: str) -> ResumeTemplate | None:
    return db.query(ResumeTemplate).filter(ResumeTemplate.name == name).first()


def list_user_templates(db: Session, kind: str | None = None) -> list[ResumeTemplate]:
    query = db.query(ResumeTemplate)
    if kind in TEMPLATE_KINDS:
        query = query.filter(ResumeTemplate.kind == kind)
    return query.order_by(ResumeTemplate.updated_at.desc()).all()


def get_user_template(db: Session, template_id: int) -> ResumeTemplate | None:
    return db.get(ResumeTemplate, template_id)


def create_user_template(
    db: Session,
    *,
    name: str,
    kind: str = TEMPLATE_KIND_STYLE,
    description: str = "",
    html: str = "",
    config: dict | None = None,
    source_name: str = "",
) -> ResumeTemplate:
    """落库一份自制模板：命名/重名/总量/类型校验与 HTML 消毒都在此。"""
    cleaned_name = validate_template_name(name)
    if find_by_name(db, cleaned_name) is not None:
        raise TemplateError(f"已存在同名模板「{cleaned_name}」，请换一个名称")
    count = db.query(ResumeTemplate).count()
    if count >= MAX_USER_TEMPLATES:
        raise TemplateError(f"自制模板最多 {MAX_USER_TEMPLATES} 个，请先删除不再使用的")
    if kind not in TEMPLATE_KINDS:
        raise TemplateError("模板类型只有「样式模板」与「格式模板」两种")

    if kind == TEMPLATE_KIND_STYLE:
        template_html = sanitize_template_html(validate_template_html(html))
        config = {}
    else:
        template_html = ""
        normalized = validated_format_config(config)
        if not normalized:
            raise TemplateError("格式模板至少需要设置一项参数")

    template = ResumeTemplate(
        name=cleaned_name,
        kind=kind,
        description=(description or "").strip()[:255],
        html=template_html,
        config=config or {},
        source_name=(source_name or "").strip()[:255],
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    logger.info("已创建简历模板 name=%s kind=%s", template.name, template.kind)
    return template


def update_user_template(
    db: Session,
    template: ResumeTemplate,
    *,
    name: str | None = None,
    description: str | None = None,
    html: str | None = None,
    config: dict | None = None,
    enabled: bool | None = None,
) -> ResumeTemplate:
    """更新自制模板：只改传入的字段，命名/HTML/参数各自按类型校验。"""
    if name is not None and name != template.name:
        cleaned_name = validate_template_name(name)
        existing = find_by_name(db, cleaned_name)
        if existing is not None and existing.id != template.id:
            raise TemplateError(f"已存在同名模板「{cleaned_name}」")
        template.name = cleaned_name
    if description is not None:
        template.description = description.strip()[:255]
    if html is not None and template.kind == TEMPLATE_KIND_STYLE:
        template.html = sanitize_template_html(validate_template_html(html))
    if config is not None and template.kind == TEMPLATE_KIND_FORMAT:
        normalized = validated_format_config(config)
        if not normalized:
            raise TemplateError("格式模板至少需要设置一项参数")
        template.config = normalized
    if enabled is not None:
        template.enabled = enabled
    db.commit()
    db.refresh(template)
    logger.info("已更新简历模板 id=%s name=%s", template.id, template.name)
    return template


def delete_user_template(db: Session, template: ResumeTemplate) -> None:
    db.delete(template)
    db.commit()


def resolve_style_template(db: Session, name: str) -> tuple[str, str]:
    """解析样式模板名 → ``(内置模板名, 用户模板 HTML)``。

    两者只会有一个生效：内置模板返回 HTML 空串，用户模板返回内置兜底名 + HTML。
    名字既查不到内置也查不到用户模板时退回默认内置模板——记录里的模板名可能是用户
    删掉的自制模板，渲染必须仍然可用。
    """
    key = (name or "").strip()
    if key in RESUME_TEMPLATES:
        return key, ""
    user = find_by_name(db, key)
    if user is not None and user.kind == TEMPLATE_KIND_STYLE and user.enabled and user.html:
        return DEFAULT_TEMPLATE, user.html
    return DEFAULT_TEMPLATE, ""


def resolve_format_config(db: Session, name: str) -> dict:
    """解析格式模板名 → 受校验的覆盖配置（内置预设或用户模板）。"""
    key = (name or "").strip()
    if not key:
        return {}
    for preset in FORMAT_PRESETS:
        if preset["name"] == key:
            return validated_format_config(preset["config"])
    user = find_by_name(db, key)
    if user is not None and user.kind == TEMPLATE_KIND_FORMAT and user.enabled:
        return validated_format_config(user.config)
    return {}


def custom_template_options(db: Session) -> list[dict]:
    """给「可选模板」清单用的精简结构。"""
    return [
        {
            "id": item.id,
            "name": item.name,
            "label": item.name,
            "description": item.description,
            "kind": item.kind,
        }
        for item in list_user_templates(db, kind=TEMPLATE_KIND_STYLE)
        if item.enabled
    ]


def custom_format_options(db: Session) -> list[dict]:
    """列出用户自制的格式模板选项，供模板清单拼装。"""
    return [
        {
            "id": item.id,
            "name": item.name,
            "label": item.name,
            "description": item.description,
            "config": item.config or {},
        }
        for item in list_user_templates(db, kind=TEMPLATE_KIND_FORMAT)
        if item.enabled
    ]


__all__ = [
    "MAX_TEMPLATE_HTML_CHARS",
    "MAX_USER_TEMPLATES",
    "TemplateError",
    "create_user_template",
    "custom_format_options",
    "custom_template_options",
    "delete_user_template",
    "find_by_name",
    "get_user_template",
    "list_user_templates",
    "resolve_format_config",
    "resolve_style_template",
    "sanitize_template_html",
    "update_user_template",
    "validate_template_html",
    "validate_template_name",
]



