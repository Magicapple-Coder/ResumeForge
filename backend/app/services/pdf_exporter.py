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
from .resume.resume_sections import resolved_section_order

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


def _resolve_template_color(
    template: str,
    format_config: dict | None,
    *,
    override_key: str,
    default_key: str,
    fallback: tuple[int, int, int],
) -> tuple[int, int, int]:
    """从"格式模板覆盖 → 模板默认值 → 兜底"里取一个颜色（强调色 / 分隔线共用）。

    颜色唯一来源是 `resume_templates.template_layout_defaults`（共享知识第 10 条）；
    PDF 与 Word 都从这里取同一份颜色，禁止任何渲染器再存一份 `_TEMPLATE_COLORS`。
    """
    from .resume.resume_templates import template_layout_defaults, template_spec, validated_format_config

    spec = template_spec(template)
    overrides = validated_format_config(format_config)
    return (
        _hex_to_rgb(str(overrides.get(override_key) or ""))
        or _hex_to_rgb(str(template_layout_defaults(spec["name"])[default_key]))
        or fallback
    )


def resolve_accent(template: str, format_config: dict | None) -> tuple[int, int, int]:
    """导出用的强调色：格式模板覆盖优先，其次模板默认，最后兜底深蓝。"""
    return _resolve_template_color(
        template, format_config, override_key="accent", default_key="accent", fallback=(22, 54, 92)
    )


def resolve_line(template: str, format_config: dict | None) -> tuple[int, int, int]:
    """导出用的分隔线颜色（区块标题的下划线等）：覆盖优先，其次模板 `--line`，最后浅灰。"""
    return _resolve_template_color(
        template, format_config, override_key="line_color", default_key="line", fallback=(217, 222, 231)
    )

# 1 px = 0.75 pt = 0.2646 mm。行推进量统一按 `字号(px) × _PX_TO_MM × 行高系数` 计算。
_PX_TO_PT = 0.75
_PX_TO_MM = 0.264_583

