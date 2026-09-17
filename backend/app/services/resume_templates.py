"""简历版式注册表：模板与字号档位。

模板是纯 Jinja 文件，共享 `_resume_sections.j2` 正文片段，只有样式不同；字号档位
通过一个基准像素值控制，所有尺寸都用 `calc(var(--fs) * N)` 相对它计算，因此加档位
只需改一个数字，不必逐处调整 CSS。

另外这里也定义**格式模板**：一组受校验的 CSS 覆盖（强调色、行高、页边距、区块间距等），
叠加在任意样式模板之上。这样"换版式"与"换皮肤"是两件独立的事，用户也能只调其中一个。
"""

import re
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

DEFAULT_TEMPLATE = "classic"
DEFAULT_FONT_SCALE = "standard"
# 默认篇幅：一页 A4。生成弹窗每次打开都按它重置，所以它得跟着模板目录一起下发——
# 前端自己写死 1 的话，后端改默认值就成了两处不一致。
DEFAULT_PAGE_LIMIT = 1

# 每个样式模板在 CSS 里的版式默认值。**这些数字必须与模板文件一致**——
# 自动一页要靠它们判断"当前值是多少、还能往紧收多少"，抄错会让它收紧一个
# 用户根本没设置过的值（或反过来该收没收）。`test_resume_templates.py` 会
# 逐个模板读文件核对，所以这里改了模板不更新会直接测试失败。
#   padding_mm    ：body 的页边距
#   line_height   ：body 的 line-height
#   section_gap   ：`.section` 的 margin-bottom 系数（× 字号）
TEMPLATE_LAYOUT_DEFAULTS: dict[str, dict[str, float]] = {
    "classic": {"padding_mm": 14.0, "line_height": 1.7, "section_gap": 1.3},
    "modern": {"padding_mm": 14.0, "line_height": 1.72, "section_gap": 1.2},
    "compact": {"padding_mm": 12.0, "line_height": 1.55, "section_gap": 0.85},
    "elegant": {"padding_mm": 16.0, "line_height": 1.76, "section_gap": 1.35},
    "technical": {"padding_mm": 12.0, "line_height": 1.6, "section_gap": 1.0},
    "minimal": {"padding_mm": 18.0, "line_height": 1.8, "section_gap": 1.45},
}

# 模板文件里版式默认值所在的样式模板名（`classic` 对应 `resume.html.j2`）。
RESUME_TEMPLATES: dict[str, dict] = {
    "classic": {
        "name": "classic",
        "label": "经典",
        "file": "resume.html.j2",
        "description": "深蓝标题与左侧色条，稳重的通用款式",
    },
    "modern": {
        "name": "modern",
        "label": "现代",
        "file": "resume_modern.html.j2",
        "description": "青绿配色与圆角标签，适合互联网岗位",
    },
    "compact": {
        "name": "compact",
        "label": "精简",
        "file": "resume_compact.html.j2",
        "description": "细线分隔、排版紧凑，适合内容多、想压在一页",
    },
    "elegant": {
        "name": "elegant",
        "label": "优雅",
        "file": "resume_elegant.html.j2",
        "description": "居中标题与衬线字，留白舒展，适合文商科与管理岗位",
    },
    "technical": {
        "name": "technical",
        "label": "技术",
        "file": "resume_technical.html.j2",
        "description": "色块标题与等宽辅助信息，信息密度高，适合研发岗位",
    },
    "minimal": {
        "name": "minimal",
        "label": "极简",
        "file": "resume_minimal.html.j2",
        "description": "只用黑灰与字号层级，没有任何色块与装饰",
    },
}


def template_layout_defaults(name: str) -> dict[str, float]:
    """某个样式模板的版式默认值；未知模板退回经典模板的那一组。"""
    return TEMPLATE_LAYOUT_DEFAULTS.get(
        (name or "").strip(), TEMPLATE_LAYOUT_DEFAULTS[DEFAULT_TEMPLATE]
    )

