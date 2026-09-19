"""服务端直接生成 PDF（fpdf2 + 系统中文字体）。

为什么自己排版而不是复用 HTML：浏览器打印要用户再点一次「另存为 PDF」，且分页
由浏览器决定；服务端生成可以直接下载，版式稳定。代价是需要一个中文字体——从
系统字体目录里找（Windows 微软雅黑/黑体、macOS PingFang、Linux Noto CJK），
找不到时抛出明确错误，让用户改用浏览器打印，而不是产出一份乱码 PDF。

**版式口径与预览对齐**（这是本条最重要的约束）：PDF 与 HTML 预览是两套独立的排版
引擎，只要两边的行距/页边距/区块间距各写各的，就会出现"预览一个样、下载的 PDF 另一个
样"。所以这里**不再内置一套硬编码系数**，而是：

  * 行距、页边距、区块间距、**各层级字号比例**、以及**强调色**都从
    `resume_templates.template_layout_defaults` 读——那是模板参数**唯一的结构化来源**
    （`test_resume_layout.py` 会拿模板 CSS 逐条核对），抄一份到 PDF 里就会在模板改动后
    悄悄漂移。PDF 曾经自带一份只对 classic 成立的字号副本，于是 technical 等模板的
    姓名 / 区块标题比预览大 7%~10%；也曾经自带一份 `_TEMPLATE_COLORS` 强调色表，与
    模板的 `--accent` 是同一件事的两份定义；
  * 用户在「格式模板」里设过的 `line_height` / `page_padding` / `section_gap` / `accent`
    覆盖它们；
  * 一页适配复用预览那套 `--fit-scale` 的口径：**只缩字号派生的尺寸，mm 页边距不动**，
    有下限（`MIN_FIT_SCALE`）、迭代式、装不下就如实标记 overflow。是否"装得下"以
    **真实渲染出来的页数**为准（见 `decide_fit_scale`），而不是连续内容高度——后者
    会低估分页后的实际高度（`ensure_space` 为不切断条目会提前换页、留下一段空隙）。

**测量与决策分开**：`measure_content_height` / `rendered_page_count` 只回答"某个缩放下
内容多高 / 排几页"，`decide_fit_scale` 只回答"该缩到多少 / 是否溢出"。后续要做
"并排展示多页而不是截断"时，只需替换决策这一步，测量与绘制都不必动。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, replace
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from ..schemas.resume import MAX_RESUME_PAGES, ResumeContent

logger = logging.getLogger(__name__)

FONT_FAMILY = "resume-cjk"
# 允许用户用环境变量指定字体（Linux 发行版字体路径五花八门时的兜底）。
FONT_ENV_VAR = "RESUMEFORGE_PDF_FONT"

# (常规, 粗体)；粗体缺失时退回常规。
_FONT_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc"),
    ("C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simhei.ttf"),
    ("C:/Windows/Fonts/simsun.ttc", "C:/Windows/Fonts/simsun.ttc"),
    ("C:/Windows/Fonts/Deng.ttf", "C:/Windows/Fonts/Dengb.ttf"),
    ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/PingFang.ttc"),
    ("/System/Library/Fonts/Supplemental/Songti.ttc", "/System/Library/Fonts/Supplemental/Songti.ttc"),
    ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"),
    (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ),
    (
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    ),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    ("/usr/share/fonts/truetype/arphic/uming.ttc", "/usr/share/fonts/truetype/arphic/uming.ttc"),
)

def _hex_to_rgb(value: str) -> tuple[int, int, int] | None:
    """把格式模板里的十六进制颜色转成 RGB；不合法时返回 None。"""
    text = (value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    if len(text) != 6:
        return None
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return None


def resolve_accent(template: str, format_config: dict | None) -> tuple[int, int, int]:
    """导出用的强调色：格式模板覆盖优先，其次模板默认，最后兜底深蓝。

    强调色唯一来源是 `resume_templates.template_layout_defaults`（共享知识第 10 条）；
    PDF 与 Word 都从这里取同一份颜色，禁止任何渲染器再存一份 `_TEMPLATE_COLORS`。
    """
    from .resume_templates import template_layout_defaults, template_spec, validated_format_config

    spec = template_spec(template)
    overrides = validated_format_config(format_config)
    return (
        _hex_to_rgb(str(overrides.get("accent") or ""))
        or _hex_to_rgb(str(template_layout_defaults(spec["name"])["accent"]))
        or (22, 54, 92)
    )

# 1 px = 0.75 pt = 0.2646 mm。行推进量统一按 `字号(px) × _PX_TO_MM × 行高系数` 计算。
_PX_TO_PT = 0.75
_PX_TO_MM = 0.264_583

PHOTO_WIDTH = 22.0
PHOTO_HEIGHT = 28.0

# A4 短边宽（mm）。页面所有横向定位都以它为基准，避免在代码里到处写 210。
PAGE_WIDTH_MM = 210.0
PAGE_HEIGHT_MM = 297.0

# ===== 一页适配（与 `_resume_fit_script.j2` 同口径）=====
# 预览的 `--fit-scale` 有没有可缩的余地、缩到多小为止，尽量沿用那套规则，避免又造出
# 第二套分页/溢出判定。两边是两套引擎（这里是 Python、脚本里是 JS），**无法共享同一份常量**，
# 只能靠 `test_pdf_exporter.py` 的 `test_fit_scale_constants_match_the_preview_script`
# 把两边的字面量拿出来逐个数值比对来钉住同步。**改动下面任何一个数值，都必须同步改
# `backend/app/templates/_resume_fit_script.j2` 里对应的 JS 字面量**，否则那条测试会红。
MIN_FIT_SCALE = 0.5  # = 脚本 `minScale`；再小就"缩到看不清"了
_FIT_MAX_PASSES = 3  # = 脚本 `maxPasses`
_FIT_RATIO_MARGIN = 0.995  # = 脚本里 `Math.min(...) * 0.995`；给"绝对尺寸不参与缩放"留的余量
_FIT_MIN_STEP = 0.001  # = 脚本里 `scale - 0.001`；一档缩不下去就停
# 高度比较的容差（mm）：= 脚本里 `referenceHeight + 1` 的 1px（1px = _PX_TO_MM mm）。
# 它只用来判断"比例跳档有没有意义"，真正的"装不装得下"由真实页数决定。
_FIT_TOLERANCE_MM = _PX_TO_MM
# 连续高判断"刚好装得下"、真实分页却超出一页时的**离散收档**步长。这是本模块相对预览脚本
# 多出来的一档：预览只用 `scrollHeight / referenceHeight` 的比例跳档，当这个比例 ≥ 1
# （连续高已"达标"）时它跳不动，于是会在**连续高 ≠ 实际分页高**的边界上不动（见
# `decide_fit_scale` 的说明）。每轮至少收这么多，才能把这类内容真正压回一页。
_FIT_PAGE_STEP = 0.02

# ===== 字号层级系数 =====
# 姓名 / 求职意向 / 联系方式 / 区块标题 / 条目标题 / 条目头副行(`.entry-head .meta`) /
# 条目下副行(`.entry .sub`) / 技能标签 的字号比例 **不再定义在本模块**：它们已纳入
# `resume_templates.TEMPLATE_LAYOUT_DEFAULTS`（模板参数唯一的结构化来源），由 `ResumeLayout`
# 带进来。此前这里存的是一份**只对 classic 成立**的副本，导致 technical 等模板的层级比例
# 与预览差 7%~10%（见 `resolve_layout`）。条目头副行与条目下副行**分成两个键**：多数模板
# 比例相同，technical 却是 0.86 / 0.9，合并一个会让其中之一悄悄偏掉。


class ResumePDFError(Exception):
    """对外暴露的 PDF 生成错误，message 可直接展示给用户。"""


def _resolve_font_paths() -> tuple[str, str] | None:
    override = os.environ.get(FONT_ENV_VAR, "").strip()
    if override:
        path = Path(override)
        if path.is_file():
            return str(path), str(path)
        logger.warning("环境变量 %s 指向的字体不存在：%s", FONT_ENV_VAR, override)
    for regular, bold in _FONT_CANDIDATES:
        if Path(regular).is_file():
            return regular, bold if Path(bold).is_file() else regular
    return None


def font_available() -> bool:
    """前端据此决定是否展示「下载 PDF」主按钮。"""
    return _resolve_font_paths() is not None


# ===== 版式 =====


@dataclass(frozen=True)
class ResumeLayout:
    """一份简历当前生效的版式（PDF 唯一的版式来源）。

    数值来自"模板默认值 + 用户已设的覆盖"，两者合成之后 PDF 与预览读的是同一组数：
    页边距（mm）、行高系数、区块间距系数，以及各层级（姓名 / 求职意向 / 联系方式 /
    区块标题 / 条目标题 / 条目头副行 / 条目下副行 / 技能标签）的字号比例。``fit_scale`` 是一页
    适配算出的缩放，**只**乘在字号派生的尺寸上（`scaled_base_px`），mm 页边距不参与——与预览把
    `--fit-scale` 吸进 `--fs` 的做法完全一致。
    """

    base_px: float
    margin_mm: float
    line_height: float
    section_gap: float
    name_ratio: float
    intent_ratio: float
    contact_ratio: float
    section_title_ratio: float
    entry_title_ratio: float
    entry_meta_ratio: float
    entry_sub_ratio: float
    tag_font_ratio: float
    fit_scale: float = 1.0

    @property
    def scaled_base_px(self) -> float:
        """一页适配之后的基准字号（px）。所有尺寸都由它派生。"""
        return self.base_px * self.fit_scale

    @property
    def margin_x(self) -> float:
        return self.margin_mm

    @property
    def margin_top(self) -> float:
        # 预览的 `body { padding: Pmm }` 是四边等距，所以这里上下也跟着页边距走，
        # 不再用一组自造的 12/13mm。
        return self.margin_mm

    @property
    def margin_bottom(self) -> float:
        return self.margin_mm

    @property
    def usable_height_per_page(self) -> float:
        """一页里正文可用高度（mm）= 页高 − 上下页边距。"""
        return PAGE_HEIGHT_MM - 2 * self.margin_mm

    def with_fit_scale(self, scale: float) -> ResumeLayout:
        return replace(self, fit_scale=scale)


def resolve_layout(
    *,
    template: str,
    base_px: float,
    format_config: dict | None,
    margin_mm: float | None = None,
) -> ResumeLayout:
    """合成"模板默认值 + 用户覆盖"，得到 PDF 的版式。

    **为什么不在这里再写一份默认系数**：模板真实的行高/页边距/区块间距**与各层级字号比例**
    定义在 `app/templates/resume*.html.j2` 的 CSS 里，`resume_templates.TEMPLATE_LAYOUT_DEFAULTS`
    是它们的结构化映射（`test_resume_layout.py` 拿 CSS 逐条核对）。从注册表读，模板一改
    PDF 自动跟上；抄一份到本模块，就是"今天对了、明天模板一改又漂移"——这正是"直出 PDF
    与预览不一致"这个 bug 的来源。

    ``margin_mm`` 是导出时的**页边距直接覆盖**（R-16 全参数导出）：给定时优先于
    ``format_config.page_padding`` 与模板默认值，让 PDF / Word 共用同一边距口径。
    """
    from .resume_templates import template_layout_defaults, validated_format_config

    defaults = template_layout_defaults(template)
    overrides = validated_format_config(format_config)

    def pick(key: str, default_key: str) -> float:
        value = overrides.get(key)
        # 只有用户**确实设过**才覆盖默认；没设过时保持模板自带的值，
        # 否则存量简历的 PDF 会因为"凭空多了一个默认值"而无端跳变。
        return float(value) if value is not None else float(defaults[default_key])

    resolved_margin = float(margin_mm) if margin_mm is not None else pick("page_padding", "padding_mm")

    return ResumeLayout(
        base_px=base_px,
        margin_mm=resolved_margin,
        line_height=pick("line_height", "line_height"),
        section_gap=pick("section_gap", "section_gap"),
        # 字号层级比例只来自模板（格式模板没有对应的用户覆盖项）。
        name_ratio=float(defaults["name_ratio"]),
        intent_ratio=float(defaults["intent_ratio"]),
        contact_ratio=float(defaults["contact_ratio"]),
        section_title_ratio=float(defaults["section_title_ratio"]),
        entry_title_ratio=float(defaults["entry_title_ratio"]),
        # `.entry-head .meta`（条目头右侧）与 `.entry .sub`（条目下副行）是**两个**选择器，
        # 比例多数模板相同、technical 却是 0.86 / 0.9，所以各取各的，不合并。
        entry_meta_ratio=float(defaults["entry_meta_ratio"]),
        entry_sub_ratio=float(defaults["entry_sub_ratio"]),
        tag_font_ratio=float(defaults["tag_font_ratio"]),
    )


# 技能标签的**形状**比例（左右内边距 0.71×标签字号、标签间距 0.57×标签字号、圆角 0.4×）。
# 标签**字号**比例已随其它层级一起纳入 `resume_templates.TEMPLATE_LAYOUT_DEFAULTS`
# （`tag_font_ratio`，由 `ResumeLayout` 带进来），这里的三个是 PDF 统一采用的一种标签形状
# ——各模板的标签形状其实不同（modern 是胶囊、technical 是左侧色条、compact/minimal 刻意
# 无框），PDF 目前统一画成"带底色的圆角框"，与预览的形状差异属于**既有**、独立的遗留，
# 不在本次"字号层级结构化"的范围内。
_TAG_PADDING_RATIO = 0.71
_TAG_GAP_RATIO = 0.57
_TAG_RADIUS_RATIO = 0.4
# 标签底色 = 强调色调淡到接近白（模板里的 `--accent-soft` 就是这个思路，例如 #0f766e → #e6f4f1）。
_TAG_TINT_RATIO = 0.88


@dataclass(frozen=True)
class SkillTagMetrics:
    """技能标签的几何尺寸（毫米 / 磅）。"""

    font_pt: float
    height: float
    padding_x: float
    gap_x: float
    gap_y: float
    radius: float


def skill_tag_metrics(
    font_size: float, *, line_height: float, tag_ratio: float
) -> SkillTagMetrics:
    """由基准字号推出标签的整套尺寸（纯函数，便于逐条验证比例）。

    ``tag_ratio`` 是模板里 `.skill-list li` 的字号倍数（来自
    `TEMPLATE_LAYOUT_DEFAULTS` 的 `tag_font_ratio`）——**必须由调用方传入**，本模块不再
    保留一份只对 classic 成立的副本。``line_height`` 是模板的行高系数：标签高度 =
    标签字号的 ``line_height`` 倍，与预览里 `.skill-list li` 继承 body 行高同理。两者都
    来自 `ResumeLayout`。
    """
    tag_px = font_size * tag_ratio
    return SkillTagMetrics(
        font_pt=tag_px * _PX_TO_PT,
        height=tag_px * _PX_TO_MM * line_height,
        padding_x=tag_px * _PX_TO_MM * _TAG_PADDING_RATIO,
        gap_x=tag_px * _PX_TO_MM * _TAG_GAP_RATIO,
        gap_y=tag_px * _PX_TO_MM * _TAG_GAP_RATIO,
        radius=tag_px * _PX_TO_MM * _TAG_RADIUS_RATIO,
    )


def soft_accent(color: tuple[int, int, int], ratio: float = _TAG_TINT_RATIO) -> tuple[int, int, int]:
    """把强调色调成标签底色。"""
    return tuple(round(channel + (255 - channel) * ratio) for channel in color)  # type: ignore[return-value]


def wrap_skill_tags(widths: list[float], *, max_width: float, gap: float) -> list[list[int]]:
    """把标签按可用宽度折行，返回**每行的下标**。

    抽成纯函数是因为折行算错**不会报错**：只会让最后一个标签悄悄跑到页面右边之外，或者把
    整行孤零零地挤到下一页——两种都很难在肉眼下发现，却能离线逐条测出来。

    单个标签本身宽于 ``max_width`` 时单独占一行（正文不可断行，只能让它略微超出），
    调用方应据此收紧标签文案，而不是在这里硬切。
    """
    rows: list[list[int]] = []
    current: list[int] = []
    used = 0.0
    for index, width in enumerate(widths):
        if not current:
            current = [index]
            used = width
            continue
        if used + gap + width <= max_width:
            current.append(index)
            used += gap + width
        else:
            rows.append(current)
            current = [index]
            used = width
    if current:
        rows.append(current)
    return rows


class _ResumePDF(FPDF):
    """PDF 画布。所有行距/页边距都从 ``self.layout`` 取，模块里没有第二份系数。"""

    def __init__(
        self,
        accent: tuple[int, int, int],
        layout: ResumeLayout,
        *,
        measuring: bool = False,
    ) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.accent = accent
        self.layout = layout
        # 测量模式：不翻页，让整份内容连续排下来，末尾的 y 就是真实内容高度。
        self.measuring = measuring
        self.set_auto_page_break(auto=not measuring, margin=layout.margin_bottom)
        self.set_margins(layout.margin_x, layout.margin_top, layout.margin_x)
        self.set_title("简历")
        self.alias_nb_pages()

    @property
    def content_width(self) -> float:
        """正文可用宽度（mm）。"""
        return PAGE_WIDTH_MM - 2 * self.layout.margin_x

    def line_advance(self, font_px: float) -> float:
        """某个字号的一行推进量（mm）= 字号 × mm/px × 行高系数。

        行高系数来自模板（`ResumeLayout.line_height`），所以 PDF 的行距与预览是**同一个
        口径**——这正是原来"PDF 比预览紧、看起来被压扁"要修的地方。
        """
        return font_px * _PX_TO_MM * self.layout.line_height

    def ensure_space(self, height: float) -> None:
        """剩余空间不足时换页，避免条目被从中间截断。测量模式不换页。"""
        if self.measuring:
            return
        if self.get_y() + height > self.page_break_trigger:
            self.add_page()

    def section_title(self, text: str, base: float) -> None:
        size = base * self.layout.section_title_ratio
        title_height = self.line_advance(size)
        # 区块之间的留白 = 模板的 section_gap × 基准字号，与预览
        # `.section { margin-bottom: calc(var(--fs) * gap) }` 同口径。
        gap = base * _PX_TO_MM * self.layout.section_gap
        self.ensure_space(gap + title_height)
        self.ln(gap)
        self.set_font(FONT_FAMILY, "B", size * _PX_TO_PT)
        self.set_text_color(*self.accent)
        self.set_x(self.layout.margin_x)
        self.cell(0, title_height, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*self.accent)
        self.set_line_width(0.3)
        line_y = self.get_y()
        self.line(self.layout.margin_x, line_y, PAGE_WIDTH_MM - self.layout.margin_x, line_y)
        # 标题与正文之间的间隙（对应模板 `.section-title` 的下外边距），仍由字号派生，
        # 因此缩放时会跟着一起变矮。
        self.ln(base * _PX_TO_MM * 0.4)
        self.set_text_color(31, 41, 55)

    def bullets(self, items: list[str], base: float, indent: float = 3.0) -> None:
        line_height = self.line_advance(base)
        self.set_font(FONT_FAMILY, "", base * _PX_TO_PT)
        for item in items:
            text = str(item).strip()
            if not text:
                continue
            self.ensure_space(line_height * 2)
            self.set_x(self.layout.margin_x + indent)
            self.multi_cell(
                self.content_width - indent,
                line_height,
                f"· {text}",
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )

    def entry_head(self, left: str, right: str, base: float) -> None:
        title_size = base * self.layout.entry_title_ratio
        line_height = self.line_advance(title_size)
        self.ensure_space(line_height * 2)
        available = self.content_width
        left_width = available * 0.68
        right_width = available - left_width
        self.set_font(FONT_FAMILY, "B", title_size * _PX_TO_PT)
        self.set_x(self.layout.margin_x)
        self.cell(left_width, line_height, left, new_x=XPos.RIGHT, new_y=YPos.TOP)
        if right:
            self.set_font(FONT_FAMILY, "", base * self.layout.entry_meta_ratio * _PX_TO_PT)
            self.set_text_color(107, 114, 128)
            self.cell(right_width, line_height, right, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_text_color(31, 41, 55)
        else:
            self.ln(line_height)

    def skill_tags(self, labels: list[str], base: float) -> None:
        """把专业技能画成**带底色的小标签**，与 HTML 预览保持一致。

        以前这里是用「、」连起来的**一行纯文本**：预览里明明是带底色的圆角小框，导出的 PDF
        却完全看不出标签的样子（用户实测反馈："预览里是蓝色小框，导出 PDF 后没有了"）。
        其余排版都在对齐预览，这一项没有理由例外。
        """
        items = [str(label).strip() for label in labels if str(label).strip()]
        if not items:
            return
        metrics = skill_tag_metrics(
            base, line_height=self.layout.line_height, tag_ratio=self.layout.tag_font_ratio
        )
        available = self.content_width
        self.set_font(FONT_FAMILY, "", metrics.font_pt)
        widths = [self.get_string_width(label) + 2 * metrics.padding_x for label in items]
        fill = soft_accent(self.accent)

        for row in wrap_skill_tags(widths, max_width=available, gap=metrics.gap_x):
            self.ensure_space(metrics.height + metrics.gap_y)
            top = self.get_y()
            left = self.layout.margin_x
            for index in row:
                width = widths[index]
                self.set_fill_color(*fill)
                self.set_draw_color(*fill)
                self.rect(
                    left,
                    top,
                    width,
                    metrics.height,
                    style="F",
                    round_corners=True,
                    corner_radius=metrics.radius,
                )
                self.set_text_color(*self.accent)
                self.set_xy(left + metrics.padding_x, top)
                self.cell(width - 2 * metrics.padding_x, metrics.height, items[index])
                left += width + metrics.gap_x
            self.set_y(top + metrics.height + metrics.gap_y)
            self.set_x(self.layout.margin_x)
        # 标签用强调色写字，用完必须把文字颜色还原，否则后面的正文也会变成强调色。
        self.set_text_color(31, 41, 55)

    def meta_line(self, text: str, base: float) -> None:
        """条目下的副行（绩点 / 核心课程 / 技术栈）。

        对应模板里的 `.entry .sub`，所以字号比例取 `entry_sub_ratio`——**不是**条目头右侧
        `.entry-head .meta` 的 `entry_meta_ratio`（两者多数模板相同，technical 却是 0.9 vs 0.86）。
        """
        if not text.strip():
            return
        size = base * self.layout.entry_sub_ratio
        line_height = self.line_advance(size)
        self.ensure_space(line_height)
        self.set_font(FONT_FAMILY, "", size * _PX_TO_PT)
        self.set_text_color(107, 114, 128)
        self.set_x(self.layout.margin_x)
        self.multi_cell(
            self.content_width,
            line_height,
            text,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        self.set_text_color(31, 41, 55)


def _join(values: list[str], separator: str = " · ") -> str:
    return separator.join(str(item).strip() for item in values if str(item).strip())


def _photo_bytes(data_url: str) -> bytes | None:
    import base64
    import binascii

    _, separator, encoded = data_url.partition(",")
    if not separator:
        return None
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None


@dataclass(frozen=True)
class ResumePDF:
    """生成好的 PDF，连同它的实际页数与一页适配结果。

    ``scale`` 是实际使用的字号缩放（1.0 表示没有缩），``overflow`` 表示"缩到下限仍塞不下"。
    调用方据此提示用户"内容超出所选页数"，而不是让用户下载完才发现。
    """

    content: bytes
    pages: int
    scale: float = 1.0
    overflow: bool = False


def _register_fonts(pdf: FPDF, regular: str, bold: str) -> None:
    try:
        pdf.add_font(FONT_FAMILY, "", regular)
        pdf.add_font(FONT_FAMILY, "B", bold)
    except Exception as exc:  # noqa: BLE001 - 字体解析失败要变成可读提示
        raise ResumePDFError(f"加载中文字体失败（{Path(regular).name}）：{exc}") from exc


def _draw_resume(pdf: _ResumePDF, resume: ResumeContent, *, include_photo: bool = True) -> None:
    """把结构化简历画进 ``pdf``。测量与最终渲染共用这一段，保证"量的"就是"画的"。

    ``include_photo=False`` 时**连页头也不给照片预留空间**（不只是不画图）：导出选项里
    关掉照片意味着这一版内容就没有照片，字号自适应与页数判定都要按"无照片"来量，否则
    会量出一个实际不存在的照片高度。
    """
    layout = pdf.layout
    base = layout.scaled_base_px

    # ===== 页头 =====
    header_top = pdf.get_y()
    photo = _photo_bytes(resume.photo) if (resume.photo and include_photo) else None
    if photo:
        try:
            from io import BytesIO

            pdf.image(
                BytesIO(photo),
                x=PAGE_WIDTH_MM - layout.margin_x - PHOTO_WIDTH,
                y=header_top,
                w=PHOTO_WIDTH,
                h=PHOTO_HEIGHT,
            )
        except Exception:  # noqa: BLE001 - 照片坏了不能阻断导出
            logger.warning("简历照片无法写入 PDF，已跳过")

    text_width = pdf.content_width - (PHOTO_WIDTH + 6 if photo else 0)
    name_size = base * layout.name_ratio
    pdf.set_font(FONT_FAMILY, "B", name_size * _PX_TO_PT)
    pdf.set_text_color(*pdf.accent)
    pdf.set_x(layout.margin_x)
    name_line = resume.name + (f"  {resume.gender}" if resume.gender else "")
    pdf.multi_cell(text_width, pdf.line_advance(name_size), name_line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(31, 41, 55)
    if resume.job_intent:
        intent_size = base * layout.intent_ratio
        pdf.set_font(FONT_FAMILY, "", intent_size * _PX_TO_PT)
        pdf.set_text_color(107, 114, 128)
        pdf.set_x(layout.margin_x)
        pdf.multi_cell(
            text_width,
            pdf.line_advance(intent_size),
            f"求职意向：{resume.job_intent}",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
    contact = _join([resume.phone, resume.email, resume.city, resume.birth_year], "    ")
    if contact:
        contact_size = base * layout.contact_ratio
        pdf.set_font(FONT_FAMILY, "", contact_size * _PX_TO_PT)
        pdf.set_text_color(107, 114, 128)
        pdf.set_x(layout.margin_x)
        pdf.multi_cell(
            text_width,
            pdf.line_advance(contact_size),
            contact,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
    pdf.set_text_color(31, 41, 55)
    pdf.set_y(max(pdf.get_y(), header_top + (PHOTO_HEIGHT if photo else 0)))

    # ===== 各分区 =====
    # 区块之间的留白统一由 `section_title` 里的 section_gap 负责，所以页头之后不再
    # 额外加一段间距（否则第一段之前会比预览多一块空白）。
    if resume.summary.strip():
        pdf.section_title("个人总结", base)
        pdf.set_font(FONT_FAMILY, "", base * _PX_TO_PT)
        pdf.set_x(layout.margin_x)
        pdf.multi_cell(
            pdf.content_width,
            pdf.line_advance(base),
            resume.summary.strip(),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

    if resume.education:
        pdf.section_title("教育经历", base)
        for edu in resume.education:
            pdf.entry_head(
                _join([edu.school, edu.major], " · "),
                _join([edu.degree, f"{edu.start_date} - {edu.end_date}"], " · "),
                base,
            )
            if edu.gpa:
                pdf.meta_line(f"绩点/排名：{edu.gpa}", base)
            if edu.courses:
                pdf.meta_line(f"核心课程：{'、'.join(edu.courses)}", base)
            pdf.bullets(edu.achievements, base)

    if resume.experience:
        pdf.section_title("实习/工作经历", base)
        for exp in resume.experience:
            pdf.entry_head(
                _join([exp.company, exp.role], " · "),
                f"{exp.start_date} - {exp.end_date}",
                base,
            )
            pdf.bullets(exp.description, base)

    if resume.campus_experience:
        pdf.section_title("校园经历", base)
        for item in resume.campus_experience:
            pdf.entry_head(
                _join([item.organization, item.role], " · "),
                f"{item.start_date} - {item.end_date}",
                base,
            )
            pdf.bullets(item.description, base)

    if resume.projects:
        pdf.section_title("项目经历", base)
        for project in resume.projects:
            pdf.entry_head(
                _join([project.name, project.role], " · "),
                f"{project.start_date} - {project.end_date}",
                base,
            )
            if project.tech_stack:
                pdf.meta_line(f"技术栈：{'、'.join(project.tech_stack)}", base)
            pdf.bullets(project.description, base)
            pdf.bullets(project.highlights, base)

    if resume.skills:
        pdf.section_title("专业技能", base)
        # 标签文案与预览一致：`技能名（等级）`。用标签绘制而不是「、」连接的一行文本——
        # 后者在预览里是带底色的小框，导出后却看不出任何标签形状。
        pdf.skill_tags(
            [
                f"{skill.name}（{skill.level}）" if skill.level else skill.name
                for skill in resume.skills
            ],
            base,
        )

    if resume.awards:
        pdf.section_title("荣誉奖项", base)
        pdf.bullets(
            [
                _join([award.name, award.date, award.description])
                for award in resume.awards
            ],
            base,
        )


def measure_content_height(
    resume: ResumeContent,
    *,
    accent: tuple[int, int, int],
    layout: ResumeLayout,
    regular: str | None = None,
    bold: str | None = None,
    include_photo: bool = True,
) -> float:
    """量出这份简历在给定版式下的内容高度（mm）。

    **只测量、不决策**：把自动分页关掉，让内容连续排下来，末尾的 y 减去上页边距就是
    真实内容高度。这样"该不该缩、缩到多少"（`decide_fit_scale`）与"内容有多高"各自
    独立，后续要做"并排多页"时只换决策那一步即可。
    """
    if regular is None or bold is None:
        fonts = _resolve_font_paths()
        if fonts is None:
            raise ResumePDFError("未找到可用的中文字体，无法在服务端生成 PDF")
        regular, bold = fonts
    pdf = _ResumePDF(accent, layout, measuring=True)
    _register_fonts(pdf, regular, bold)
    pdf.add_page()
    _draw_resume(pdf, resume, include_photo=include_photo)
    return pdf.get_y() - layout.margin_top


def rendered_page_count(
    resume: ResumeContent,
    *,
    accent: tuple[int, int, int],
    layout: ResumeLayout,
    regular: str | None = None,
    bold: str | None = None,
    include_photo: bool = True,
) -> int:
    """真实渲染这份简历，返回它实际排出来的页数。

    **这是"装不装得下"的唯一权威判据**：``measure_content_height`` 量的是**连续内容高度**，
    而真实分页会因 `ensure_space`（不切断条目）提前换页、留下一段空隙——于是"连续高 < 可用高"
    仍可能排出第二页。按连续高判定会**说谎**（报告 1 页、实际 2 页、``overflow=False``）。
    这里让内容按真实分页排一遍，直接数页数。
    """
    if regular is None or bold is None:
        fonts = _resolve_font_paths()
        if fonts is None:
            raise ResumePDFError("未找到可用的中文字体，无法在服务端生成 PDF")
        regular, bold = fonts
    pdf = _ResumePDF(accent, layout)
    _register_fonts(pdf, regular, bold)
    pdf.add_page()
    _draw_resume(pdf, resume, include_photo=include_photo)
    return pdf.pages_count


def decide_fit_scale(
    measure_pages, measure_height, *, page_limit: int, usable_height: float
) -> tuple[float, bool]:
    """决定一页适配的缩放：返回 ``(scale, overflow)``。

    **判定"装得下"以真实页数为准**（``measure_pages(scale) <= page_limit``），而不是连续
    内容高度——这正是"请求 1 页、产出 2 页，而 overflow 还在说装得下"那个 bug 的修法。

    收敛策略（尽量贴近预览脚本 `_resume_fit_script.j2`）：
      1. 从 1.0 起，只在真实页数超限时才继续缩（绝不来回震荡、也绝不放大）；
      2. 连续高明显超出可用高时，按 `可用高 / 内容高 × 0.995` 比例跳一档（快）；
      3. 连续高已"达标"（在容差内）却仍多页时，比例档跳不动（比值 ≥ 1），退化为
         **每轮至少收 `_FIT_PAGE_STEP`** 的离散档——专门处理"连续高 ≠ 实际分页高"的边界；
      4. 下限 `MIN_FIT_SCALE`；最多 `_FIT_MAX_PASSES` 轮；
      5. 到下限仍多页 → ``overflow=True``，如实标出，交给调用方提示用户加页/换字号，
         而不是把文字裁掉（与预览"塞不下就溢出并提示"一致）。

    ``measure_pages`` / ``measure_height`` 分别是 ``scale -> 页数`` 与 ``scale -> 连续高(mm)``
    的可调用对象。高度只在页数超限时才需要——常见情形（本来就放得下）只渲染一次即可放行。
    """
    scale = 1.0
    pages = measure_pages(scale)
    for _ in range(_FIT_MAX_PASSES):
        if pages <= page_limit:
            return scale, False
        height = measure_height(scale)
        # 连续高明显超出 → 按比例一次跳够；连续高已达标（比例档失效）→ 用离散下限兜底。
        ratio = usable_height / height * _FIT_RATIO_MARGIN if height > usable_height + _FIT_TOLERANCE_MM else 1.0
        next_scale = max(MIN_FIT_SCALE, scale * min(ratio, 1 - _FIT_PAGE_STEP))
        if next_scale >= scale - _FIT_MIN_STEP:
            break
        scale = next_scale
        pages = measure_pages(scale)
    return scale, pages > page_limit


def build_resume_pdf(
    resume: ResumeContent,
    *,
    template: str = "classic",
    page_limit: int = 1,
    font_scale: str = "standard",
    format_config: dict | None = None,
    margin_mm: float | None = None,
    include_photo: bool = True,
) -> ResumePDF:
    """把结构化简历渲染成 PDF。

    版式（行距/页边距/区块间距**与各层级字号比例**）与预览对齐：默认取所选**样式模板**的
    版式值，用户在「格式模板」里设过的 `line_height` / `page_padding` / `section_gap` 会
    覆盖它们；``margin_mm`` 是导出时的页边距直接覆盖；内容超过所选页数时按与预览同口径缩
    **字号派生尺寸**来装下，是否"装得下"以**真实渲染的页数**为准（见 `decide_fit_scale`），
    实在装不下就如实标记 ``overflow``。
    """
    from .resume_templates import FONT_SCALES, template_spec

    fonts = _resolve_font_paths()
    if fonts is None:
        raise ResumePDFError(
            "未找到可用的中文字体，无法在服务端生成 PDF；请用「打印 / 另存为 PDF」导出，"
            f"或设置环境变量 {FONT_ENV_VAR} 指向一个中文 TTF/TTC 字体文件"
        )
    regular, bold = fonts
    spec = template_spec(template)
    scale = FONT_SCALES.get(font_scale) or FONT_SCALES["standard"]
    base = float(scale["base_px"])

    from .resume_templates import validated_format_config

    overrides = validated_format_config(format_config)
    accent_adjust = overrides.get("font_scale_adjust")
    if isinstance(accent_adjust, (int, float)):
        base = round(base * float(accent_adjust), 2)
    accent = resolve_accent(spec["name"], overrides)

    layout = resolve_layout(
        template=spec["name"], base_px=base, format_config=overrides, margin_mm=margin_mm
    )
    limit = max(1, min(int(page_limit), MAX_RESUME_PAGES))

    # 一页适配：先测**真实页数**→ 再决（缩到多少）→ 最后照决策渲染一遍。
    usable = layout.usable_height_per_page * limit

    def pages_at(value: float) -> int:
        return rendered_page_count(
            resume,
            accent=accent,
            layout=layout.with_fit_scale(value),
            regular=regular,
            bold=bold,
            include_photo=include_photo,
        )

    def height_at(value: float) -> float:
        return measure_content_height(
            resume,
            accent=accent,
            layout=layout.with_fit_scale(value),
            regular=regular,
            bold=bold,
            include_photo=include_photo,
        )

    fit_scale, overflow = decide_fit_scale(
        pages_at, height_at, page_limit=limit, usable_height=usable
    )
    final_layout = layout.with_fit_scale(fit_scale)

    pdf = _ResumePDF(accent, final_layout)
    _register_fonts(pdf, regular, bold)
    pdf.add_page()
    _draw_resume(pdf, resume, include_photo=include_photo)

    pages = pdf.pages_count
    # 硬要求：**标志不许说谎**——最终真的多出页就必须标 overflow。决策层已按页数判定，
    # 这里再兜一次，防止将来改动让"页数"与"标志"再次脱节（用户会以为一切正常）。
    if pages > limit:
        overflow = True
    if overflow:
        # 到下限仍塞不下：不裁内容，但必须让用户知道（日志只有开发者能看到，界面读 headers）。
        logger.info(
            "PDF 内容缩到下限 %.2f 仍超出所选页数上限 %s，实际 %s 页",
            fit_scale,
            limit,
            pages,
        )
    return ResumePDF(content=bytes(pdf.output()), pages=pages, scale=fit_scale, overflow=overflow)


__all__ = [
    "MIN_FIT_SCALE",
    "ResumeLayout",
    "ResumePDF",
    "ResumePDFError",
    "build_resume_pdf",
    "decide_fit_scale",
    "font_available",
    "measure_content_height",
    "rendered_page_count",
    "resolve_accent",
    "resolve_layout",
    "skill_tag_metrics",
    "soft_accent",
    "wrap_skill_tags",
]