# 正文与辅助文字的 PDF 颜色（与模板 `:root` 的 `--text` / `--muted` 同值；多数模板一致）。
_BODY_TEXT = (31, 41, 55)
_MUTED_TEXT = (107, 114, 128)

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
    页边距（mm）、行高系数、区块间距系数，各层级（姓名 / 求职意向 / 联系方式 /
    区块标题 / 条目标题 / 条目头副行 / 条目下副行 / 技能标签）的字号比例，以及**垂直间距**
    （页头 / 条目 / 副行 / 列表项 / 区块标题与正文之间）与**区块标题的形状**、**照片尺寸**。
    ``fit_scale`` 是一页适配算出的缩放，**只**乘在字号派生的尺寸上（`scaled_base_px`），
    mm 页边距不参与——与预览把 `--fit-scale` 吸进 `--fs` 的做法完全一致。
    """

    base_px: float
    margin_mm: float
    line_height: float
    section_gap: float
    name_ratio: float
    # 姓名旁附加信息（性别）的字号比例——预览里是 `.name-extra`（常规字重、muted 灰），
    # 每模板不同（classic/modern 1.0，compact/minimal/elegant 0.93，technical 0.95），
    # 与其它层级一样只从 `TEMPLATE_LAYOUT_DEFAULTS` 读。
    name_extra_ratio: float
    intent_ratio: float
    contact_ratio: float
    section_title_ratio: float
    entry_title_ratio: float
    entry_meta_ratio: float
    entry_sub_ratio: float
    tag_font_ratio: float
    # ===== 垂直间距（× 基准字号的倍数，见 `resume_templates.TEMPLATE_LAYOUT_DEFAULTS`）=====
    header_gap: float
    entry_gap: float
    sub_gap_top: float
    sub_gap_bottom: float
    li_gap: float
    # ===== 页头装饰（底边线 / modern 的浅底色块，见模板 `.header` 的 CSS）=====
    header_border_width: float
    header_border_color: str
    header_pad_bottom: float
    header_bg: str
    header_pad_x: float
    header_pad_y: float
    header_radius: float
    # ===== 区块标题的形状（来自模板 `.section-title` 的 CSS）=====
    section_title_style: str
    section_title_text: str
    section_title_align: str
    section_title_gap: float
    section_title_pad_x: float
    section_title_pad_y: float
    # ===== 照片尺寸（× 基准字号，来自模板 `.profile-photo` 的 width/height）=====
    photo_width_ratio: float
    photo_height_ratio: float
    fit_scale: float = 1.0

    @property
    def scaled_base_px(self) -> float:
        """一页适配之后的基准字号（px）。所有尺寸都由它派生。"""
        return self.base_px * self.fit_scale

    def gap_mm(self, ratio: float) -> float:
        """把"× 基准字号"的间距系数换成毫米（随一页适配缩放，与预览同口径）。"""
        return self.scaled_base_px * _PX_TO_MM * ratio

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
    from .resume.resume_templates import template_layout_defaults, validated_format_config

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
        name_extra_ratio=float(defaults["name_extra_ratio"]),
        intent_ratio=float(defaults["intent_ratio"]),
        contact_ratio=float(defaults["contact_ratio"]),
        section_title_ratio=float(defaults["section_title_ratio"]),
        entry_title_ratio=float(defaults["entry_title_ratio"]),
        # `.entry-head .meta`（条目头右侧）与 `.entry .sub`（条目下副行）是**两个**选择器，
        # 比例多数模板相同、technical 却是 0.86 / 0.9，所以各取各的，不合并。
        entry_meta_ratio=float(defaults["entry_meta_ratio"]),
        entry_sub_ratio=float(defaults["entry_sub_ratio"]),
        tag_font_ratio=float(defaults["tag_font_ratio"]),
        # 垂直间距、区块标题形状与照片尺寸同样只来自模板——这些此前只存在于模板 CSS，
        # PDF 侧没有，于是排得比预览紧（"被压扁"的主要来源）。
        header_gap=float(defaults["header_gap"]),
        entry_gap=float(defaults["entry_gap"]),
        sub_gap_top=float(defaults["sub_gap_top"]),
        sub_gap_bottom=float(defaults["sub_gap_bottom"]),
        li_gap=float(defaults["li_gap"]),
        header_border_width=float(defaults["header_border_width"]),
        header_border_color=str(defaults["header_border_color"]),
        header_pad_bottom=float(defaults["header_pad_bottom"]),
        header_bg=str(defaults["header_bg"]),
        header_pad_x=float(defaults["header_pad_x"]),
        header_pad_y=float(defaults["header_pad_y"]),
        header_radius=float(defaults["header_radius"]),
        section_title_style=str(defaults["section_title_style"]),
        section_title_text=str(defaults["section_title_text"]),
        section_title_align=str(defaults["section_title_align"]),
        section_title_gap=float(defaults["section_title_gap"]),
        section_title_pad_x=float(defaults["section_title_pad_x"]),
        section_title_pad_y=float(defaults["section_title_pad_y"]),
        photo_width_ratio=float(defaults["photo_width_ratio"]),
        photo_height_ratio=float(defaults["photo_height_ratio"]),
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
        line: tuple[int, int, int] = (217, 222, 231),
        measuring: bool = False,
    ) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.accent = accent
        # 分隔线颜色（区块标题的下划线用它），来自模板 `--line`。
        self.line_color = line
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

    def text_block_height(self, text: str, *, width: float, size_px: float, bold: bool = False) -> float:
        """量一段 `multi_cell` 文本的高度（mm），**不落笔**。

        页头的 modern 底色块要画在文字**之下**，就必须先知道文字多高——否则要么底色盖住
        文字，要么先画文字再补底色（把文字也盖住）。`dry_run=True` 只算不画。
        """
        self.set_font(FONT_FAMILY, "B" if bold else "", size_px * _PX_TO_PT)
        return float(
            self.multi_cell(
                width, self.line_advance(size_px), text, dry_run=True, output="HEIGHT"
            )
        )

    def ensure_space(self, height: float) -> None:
        """剩余空间不足时换页，避免条目被从中间截断。测量模式不换页。"""
        if self.measuring:
            return
        if self.get_y() + height > self.page_break_trigger:
            self.add_page()

    def _section_title_color(self) -> tuple[int, int, int]:
        """区块标题文字颜色：按模板 `.section-title` 的配色（accent / body / muted / white）。"""
        choice = self.layout.section_title_text
        if choice == "accent":
            return self.accent
        if choice == "white":
            return (255, 255, 255)
        if choice == "muted":
            return _MUTED_TEXT
        return _BODY_TEXT

    def section_title(self, text: str, base: float, *, leading_gap: float) -> None:
        """画一个区块标题——**形状与颜色由模板 `.section-title` 决定**，与预览同口径。

        此前这里对所有模板统一画一条"贯穿正文宽度的横向下划线"，而预览其实各不相同：
        classic 是**左侧竖条**、modern 是浅底色块、compact/elegant 是细下划线、technical
        是实心底色块、minimal 什么装饰都没有。统一画下划线正是"PDF 与预览不一致"里最显眼
        的一处。现在形状由 `section_title_style` 驱动，各模板各画各的。

        ``leading_gap`` 是标题**之前**的留白系数（× 基准字号）：第一个区块之前是页头
        `.header` 的 margin-bottom，之后是上一区块 `.section` 的 margin-bottom——预览里
        `.section` 只有 bottom 边距，所以必须把"前一段的间距"显式带进来，否则第一段会比预览紧。
        """
        layout = self.layout
        size = base * layout.section_title_ratio
        title_height = self.line_advance(size)
        pad_x = layout.gap_mm(layout.section_title_pad_x)
        pad_y = layout.gap_mm(layout.section_title_pad_y)
        gap_after = layout.gap_mm(layout.section_title_gap)
        style = layout.section_title_style
        bar_w = 4 * _PX_TO_MM  # classic 的左竖条是固定 4px（与预览 border-left 一致）

        if style in ("soft_box", "accent_box"):
            block_height = title_height + 2 * pad_y
        elif style == "underline":
            block_height = title_height + pad_y
        else:
            block_height = title_height

        self.ensure_space(layout.gap_mm(leading_gap) + block_height + gap_after)
        self.ln(layout.gap_mm(leading_gap))
        top = self.get_y()

        self.set_font(FONT_FAMILY, "B", size * _PX_TO_PT)
        text_width = self.get_string_width(text)
        text_x = layout.margin_x + pad_x

        if style == "left_bar":
            text_x = layout.margin_x + bar_w + pad_x
            self.set_fill_color(*self.accent)
            self.rect(layout.margin_x, top, bar_w, title_height, style="F")
        elif style == "soft_box":
            self.set_fill_color(*soft_accent(self.accent))
            self.rect(
                layout.margin_x,
                top,
                text_width + 2 * pad_x,
                block_height,
                style="F",
                round_corners=True,
                corner_radius=base * _PX_TO_MM * 0.4,
            )
        elif style == "accent_box":
            self.set_fill_color(*self.accent)
            self.rect(layout.margin_x, top, text_width + 2 * pad_x, block_height, style="F")

        if layout.section_title_align == "center":
            text_x = layout.margin_x + max(0.0, (self.content_width - text_width) / 2)

        self.set_text_color(*self._section_title_color())
        self.set_xy(text_x, top + pad_y)
        self.cell(0, title_height, text, new_x=XPos.RIGHT, new_y=YPos.TOP)

        if style == "underline":
            line_y = top + title_height + pad_y
            self.set_draw_color(*self.line_color)
            self.set_line_width(0.3)
            self.line(layout.margin_x, line_y, PAGE_WIDTH_MM - layout.margin_x, line_y)

        self.set_y(top + block_height + gap_after)
        self.set_x(layout.margin_x)
        self.set_text_color(*_BODY_TEXT)

    def bullets(self, items: list[str], base: float, indent: float = 3.0) -> None:
        """画一段带圆点的列表项（项间留白对齐模板的 li margin）。"""
        layout = self.layout
        line_height = self.line_advance(base)
        li_gap = layout.gap_mm(layout.li_gap)
        self.set_font(FONT_FAMILY, "", base * _PX_TO_PT)
        first = True
        for item in items:
            text = str(item).strip()
            if not text:
                continue
            # 列表项之间的留白 = 模板 `li { margin-bottom }`（此前 PDF 完全没有这一项）。
            if not first:
                self.ln(li_gap)
            first = False
            self.ensure_space(line_height * 2)
            self.set_x(layout.margin_x + indent)
            self.multi_cell(
                self.content_width - indent,
                line_height,
                f"· {text}",
                align="L",
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )

    def entry_head(self, left: str, right: str, base: float) -> None:
        """画条目头（左标题加粗、右时间戳淡化右对齐）。"""
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
            self.set_text_color(*_MUTED_TEXT)
            self.cell(right_width, line_height, right, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_text_color(*_BODY_TEXT)
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
        self.set_text_color(*_BODY_TEXT)

    def meta_line(self, text: str, base: float) -> None:
        """条目下的副行（绩点 / 核心课程 / 技术栈）。

        对应模板里的 `.entry .sub`，所以字号比例取 `entry_sub_ratio`——**不是**条目头右侧
        `.entry-head .meta` 的 `entry_meta_ratio`（两者多数模板相同，technical 却是 0.9 vs 0.86）。
        上下留白也取 `.entry .sub` 的 `margin`（`sub_gap_top` / `sub_gap_bottom`）——此前 PDF
        完全没有这两段间距，是"被压扁"的一部分。
        """
        if not text.strip():
            return
        layout = self.layout
        size = base * layout.entry_sub_ratio
        line_height = self.line_advance(size)
        self.ensure_space(layout.gap_mm(layout.sub_gap_top) + line_height)
        self.ln(layout.gap_mm(layout.sub_gap_top))
        self.set_font(FONT_FAMILY, "", size * _PX_TO_PT)
        self.set_text_color(*_MUTED_TEXT)
        self.set_x(layout.margin_x)
        self.multi_cell(
            self.content_width,
            line_height,
            text,
            align="L",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        self.ln(layout.gap_mm(layout.sub_gap_bottom))
        self.set_text_color(*_BODY_TEXT)


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


def crop_image_to_cover(data: bytes, target_ratio: float) -> bytes:
    """把图片**居中裁剪**成 ``target_ratio``（宽/高）——`object-fit: cover` 的等价物。

    模板里 `.profile-photo` 是 `object-fit: cover`：保持宽高比、居中裁剪、填满目标框。
    而 fpdf2 的 ``image()`` 在同时给定 ``w`` 与 ``h`` 时会**强制拉伸**到该尺寸，不先裁剪
    的话，用户照片的宽高比一旦与模板照片框（`photo_width_ratio / photo_height_ratio`）
    不同就会变形——这正是"PDF 里照片被压扁"的来源。Word 侧共用本函数保持同一口径。

    纯函数、只依赖 Pillow（fpdf2 的既有依赖，已锁定在 requirements.txt），便于离线单测。
    EXIF 方向（Orientation）顺带转正（手机竖拍不转正的话，裁出来的仍是躺倒的）。比例
    已经一致且无方向信息时**原样返回**，避免一次无谓的重编码损伤画质。解码失败会抛出
    Pillow 的异常——调用方（PDF / Word）已有"照片坏了就跳过导出"的兜底，不在这里吞。
    """
    from io import BytesIO

    from PIL import Image, ImageOps
    from PIL.ExifTags import Base as ExifBase

    with Image.open(BytesIO(data)) as source:
        fmt = (source.format or "PNG").upper()
        # 部分手机拍出的多帧 JPEG 会被 Pillow 认成 MPO，按 MPO 存回去 fpdf2 解不了。
        if fmt == "MPO":
            fmt = "JPEG"
        image = ImageOps.exif_transpose(source)
        width, height = image.size
        if width <= 0 or height <= 0:
            raise ValueError(f"图片尺寸不合法：{width}x{height}")
        ratio = width / height
        if abs(ratio - target_ratio) <= 1e-9:
            # 比例已经一致：只有 EXIF 方向需要转正时才值得重编码，否则原样返回。
            # （`exif_transpose` 没有可转正的内容时也会返回一个副本，不能用对象同一性判断。）
            orientation = source.getexif().get(ExifBase.Orientation, 1)
            if orientation in (0, 1):
                return data
        if ratio > target_ratio:
            # 太宽：左右各裁掉一点，保持高度。
            new_width = max(1, round(height * target_ratio))
            left = (width - new_width) // 2
            image = image.crop((left, 0, left + new_width, height))
        else:
            # 太高：上下各裁掉一点，保持宽度。
            new_height = max(1, round(width / target_ratio))
            top = (height - new_height) // 2
            image = image.crop((0, top, width, top + new_height))
        if fmt == "JPEG" and image.mode not in ("RGB", "L", "CMYK"):
            # JPEG 不支持透明通道（RGBA 存不回去），先落到 RGB。
            image = image.convert("RGB")
        buffer = BytesIO()
        image.save(buffer, format=fmt)
        return buffer.getvalue()


# fpdf2 在 cell 内放文字基线的规则：基线 = 单元格顶 + 0.5×行高 + 0.3×字号（见其
# `_render_styled_text_line` 的 `Td` 定位）。同一行画两种字号时若不给性别那半格补偿，
# 小字号会被抬得比姓名的基线高约 1mm——预览里两个 span 是 inline、基线对齐的，照做。
_CELL_BASELINE_FONT_FACTOR = 0.3


@dataclass(frozen=True)
class NameGenderPlan:
    """页头"姓名（+ 性别）"这一块的绘制计划（只含几何，不含文字样式）。

    预览里性别是 `.name` 内独立的 `<span class="name-extra">`：常规字重、muted 灰、
    `name_extra_ratio` 倍字号，与姓名**同行**（放不下就折到下一行）。PDF 此前把性别
    拼进姓名字符串、整行用姓名的字号/粗体/强调色渲染——"性别和姓名一样大"即来源于此。
    计划与绘制（`draw_name_gender`）是同一逻辑的两半：先量后排，块高严格等于
    ``height``，保证测量路径（`measure_content_height`）与渲染路径"量的就是画的"。
    """

    same_line: bool    # 性别是否与姓名同一行（无性别时为 False）
    gender_text: str   # 同行时含前导空格；独占一行时为纯文本；无性别为空串
    gender_width: float  # gender_text 的宽度（mm，按 extra 字号量出）
    height: float      # 整块高度（mm）：同行 = 两种字号行高中较大者；换行 = 姓名 + 性别两段


def plan_name_gender(
    pdf: _ResumePDF,
    name: str,
    gender: str,
    *,
    width: float,
    name_size: float,
    extra_size: float,
) -> NameGenderPlan:
    """量出"姓名（+ 性别）"块的排法（只量不画），与 `draw_name_gender` 严格互逆。

    ``name_size`` / ``extra_size`` 是字号（px），分别乘 `name_ratio` / `name_extra_ratio`
    得到（调用方从 `ResumeLayout` 取，本函数不碰注册表）。
    """
    name_height = pdf.text_block_height(name, width=width, size_px=name_size, bold=True)
    gender_text = (gender or "").strip()
    if not gender_text:
        return NameGenderPlan(same_line=False, gender_text="", gender_width=0.0, height=name_height)

    pdf.set_font(FONT_FAMILY, "B", name_size * _PX_TO_PT)
    name_width = pdf.get_string_width(name)
    pdf.set_font(FONT_FAMILY, "", extra_size * _PX_TO_PT)
    # 与预览一致：两个 span 之间就是一个空格，间隔算进性别那段的宽度里。
    inline_text = f" {gender_text}"
    inline_width = pdf.get_string_width(inline_text)
    # 同行条件：姓名本身单行、且"姓名 + 性别"放得下（cell 内左右各有一段内边距要一并算）。
    name_single_line = name_height <= pdf.line_advance(name_size) + 1e-6
    if name_single_line and name_width + inline_width + 2 * pdf.c_margin <= width:
        row_height = max(pdf.line_advance(name_size), pdf.line_advance(extra_size))
        return NameGenderPlan(same_line=True, gender_text=inline_text, gender_width=inline_width, height=row_height)
    # 放不下：性别折到姓名下一行（预览的 inline 折行行为），各按各的字号计高。
    own_height = pdf.text_block_height(gender_text, width=width, size_px=extra_size)
    return NameGenderPlan(same_line=False, gender_text=gender_text, gender_width=inline_width, height=name_height + own_height)


def draw_name_gender(
    pdf: _ResumePDF,
    name: str,
    plan: NameGenderPlan,
    *,
    width: float,
    name_size: float,
    extra_size: float,
) -> None:
    """按 `plan` 画"姓名（+ 性别）"块：姓名用姓名字号/粗体/强调色，性别用 extra 口径。

    画完把光标放回块左下角（x 回到起笔处、y 前进 ``plan.height``），与 multi_cell 的
    收尾行为一致，调用方不必知道这块是几个 cell 画出来的。
    """
    left = pdf.get_x()
    top = pdf.get_y()
    pdf.set_text_color(*pdf.accent)
    if plan.same_line:
        pdf.set_font(FONT_FAMILY, "B", name_size * _PX_TO_PT)
        name_width = pdf.get_string_width(name)
        pdf.cell(name_width, plan.height, name, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_font(FONT_FAMILY, "", extra_size * _PX_TO_PT)
        pdf.set_text_color(*_MUTED_TEXT)
        # 基线对齐补偿：把性别那格加高 2×0.3×字号差，两种字号的基线即重合
        # （cell 文字起点还各带一段左右内边距，两种字号下正好互相抵消，不另补）。
        baseline_gap = _CELL_BASELINE_FONT_FACTOR * (name_size - extra_size) * _PX_TO_MM
        pdf.cell(
            plan.gender_width,
            plan.height + 2 * baseline_gap,
            plan.gender_text,
            new_x=XPos.LMARGIN,
            new_y=YPos.TOP,
        )
    else:
        pdf.set_font(FONT_FAMILY, "B", name_size * _PX_TO_PT)
        pdf.multi_cell(
            width,
            pdf.line_advance(name_size),
            name,
            align="L",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        if plan.gender_text:
            pdf.set_font(FONT_FAMILY, "", extra_size * _PX_TO_PT)
            pdf.set_text_color(*_MUTED_TEXT)
            pdf.set_x(left)
            pdf.multi_cell(
                width,
                pdf.line_advance(extra_size),
                plan.gender_text,
                align="L",
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )
    pdf.set_xy(left, top + plan.height)
    pdf.set_text_color(*_BODY_TEXT)


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


def _draw_resume(
    pdf: _ResumePDF,
    resume: ResumeContent,
    *,
    include_photo: bool = True,
    format_config: dict | None = None,
) -> None:
    """把结构化简历画进 ``pdf``。测量与最终渲染共用这一段，保证"量的"就是"画的"。

    ``include_photo=False`` 时**连页头也不给照片预留空间**（不只是不画图）：导出选项里
    关掉照片意味着这一版内容就没有照片，字号自适应与页数判定都要按"无照片"来量，否则
    会量出一个实际不存在的照片高度。

    ``format_config`` 里可能带 ``section_order``（分区顺序）。**分页会受顺序影响**
    （`ensure_space` 不切断条目，于是某个分区被推到下一页时留白多少与顺序有关），
    所以测量路径也要用同一份配置，否则"量的"与"画的"又分家了。
    """
    layout = pdf.layout
    base = layout.scaled_base_px

    # 照片尺寸由模板 `.profile-photo` 的宽高（× 字号）派生——预览里它随字号/缩放走，
    # PDF 此前却是固定 22×28mm，字号一大一小就对不上（用户看到"照片大小与字号不协调"）。
    photo_w = layout.gap_mm(layout.photo_width_ratio)
    photo_h = layout.gap_mm(layout.photo_height_ratio)

    # ===== 页头（含装饰：底边线 / modern 的浅底色块）=====
    # 页头的装饰同样只来自模板 `.header` 的 CSS：底边线（宽度固定 px、强调色）、文字与线之间的
    # padding-bottom，以及 modern 那种浅底色块（`background: var(--accent-soft)` + 圆角 + 四周内边距）。
    hdr_pad_x = layout.gap_mm(layout.header_pad_x)
    hdr_pad_y = layout.gap_mm(layout.header_pad_y)
    hdr_pad_bottom = layout.gap_mm(layout.header_pad_bottom)
    hdr_radius = layout.gap_mm(layout.header_radius)
    # 底边线宽度是固定的 px（CSS `border-bottom: Npx`），不随字号/一页适配缩放，与预览一致。
    hdr_border_w = layout.header_border_width * _PX_TO_MM
    header_has_bg = layout.header_bg == "soft_accent"

    header_top = pdf.get_y()
    content_left = layout.margin_x + hdr_pad_x
    content_top = header_top + hdr_pad_y
    inner_width = pdf.content_width - 2 * hdr_pad_x

    photo = _photo_bytes(resume.photo) if (resume.photo and include_photo) else None
    text_width = inner_width - (photo_w + 6 if photo else 0)

    name_size = base * layout.name_ratio
    extra_size = base * layout.name_extra_ratio
    gender = (resume.gender or "").strip()
    intent_text = f"求职意向：{resume.job_intent}" if resume.job_intent else ""
    contact = _join([resume.phone, resume.email, resume.city, resume.birth_year], "    ")

    # 先量页头正文的高度（不落笔）：modern 的底色块要按它定尺寸、并画在文字之下。
    # 姓名与性别**各量各的**（`plan_name_gender`，与绘制同一逻辑），性别不再并入
    # 姓名行的字号计算——此前拼成一条 name_line，性别被按姓名字号量与画。
    name_plan = plan_name_gender(
        pdf, resume.name, gender, width=text_width, name_size=name_size, extra_size=extra_size
    )
    text_height = name_plan.height
    if intent_text:
        text_height += pdf.text_block_height(
            intent_text, width=text_width, size_px=base * layout.intent_ratio
        )
    if contact:
        text_height += pdf.text_block_height(
            contact, width=text_width, size_px=base * layout.contact_ratio
        )
    photo_span = photo_h if photo else 0.0
    header_content_h = max(text_height, photo_span)

    if header_has_bg:
        pdf.set_fill_color(*soft_accent(pdf.accent))
        pdf.rect(
            layout.margin_x,
            header_top,
            pdf.content_width,
            hdr_pad_y + header_content_h + hdr_pad_y,
            style="F",
            round_corners=hdr_radius > 0,
            corner_radius=hdr_radius,
        )

    if photo:
        try:
            from io import BytesIO

            # 先按目标框比例居中裁剪（object-fit: cover 的等价物）再交给 fpdf2——
            # 它同时给定 w 与 h 时会强制拉伸，不裁剪的照片宽高比一不同就变形。
            # 坏图（裁剪/解码失败）由这里的兜底跳过照片，不阻断导出。
            pdf.image(
                BytesIO(crop_image_to_cover(photo, photo_w / photo_h)),
                x=PAGE_WIDTH_MM - layout.margin_x - hdr_pad_x - photo_w,
                y=content_top,
                w=photo_w,
                h=photo_h,
            )
        except Exception:  # noqa: BLE001 - 照片坏了不能阻断导出
            logger.warning("简历照片无法写入 PDF，已跳过")

    pdf.set_y(content_top)
    pdf.set_x(content_left)
    # 姓名（姓名字号/粗体/强调色）与性别（extra 字号/常规/muted）同块绘制，见 plan。
    draw_name_gender(
        pdf, resume.name, name_plan, width=text_width, name_size=name_size, extra_size=extra_size
    )
    pdf.set_text_color(*_BODY_TEXT)
    if intent_text:
        intent_size = base * layout.intent_ratio
        pdf.set_font(FONT_FAMILY, "", intent_size * _PX_TO_PT)
        pdf.set_text_color(*_MUTED_TEXT)
        pdf.set_x(content_left)
        pdf.multi_cell(
            text_width,
            pdf.line_advance(intent_size),
            intent_text,
            align="L",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
    if contact:
        contact_size = base * layout.contact_ratio
        pdf.set_font(FONT_FAMILY, "", contact_size * _PX_TO_PT)
        pdf.set_text_color(*_MUTED_TEXT)
        pdf.set_x(content_left)
        pdf.multi_cell(
            text_width,
            pdf.line_advance(contact_size),
            contact,
            align="L",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
    pdf.set_text_color(*_BODY_TEXT)

    # 页头块的底：文字底与照片底取更靠下者；modern 再补下内边距，其余模板补 padding-bottom 后画底边线。
    header_bottom = max(pdf.get_y(), content_top + photo_span)
    if header_has_bg:
        header_bottom += hdr_pad_y
    if hdr_border_w > 0:
        header_bottom += hdr_pad_bottom
        line_y = header_bottom
        pdf.set_draw_color(*pdf.accent)
        pdf.set_line_width(hdr_border_w)
        pdf.line(layout.margin_x, line_y, PAGE_WIDTH_MM - layout.margin_x, line_y)
    pdf.set_y(header_bottom)

    # ===== 各分区 =====
    # 第一段之前的留白 = 页头 `.header` 的 margin-bottom（`header_gap`）；之后区块之间 = 上一段
    # `.section` 的 margin-bottom（`section_gap`）。预览里 `.section` 只有 bottom 边距、且页头
    # 自己也有一段 margin-bottom，所以这里必须把两种前导间距分开，否则第一段会比预览紧。
    first_section = True

    def section(title: str) -> None:
        nonlocal first_section
        leading = layout.header_gap if first_section else layout.section_gap
        pdf.section_title(title, base, leading_gap=leading)
        first_section = False

    def body(text: str) -> None:
        pdf.set_font(FONT_FAMILY, "", base * _PX_TO_PT)
        pdf.set_x(layout.margin_x)
        pdf.multi_cell(
            pdf.content_width,
            pdf.line_advance(base),
            text,
            align="L",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

    def draw_summary() -> None:
        if resume.summary.strip():
            section("个人总结")
            body(resume.summary.strip())


    def draw_education() -> None:
        if resume.education:
            section("教育经历")
            for index, edu in enumerate(resume.education):
                # 同一分区内条目之间的留白 = 模板 `.entry { margin-bottom }`（此前 PDF 没有）。
                if index:
                    pdf.ln(layout.gap_mm(layout.entry_gap))
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


    def draw_experience() -> None:
        if resume.experience:
            section("实习/工作经历")
            for index, exp in enumerate(resume.experience):
                if index:
                    pdf.ln(layout.gap_mm(layout.entry_gap))
                pdf.entry_head(
                    _join([exp.company, exp.role], " · "),
                    f"{exp.start_date} - {exp.end_date}",
                    base,
                )
                pdf.bullets(exp.description, base)


    def draw_campus() -> None:
        if resume.campus_experience:
            section("校园经历")
            for index, item in enumerate(resume.campus_experience):
                if index:
                    pdf.ln(layout.gap_mm(layout.entry_gap))
                pdf.entry_head(
                    _join([item.organization, item.role], " · "),
                    f"{item.start_date} - {item.end_date}",
                    base,
                )
                pdf.bullets(item.description, base)


    def draw_projects() -> None:
        if resume.projects:
            section("项目经历")
            for index, project in enumerate(resume.projects):
                if index:
                    pdf.ln(layout.gap_mm(layout.entry_gap))
                # 项目名在左、`角色 · 时间` 在右——与预览 `_resume_sections.j2` 一致
                # （此前把角色并进了左边：`name · role`，看起来与预览不是一回事）。
                pdf.entry_head(
                    project.name,
                    _join([project.role, f"{project.start_date} - {project.end_date}"], " · "),
                    base,
                )
                if project.tech_stack:
                    pdf.meta_line(f"技术栈/工具：{'、'.join(project.tech_stack)}", base)
                pdf.bullets(project.description, base)
                pdf.bullets(project.highlights, base)


    def draw_skills() -> None:
        if resume.skills:
            section("专业技能")
            # 标签文案与预览一致：`技能名（等级）`。用标签绘制而不是「、」连接的一行文本——
            # 后者在预览里是带底色的小框，导出后却看不出任何标签形状。
            pdf.skill_tags(
                [
                    f"{skill.name}（{skill.level}）" if skill.level else skill.name
                    for skill in resume.skills
                ],
                base,
            )


    def draw_awards() -> None:
        if resume.awards:
            section("荣誉奖项")
            pdf.bullets(
                [
                    _join([award.name, award.date, award.description])
                    for award in resume.awards
                ],
                base,
            )

    # 分区顺序由版式配置里的 section_order 决定（见 services/resume/resume_sections.py）。
    # 用字典而不是 if/elif 链：漏一个键时字典会直接 KeyError，而 if 链的表现是
    # "那个分区在 PDF 里默默消失"——同一个错误，早失败比晚失败好。
    drawers = {
        "summary": draw_summary,
        "education": draw_education,
        "experience": draw_experience,
        "campus_experience": draw_campus,
        "projects": draw_projects,
        "skills": draw_skills,
        "awards": draw_awards,
    }
    for section_key in resolved_section_order(format_config):
        drawers[section_key]()


def measure_content_height(
    resume: ResumeContent,
    *,
    accent: tuple[int, int, int],
    layout: ResumeLayout,
    regular: str | None = None,
    bold: str | None = None,
    include_photo: bool = True,
    line: tuple[int, int, int] | None = None,
    format_config: dict | None = None,
) -> float:
    """量出这份简历在给定版式下的内容高度（mm）。

    **只测量、不决策**：把自动分页关掉，让内容连续排下来，末尾的 y 减去上页边距就是
    真实内容高度。这样"该不该缩、缩到多少"（`decide_fit_scale`）与"内容有多高"各自
    独立，后续要做"并排多页"时只换决策那一步即可。

    ``line`` 是分隔线颜色（区块标题下划线用），只影响配色、不影响高度；不传则用兜底浅灰。
    """
    if regular is None or bold is None:
        fonts = _resolve_font_paths()
        if fonts is None:
            raise ResumePDFError("未找到可用的中文字体，无法在服务端生成 PDF")
        regular, bold = fonts
    pdf = _ResumePDF(accent, layout, line=line or (217, 222, 231), measuring=True)
    _register_fonts(pdf, regular, bold)
    pdf.add_page()
    _draw_resume(pdf, resume, include_photo=include_photo, format_config=format_config)
    return pdf.get_y() - layout.margin_top


def rendered_page_count(
    resume: ResumeContent,
    *,
    accent: tuple[int, int, int],
    layout: ResumeLayout,
    regular: str | None = None,
    bold: str | None = None,
    include_photo: bool = True,
    line: tuple[int, int, int] | None = None,
    format_config: dict | None = None,
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
    pdf = _ResumePDF(accent, layout, line=line or (217, 222, 231))
    _register_fonts(pdf, regular, bold)
    pdf.add_page()
    _draw_resume(pdf, resume, include_photo=include_photo, format_config=format_config)
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
    from .resume.resume_templates import FONT_SCALES, template_spec

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

    from .resume.resume_templates import validated_format_config

    overrides = validated_format_config(format_config)
    accent_adjust = overrides.get("font_scale_adjust")
    if isinstance(accent_adjust, (int, float)):
        base = round(base * float(accent_adjust), 2)
    accent = resolve_accent(spec["name"], overrides)
    line = resolve_line(spec["name"], overrides)

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
            line=line,
            format_config=overrides,
        )

    def height_at(value: float) -> float:
        return measure_content_height(
            resume,
            accent=accent,
            layout=layout.with_fit_scale(value),
            regular=regular,
            bold=bold,
            include_photo=include_photo,
            line=line,
            format_config=overrides,
        )

    fit_scale, overflow = decide_fit_scale(
        pages_at, height_at, page_limit=limit, usable_height=usable
    )
    final_layout = layout.with_fit_scale(fit_scale)

    pdf = _ResumePDF(accent, final_layout, line=line)
    _register_fonts(pdf, regular, bold)
    pdf.add_page()
    _draw_resume(pdf, resume, include_photo=include_photo, format_config=overrides)

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
    "NameGenderPlan",
    "ResumeLayout",
    "ResumePDF",
    "ResumePDFError",
    "build_resume_pdf",
    "crop_image_to_cover",
    "decide_fit_scale",
    "draw_name_gender",
    "font_available",
    "measure_content_height",
    "plan_name_gender",
    "rendered_page_count",
    "resolve_accent",
    "resolve_layout",
    "resolve_line",
    "skill_tag_metrics",
    "soft_accent",
    "wrap_skill_tags",
]