# 格式模板：一组 CSS 变量与版式覆盖，叠加在任意样式模板之上。
#
# 实现方式是在 `</head>` 前追加一段受校验的 `<style>`：CSS 后写的同优先级规则生效，
# 所以不必为每个模板都留占位变量——加新样式模板时也不必再改这里的代码。
FORMAT_FIELDS: tuple[dict, ...] = (
    {"key": "accent", "label": "强调色", "type": "color", "css": "--accent"},
    {"key": "text_color", "label": "正文颜色", "type": "color", "css": "--text"},
    {"key": "muted_color", "label": "辅助文字颜色", "type": "color", "css": "--muted"},
    {"key": "line_color", "label": "分隔线颜色", "type": "color", "css": "--line"},
    {
        "key": "font_scale_adjust",
        "label": "字号系数",
        "type": "number",
        "min": 0.88,
        "max": 1.16,
        "step": 0.02,
        # 这一项**刻意没有 css 映射**：它在渲染时就把档位基准字号乘好再交给模板
        # （见 `services/exporter.py` 的 `base_px`），是唯一对内置模板与用户自制模板
        # 都生效的路径。如果这里再给一条 `--fs-adjust` 的 CSS 覆盖，两者会叠乘——
        # 界面上调 1.1 会实得 1.21 倍，而这种偏差只有拿尺子量才看得出来。
        "description": "在所选字号档位上再乘一个系数",
    },
    {
        "key": "line_height",
        "label": "行高",
        "type": "number",
        "min": 1.2,
        "max": 2.2,
        "step": 0.05,
        "css_rule": "body { line-height: %s !important; }",
    },
    {
        "key": "page_padding",
        "label": "页边距（mm）",
        "type": "number",
        "min": 8,
        "max": 26,
        "step": 1,
        # body 的 padding 在模板里是字面量（各模板默认不同），所以整条覆盖。
        "css_rule": "body { padding: %smm !important; }",
    },
    {
        "key": "section_gap",
        "label": "区块间距",
        "type": "number",
        "min": 0.6,
        "max": 2.2,
        "step": 0.1,
        "css_rule": ".section { margin-bottom: calc(var(--fs) * %s) !important; }",
    },
)

FORMAT_FIELD_KEYS = tuple(field["key"] for field in FORMAT_FIELDS)
_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _format_field(key: str) -> dict | None:
    for field in FORMAT_FIELDS:
        if field["key"] == key:
            return field
    return None


def validated_format_config(raw: dict | None) -> dict:
    """校验并归一化格式模板取值。

    只接受清单里的键，颜色必须是十六进制、数值必须落在范围内——这段内容会被拼进
    HTML 的 `<style>`，不校验就等于把 CSS 注入的口子交给前端。
    """
    if not isinstance(raw, dict):
        return {}
    result: dict = {}
    for key, value in raw.items():
        field = _format_field(str(key))
        if field is None or value in (None, ""):
            continue
        if field["type"] == "color":
            text = str(value).strip()
            if _HEX_COLOR_RE.match(text):
                result[field["key"]] = text.lower()
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        low = float(field.get("min", 0))
        high = float(field.get("max", 1))
        if not (low <= number <= high):
            continue
        result[field["key"]] = round(number, 3)
    return result


def format_css(config: dict | None) -> str:
    """把格式模板翻译成一段 CSS（空配置返回空串）。"""
    values = validated_format_config(config)
    if not values:
        return ""
    root_parts: list[str] = []
    extra_rules: list[str] = []
    for key, value in values.items():
        field = _format_field(key)
        if field is None:
            continue
        if field.get("css"):
            root_parts.append(f"{field['css']}: {value};")
        rule = field.get("css_rule")
        if rule:
            # 数值统一去掉多余的小数位（3.0 → 3），生成的 CSS 更干净。
            text = f"{value:g}"
            extra_rules.append(rule % text)
    blocks: list[str] = []
    if root_parts:
        blocks.append(":root { " + " ".join(root_parts) + " }")
    blocks.extend(extra_rules)
    return "\n".join(blocks)


