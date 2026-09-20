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
#   padding_mm         ：body 的页边距
#   line_height        ：body 的 line-height
#   section_gap        ：`.section` 的 margin-bottom 系数（× 字号）
#   name_ratio         ：`.header .name` 的字号倍数（× 字号）
#   name_extra_ratio   ：`.name-extra`（姓名旁的性别等附加信息）的字号倍数
#   intent_ratio       ：`.header .intent`（求职意向）
#   contact_ratio      ：`.header .contact`（联系方式）
#   section_title_ratio：`.section-title`
#   entry_title_ratio  ：`.entry-head .title`
#   entry_meta_ratio   ：`.entry-head .meta`（条目头右侧的机构 / 时间等）
#   entry_sub_ratio    ：`.entry .sub`（条目下的绩点 / 核心课程 / 技术栈等副行）
#   tag_font_ratio     ：`.skill-list li`（技能标签字号）
# 注意 `.entry-head .meta` 与 `.entry .sub` 是**两个**选择器、多数模板比例相同但并非总是
# 相同（technical 是 0.86 / 0.9），所以各自一个键；合成一个会让其中之一悄悄偏掉。
# `*_ratio` 一律是"相对基准字号的倍数"：直出 PDF 与预览的字号层级靠它们对齐，
# 因此 PDF 侧**不再自带第二份系数**（那份只对 classic 成立的副本正是"导出与预览
# 字号不一致"的来源）。同一套 `test_resume_layout.py` 的 CSS 守卫会逐条核对。
#
# 每个模板的**配色默认值**也放在这里（`accent` / `text` / `muted` / `line`，键名对应模板
# `:root` 里的 CSS 变量去掉 `--` 前缀），值一律是**十六进制字符串**——与上面的数值键
# 类型不同，所以这个注册表的值类型是 `float | str`。直出 PDF 的强调色从这里读
# （`pdf_exporter` 曾自带一份 `_TEMPLATE_COLORS`，与 `--accent` 是同一件事的两份定义，
# 模板一改颜色 PDF 就悄悄漂移）。`line` 现在也被 PDF 读（区块标题的下划线用它画），
# `text`/`muted` 仍主要给 HTML 用，但一并收录让"模板颜色"在此一处定义。
#
# 除"字号层级"外，**垂直间距**与**区块标题的形状**也从这里读。它们曾只存在于模板 CSS、
# 而 PDF 侧完全没有，于是 PDF 排得比预览紧——用户看到的"被压扁"主要就是这些间距缺席造成的
# （条目之间 `.entry`、副行 `.sub`、列表项 `li`、页头之后 `.header`）。键与 CSS 的对应：
#   header_gap          ：`.header` 的 margin-bottom（页头与第一段之间的留白）
#   entry_gap           ：`.entry` 的 margin-bottom（同一分区内条目之间的留白）
#   sub_gap_top         ：`.entry .sub` 的 margin-top
#   sub_gap_bottom      ：`.entry .sub` 的 margin-bottom
#   li_gap              ：`li` 的 margin-bottom（列表项之间）
#   section_title_gap   ：`.section-title` 的 margin-bottom（标题与正文之间的留白）
#   section_title_style ：区块标题的形状（left_bar / soft_box / underline / accent_box / plain）
#   section_title_text  ：标题文字颜色（accent / body / muted / white）
#   section_title_align ：标题对齐（left / center）
#   section_title_pad_x/y：标题的内边距（× 字号），左竖条与色块用得到
#   photo_width_ratio / photo_height_ratio：`.profile-photo` 的宽高（× 字号）
#   header_*            ：页头的装饰——底边线（`header_border_width` 固定 px / `header_border_color`）、
#                         文字与底边线之间的 `header_pad_bottom`（× 字号），以及 modern 那种
#                         **浅底色块**（`header_bg` = soft_accent、`header_pad_x/y`、`header_radius`，均 × 字号）。
#                         此前 PDF 只画了 `header_gap`（下边距），classic 页头下那条 2px 蓝线整条缺失。
# 这些数字同样由 `test_resume_layout.py` 拿模板 CSS 逐条核对，抄错会让 PDF 与预览再次分叉。
TEMPLATE_LAYOUT_DEFAULTS: dict[str, dict[str, float | str]] = {
    "classic": {
        "padding_mm": 14.0,
        "line_height": 1.7,
        "section_gap": 1.3,
        "name_ratio": 1.86,
        "name_extra_ratio": 1.0,
        "intent_ratio": 1.07,
        "contact_ratio": 0.93,
        "section_title_ratio": 1.14,
        "entry_title_ratio": 1.07,
        "entry_meta_ratio": 0.93,
        "entry_sub_ratio": 0.93,
        "tag_font_ratio": 0.93,
        "header_gap": 1.4,
        "entry_gap": 0.86,
        "sub_gap_top": 0.14,
        "sub_gap_bottom": 0.28,
        "li_gap": 0.21,
        "header_border_width": 2.0,
        "header_border_color": "accent",
        "header_pad_bottom": 1.1,
        "header_bg": "none",
        "header_pad_x": 0.0,
        "header_pad_y": 0.0,
        "header_radius": 0.0,
        "section_title_style": "left_bar",
        "section_title_text": "accent",
        "section_title_align": "left",
        "section_title_gap": 0.71,
        "section_title_pad_x": 0.71,
        "section_title_pad_y": 0.0,
        "photo_width_ratio": 6.3,
        "photo_height_ratio": 8.0,
        "accent": "#16365c",
        "text": "#1f2937",
        "muted": "#6b7280",
        "line": "#d9dee7",
    },
    "modern": {
        "padding_mm": 14.0,
        "line_height": 1.72,
        "section_gap": 1.2,
        "name_ratio": 2.0,
        "name_extra_ratio": 1.0,
        "intent_ratio": 1.07,
        "contact_ratio": 0.93,
        "section_title_ratio": 1.14,
        "entry_title_ratio": 1.07,
        "entry_meta_ratio": 0.93,
        "entry_sub_ratio": 0.93,
        "tag_font_ratio": 0.93,
        "header_gap": 1.5,
        "entry_gap": 0.9,
        "sub_gap_top": 0.14,
        "sub_gap_bottom": 0.28,
        "li_gap": 0.25,
        "header_border_width": 0.0,
        "header_border_color": "none",
        "header_pad_bottom": 0.0,
        "header_bg": "soft_accent",
        "header_pad_x": 1.3,
        "header_pad_y": 1.2,
        "header_radius": 0.6,
        "section_title_style": "soft_box",
        "section_title_text": "accent",
        "section_title_align": "left",
        "section_title_gap": 0.8,
        "section_title_pad_x": 0.8,
        "section_title_pad_y": 0.28,
        "photo_width_ratio": 6.6,
        "photo_height_ratio": 6.6,
        "accent": "#0f766e",
        "text": "#24303f",
        "muted": "#667085",
        "line": "#d7e0e6",
    },
    "compact": {
        "padding_mm": 12.0,
        "line_height": 1.55,
        "section_gap": 0.85,
        "name_ratio": 1.6,
        "name_extra_ratio": 0.93,
        "intent_ratio": 1.0,
        "contact_ratio": 0.9,
        "section_title_ratio": 1.05,
        "entry_title_ratio": 1.0,
        "entry_meta_ratio": 0.9,
        "entry_sub_ratio": 0.9,
        "tag_font_ratio": 0.9,
        "header_gap": 0.9,
        "entry_gap": 0.5,
        "sub_gap_top": 0.1,
        "sub_gap_bottom": 0.2,
        "li_gap": 0.12,
        "header_border_width": 1.0,
        "header_border_color": "accent",
        "header_pad_bottom": 0.7,
        "header_bg": "none",
        "header_pad_x": 0.0,
        "header_pad_y": 0.0,
        "header_radius": 0.0,
        "section_title_style": "underline",
        "section_title_text": "body",
        "section_title_align": "left",
        "section_title_gap": 0.5,
        "section_title_pad_x": 0.0,
        "section_title_pad_y": 0.14,
        "photo_width_ratio": 5.4,
        "photo_height_ratio": 7.0,
        "accent": "#30363f",
        "text": "#1f2430",
        "muted": "#6b7280",
        "line": "#dcdfe6",
    },
    "elegant": {
        "padding_mm": 16.0,
        "line_height": 1.76,
        "section_gap": 1.35,
        "name_ratio": 1.9,
        "name_extra_ratio": 0.93,
        "intent_ratio": 1.0,
        "contact_ratio": 0.9,
        "section_title_ratio": 1.11,
        "entry_title_ratio": 1.05,
        "entry_meta_ratio": 0.9,
        "entry_sub_ratio": 0.9,
        "tag_font_ratio": 0.93,
        "header_gap": 1.5,
        "entry_gap": 0.9,
        "sub_gap_top": 0.14,
        "sub_gap_bottom": 0.28,
        "li_gap": 0.2,
        "header_border_width": 1.0,
        "header_border_color": "accent",
        "header_pad_bottom": 0.9,
        "header_bg": "none",
        "header_pad_x": 0.0,
        "header_pad_y": 0.0,
        "header_radius": 0.0,
        "section_title_style": "underline",
        "section_title_text": "accent",
        "section_title_align": "center",
        "section_title_gap": 0.8,
        "section_title_pad_x": 0.0,
        "section_title_pad_y": 0.28,
        "photo_width_ratio": 5.6,
        "photo_height_ratio": 7.2,
        "accent": "#1f3b4d",
        "text": "#22252b",
        "muted": "#7a7f88",
        "line": "#e0ddd6",
    },
    "technical": {
        "padding_mm": 12.0,
        "line_height": 1.6,
        "section_gap": 1.0,
        "name_ratio": 1.8,
        "name_extra_ratio": 0.95,
        "intent_ratio": 1.04,
        "contact_ratio": 0.86,
        "section_title_ratio": 1.04,
        "entry_title_ratio": 1.04,
        "entry_meta_ratio": 0.86,
        "entry_sub_ratio": 0.9,
        "tag_font_ratio": 0.86,
        "header_gap": 1.1,
        "entry_gap": 0.64,
        "sub_gap_top": 0.1,
        "sub_gap_bottom": 0.2,
        "li_gap": 0.14,
        "header_border_width": 3.0,
        "header_border_color": "accent",
        "header_pad_bottom": 0.8,
        "header_bg": "none",
        "header_pad_x": 0.0,
        "header_pad_y": 0.0,
        "header_radius": 0.0,
        "section_title_style": "accent_box",
        "section_title_text": "white",
        "section_title_align": "left",
        "section_title_gap": 0.57,
        "section_title_pad_x": 0.71,
        "section_title_pad_y": 0.1,
        "photo_width_ratio": 5.8,
        "photo_height_ratio": 7.4,
        "accent": "#0b5fa5",
        "text": "#1c2430",
        "muted": "#5d6b7a",
        "line": "#ccd6e0",
    },
    "minimal": {
        "padding_mm": 18.0,
        "line_height": 1.8,
        "section_gap": 1.45,
        "name_ratio": 1.75,
        "name_extra_ratio": 0.93,
        "intent_ratio": 1.0,
        "contact_ratio": 0.9,
        "section_title_ratio": 1.0,
        "entry_title_ratio": 1.04,
        "entry_meta_ratio": 0.9,
        "entry_sub_ratio": 0.9,
        "tag_font_ratio": 0.93,
        "header_gap": 1.7,
        "entry_gap": 0.93,
        "sub_gap_top": 0.14,
        "sub_gap_bottom": 0.28,
        "li_gap": 0.21,
        "header_border_width": 0.0,
        "header_border_color": "none",
        "header_pad_bottom": 0.0,
        "header_bg": "none",
        "header_pad_x": 0.0,
        "header_pad_y": 0.0,
        "header_radius": 0.0,
        "section_title_style": "plain",
        "section_title_text": "muted",
        "section_title_align": "left",
        "section_title_gap": 0.71,
        "section_title_pad_x": 0.0,
        "section_title_pad_y": 0.0,
        "photo_width_ratio": 5.4,
        "photo_height_ratio": 7.0,
        "accent": "#17181a",
        "text": "#17181a",
        "muted": "#767a80",
        "line": "#e6e6e6",
    },
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


def template_layout_defaults(name: str) -> dict[str, float | str]:
    """某个样式模板的版式与配色默认值；未知模板退回经典模板的那一组。"""
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


# ===== 模板市场（R-19）=====
# 四套场景预设：**映射既有样式模板 + 既有格式预设 + 建议字号**，不新建任何 .html.j2
# 文件、不引在线资源，全离线。``template`` 是 ``RESUME_TEMPLATES`` 里的键，
# ``format_name`` 是 ``FORMAT_PRESETS`` 里的键，``font_scale`` 是 ``FONT_SCALES`` 里的键，
# ``page_limit`` 为建议篇幅——「使用此模板」预览时原样交给渲染管线即可。
TEMPLATE_MARKET_PRESETS: tuple[dict, ...] = (
    {
        "name": "internet",
        "label": "互联网",
        "category": "互联网",
        "description": "青绿强调色 + 紧凑版式，突出项目与技能，适合研发 / 产品 / 运营投递",
        "template": "modern",
        "format_name": "compact",
        "format_config": {},
        "font_scale": "standard",
        "page_limit": 1,
    },
    {
        "name": "soe",
        "label": "国企",
        "category": "国企",
        "description": "深蓝稳重配色、正文舒展，突出教育背景与荣誉，适合体制内与国企投递",
        "template": "classic",
        "format_name": "spacious",
        "format_config": {},
        "font_scale": "standard",
        "page_limit": 1,
    },
    {
        "name": "foreign",
        "label": "外企",
        "category": "外企",
        "description": "优雅留白 + 单色强调，适合文商科与英文岗位，突出经历与奖项",
        "template": "elegant",
        "format_name": "spacious",
        "format_config": {},
        "font_scale": "standard",
        "page_limit": 1,
    },
    {
        "name": "campus",
        "label": "应届生",
        "category": "应届生",
        "description": "精简紧凑、小字号，一页放下教育、校园经历与实习，适合校招海投",
        "template": "compact",
        "format_name": "compact",
        "format_config": {},
        "font_scale": "small",
        "page_limit": 1,
    },
)


def market_options() -> list[dict]:
    """模板市场预设清单（返回副本，避免调用方改到全局常量）。"""
    return [dict(item) for item in TEMPLATE_MARKET_PRESETS]


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
    # `base_px` 也一并下发：无级字号滑块要把绝对像素映射回"最近档位 + 系数"，
    # 就必须知道每档的基准字号。让前端自己抄一份 12/14/15.5 会与这里漂移
    # （改 FONT_SCALES 时没人记得去改前端），所以由后端作为唯一来源。
    return [
        {
            "name": item["name"],
            "label": item["label"],
            "description": item["description"],
            "base_px": item["base_px"],
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
    "TEMPLATE_MARKET_PRESETS",
    "font_scale_options",
    "market_options",
    "font_scale_spec",
    "format_css",
    "format_field_options",
    "template_options",
    "template_options_with_custom",
    "template_spec",
    "validated_format_config",
]
