"""简历版式注册表：模板与字号档位。

模板是纯 Jinja 文件，共享 `_resume_sections.j2` 正文片段，只有样式不同；字号档位
通过一个基准像素值控制，所有尺寸都用 `calc(var(--fs) * N)` 相对它计算，因此加档位
只需改一个数字，不必逐处调整 CSS。
"""

DEFAULT_TEMPLATE = "classic"
DEFAULT_FONT_SCALE = "standard"
# 默认篇幅：一页 A4。生成弹窗每次打开都按它重置，所以它得跟着模板目录一起下发——
# 前端自己写死 1 的话，后端改默认值就成了两处不一致。
DEFAULT_PAGE_LIMIT = 1

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
}

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
    "RESUME_TEMPLATES",
    "font_scale_options",
    "font_scale_spec",
    "template_options",
    "template_spec",
]