def format_field_options() -> list[dict]:
    return [
        {
            "key": field["key"],
            "label": field["label"],
            "type": field["type"],
            **(
                {"min": field["min"], "max": field["max"], "step": field.get("step", 0.1)}
                if field["type"] == "number"
                else {}
            ),
            "description": field.get("description", ""),
        }
        for field in FORMAT_FIELDS
    ]


# 几个开箱可用的格式模板，让用户不必从零调参。
FORMAT_PRESETS: tuple[dict, ...] = (
    {
        "name": "standard",
        "label": "标准",
        "description": "不改动样式模板自身的版式",
        "config": {},
    },
    {
        "name": "compact",
        "label": "紧凑",
        "description": "行高与间距收紧、页边距变小，适合想压进一页",
        "config": {"line_height": 1.45, "page_padding": 11, "section_gap": 0.85},
    },
    {
        "name": "spacious",
        "label": "舒展",
        "description": "行高与留白放大，适合内容不多、想显得从容",
        "config": {"line_height": 2.0, "page_padding": 20, "section_gap": 1.8},
    },
    {
        "name": "mono_accent",
        "label": "单色强调",
        "description": "低调的深灰强调色，适合正式、保守的投递场景",
        "config": {"accent": "#374151", "line_color": "#d1d5db"},
    },
)

FONT_SCALES: dict[str, dict] = {
    "small": {
        "name": "small",
        "label": "小字号",
        "base_px": 12.0,
        "description": "字更小、信息密度更高，适合内容偏多",
    },
    "standard": {
        "name": "standard",
        "label": "标准字号",
        "base_px": 14.0,
        "description": "默认档位，兼顾可读性与篇幅",
    },
    "large": {
        "name": "large",
        "label": "大字号",
        "base_px": 15.5,
        "description": "字更大更醒目，适合内容较少",
    },
}


def template_spec(name: str) -> dict:
    return RESUME_TEMPLATES.get((name or "").strip()) or RESUME_TEMPLATES[DEFAULT_TEMPLATE]


def font_scale_spec(name: str) -> dict:
    return FONT_SCALES.get((name or "").strip()) or FONT_SCALES[DEFAULT_FONT_SCALE]


def template_options() -> list[dict]:
    return [
        {
            "name": item["name"],
            "label": item["label"],
            "description": item["description"],
        }
        for item in RESUME_TEMPLATES.values()
    ]


def template_options_with_custom(custom: list[dict]) -> list[dict]:
    """内置模板 + 用户自制模板（自制排在后面，用 ``custom`` 标记区分）。"""
    options = [
        {**item, "custom": False, "id": None} for item in template_options()
    ]
    for item in custom:
        options.append(
            {
                "name": item["name"],
                "id": item.get("id"),
                "label": item.get("label") or item["name"],
                "description": item.get("description", ""),
                "custom": True,
            }
        )
    return options


def font_scale_options() -> list[dict]:
    return [
        {
            "name": item["name"],
            "label": item["label"],
            "description": item["description"],
        }
        for item in FONT_SCALES.values()
    ]


__all__ = [
    "DEFAULT_FONT_SCALE",
    "DEFAULT_PAGE_LIMIT",
    "DEFAULT_TEMPLATE",
    "FONT_SCALES",
    "FORMAT_FIELDS",
    "FORMAT_FIELD_KEYS",
    "FORMAT_PRESETS",
    "RESUME_TEMPLATES",
    "font_scale_options",
    "font_scale_spec",
    "format_css",
    "format_field_options",
    "template_options",
    "template_options_with_custom",
    "template_spec",
    "validated_format_config",
]
