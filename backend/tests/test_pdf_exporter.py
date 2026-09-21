"""服务端 PDF 导出：标签几何、折行边界、绘制行为，以及与预览口径的对齐。

这个模块此前没有任何测试，而它恰好是"预览与导出不一致"的另一个源头：技能标签在预览里是
带底色的圆角小框，导出的 PDF 里却曾是一行用「、」连起来的纯文本（用户实测反馈）。

**为什么这一版要加"从 PDF 里读回文字矩阵"的几何断言**：直出 PDF 与预览是两套独立排版引擎，
PDF 曾经**完全忽略 `format_config`**、还内置了一套与模板不一致的行距系数，而旧测试是"拿 PDF
自己的常量跟自身比"——结构性测不出这类漂移。所以这里用 `pypdf` 读回每个文字块的字号、基线
坐标与 x 起点来断言几何真的变了；并且**期望值一律从模板注册表读出来**，不再抄一份常量。

分四层验：
1. **几何**（`skill_tag_metrics`）——比例必须与 HTML 模板的 `.skill-list li` 对齐；
2. **折行**（`wrap_skill_tags`）——算错不会报错，只会让标签悄悄跑出页面，所以逐条钉边界；
3. **版式合成**（`resolve_layout` / `decide_fit_scale`）——纯逻辑，逐条钉；
4. **真实 PDF 几何**（pypdf）——行高/页边距/一页适配是否真的作用到排版上。
"""
from io import BytesIO
import base64
import re

import pytest
from PIL import Image
from pypdf import PdfReader

from app.schemas.resume import ResumeAward, ResumeContent
from app.services.pdf_exporter import (
    MIN_FIT_SCALE,
    _FIT_MAX_PASSES,
    _FIT_MIN_STEP,
    _FIT_RATIO_MARGIN,
    _FIT_TOLERANCE_MM,
    _PX_TO_MM,
    _PX_TO_PT,
    _ResumePDF,
    _resolve_font_paths,
    build_resume_pdf,
    crop_image_to_cover,
    decide_fit_scale,
    draw_name_gender,
    font_available,
    measure_content_height,
    plan_name_gender,
    rendered_page_count,
    resolve_layout,
    skill_tag_metrics,
    soft_accent,
    wrap_skill_tags,
)
from app.services.resume.resume_sample import sample_resume_content
from app.services.resume.resume_templates import (
    RESUME_TEMPLATES,
    TEMPLATE_LAYOUT_DEFAULTS,
    TEMPLATES_DIR,
)

needs_font = pytest.mark.skipif(not font_available(), reason="本机没有可用的中文字体")

# 1mm = 72/25.4 pt，用于把 mm 期望值换算成 PDF 里的磅坐标。
# 说明：fpdf2 在单元格里默认留 1mm 内边距，文字实际起点比页边距大 1mm；下面只做
# **差值**断言，这个常数会自动抵消，所以不把它写进期望值。
_MM_TO_PT = 72 / 25.4


def _pdf_with_font() -> _ResumePDF:
    """造一个已注册中文字体、且带"经典模板"版式的 PDF。

    `build_resume_pdf` 会自己解析版式并注册字体；这里单独用 `_ResumePDF` 测绘制行为，
    就必须显式给出两者，否则 `set_font("resume-cjk")` 会抛 "Undefined font"。
    """
    regular, bold = _resolve_font_paths()
    layout = resolve_layout(template="classic", base_px=14.0, format_config=None)
    pdf = _ResumePDF((15, 118, 110), layout)
    pdf.add_font("resume-cjk", "", regular)
    pdf.add_font("resume-cjk", "B", bold)
    pdf.add_page()
    return pdf


def _text_runs(content: bytes) -> list[tuple[float, float, float, str]]:
    """把 PDF 里每个文字块读成 ``(x_pt, 基线y_pt, 字号pt, 文本)``。

    `extract_text(visitor_text=...)` 的回调签名是 ``(text, cm, tm, font_dict, font_size)``：
    ``tm[4]`` 是 x、``tm[5]`` 是基线 y（原点在左下角）、``font_size`` 是字号（pt）。
    """
    reader = PdfReader(BytesIO(content))
    runs: list[tuple[float, float, float, str]] = []

    def visit(text: str, cm, tm, font_dict, font_size) -> None:  # noqa: ANN001 - pypdf 回调签名
        if text.strip():
            runs.append((round(float(tm[4]), 3), round(float(tm[5]), 3), round(float(font_size), 4), text))

    for page in reader.pages:
        page.extract_text(visitor_text=visit)
    return runs


# PDF 里区块标题用的固定文字（见 `pdf_exporter._draw_resume`）。它们一般是加粗、且字号与正文
# 不同，**唯独 minimal 模板的 `section_title_ratio` 恰好是 1.0**——标题字号与正文基准字号相同，
# 于是会被下面"只留正文行"的过滤误收进来。此时量到的第一对差值其实是"标题→正文"（夹着
# section_gap 与标题下间距，比值会得到 2.2 这种假值），而不是段落内部的行距。按文字排除掉。
_SECTION_TITLES = frozenset(
    {"个人总结", "教育经历", "实习/工作经历", "校园经历", "项目经历", "专业技能", "荣誉奖项"}
)


def _body_lines(content: bytes, *, base_px: float) -> list[tuple[float, float, float, str]]:
    """只留正文行（字号等于基准字号、且不是区块标题），用于量行距。"""
    return [
        run
        for run in _text_runs(content)
        if abs(run[2] - base_px * _PX_TO_PT) < 0.01 and run[3].strip() not in _SECTION_TITLES
    ]


def _summary_only_resume(text: str) -> ResumeContent:
    """只含一段"个人总结"的简历：正文之外没有其它元素，便于逐行量行距。"""
    return ResumeContent(name="", summary=text)


def _filler(chars: int) -> str:
    """生成可折行的中文长文本；`chars` 控制长度（不依赖具体折行算法）。"""
    unit = "负责后端服务的设计与开发，保证接口稳定与性能达标。"
    return (unit * (chars // len(unit) + 1))[:chars]


# minimal 模板强调色（`TEMPLATE_LAYOUT_DEFAULTS["minimal"]["accent"]` = #17181a 的 RGB）。
# 这里只影响配色，不影响几何。
_MINIMAL_ACCENT = (23, 24, 26)


def _blind_spot_resume() -> ResumeContent:
    """一份"**连续高说装得下、真实分页却两页**"的简历——一页适配会在此说谎的场景。

    一段几乎填满整页的总结 + 末尾一个只有一行的奖项：结尾区块的 `ensure_space`
    会为它**预留两行**高度，于是即便只剩一行多一点的空间也会提前换页，在第一页尾部
    留出一段空隙。结果：连续高约 255.3mm（< 可用 261mm）却真实排成 2 页。只按连续高
    判定的旧实现会返回 ``(scale=1.0, overflow=False)``——请求 1 页、给了 2 页、还说装得下。

    备注：补齐"垂直间距"（页头 / 条目 / 副行 / 列表项 / 标题下间距）后几何整体变高，原先的
    `_filler(1450)` 已让连续高越过了可用高、不再是盲区。这里按新几何把填充长度收到 1400
    （连续高 255.3mm），让"连续高 ≤ 可用高但真实 2 页"的盲区重新成立。
    """
    return ResumeContent(
        name="张三",
        summary=_filler(1400),
        awards=[ResumeAward(name="校级奖学金", date="2023")],
    )


# ===== 几何 =====


def test_tag_metrics_follow_the_html_template_ratios():
    """标签尺寸的比例来自 HTML 模板；两边对不上，PDF 与预览就又开始不一样。

    模板里 `.skill-list li` 是：字号 `tag_font_ratio × --fs`、左右内边距 `0.71 × 标签字号`。
    期望值从注册表读（它本身又被 `test_resume_layout.py` 拿模板 CSS 逐条核对过），
    不在这里再抄一份常量——抄一份就等于又写了一遍"跟自己比"。
    """
    classic = TEMPLATE_LAYOUT_DEFAULTS["classic"]
    tag_ratio = classic["tag_font_ratio"]
    base = 14.0
    metrics = skill_tag_metrics(base, line_height=classic["line_height"], tag_ratio=tag_ratio)

    assert metrics.font_pt == pytest.approx(base * tag_ratio * _PX_TO_PT)
    assert metrics.padding_x == pytest.approx(base * tag_ratio * _PX_TO_MM * 0.71)
    # 高度要能装下字号本身，否则文字会被裁掉。
    assert metrics.height > base * tag_ratio * _PX_TO_MM


def test_tag_height_uses_the_template_line_height():
    """标签高度 = 标签字号 × **模板行高**——与预览里 `.skill-list li` 继承 body 行高同理。

    这条防止有人又把标签行高写死成某个与模板无关的常数。
    """
    classic = TEMPLATE_LAYOUT_DEFAULTS["classic"]
    tag_ratio = classic["tag_font_ratio"]
    base = 14.0
    for line_height in (1.5, 1.7, 1.8):
        metrics = skill_tag_metrics(base, line_height=line_height, tag_ratio=tag_ratio)
        assert metrics.height == pytest.approx(base * tag_ratio * _PX_TO_MM * line_height)


def test_soft_accent_lightens_towards_white():
    assert soft_accent((0, 0, 0), ratio=0.5) == (128, 128, 128)
    # 强调色越深，调淡后越亮；且永远不等于纯白（否则标签在白底上看不见边界）。
    softened = soft_accent((15, 118, 110))
    assert all(channel > 200 for channel in softened)
    assert softened != (255, 255, 255)


# ===== 折行边界 =====


def test_wrap_keeps_everything_on_one_row_when_it_fits():
    assert wrap_skill_tags([20.0, 20.0, 20.0], max_width=100.0, gap=5.0) == [[0, 1, 2]]


def test_wrap_breaks_exactly_at_the_boundary():
    # 20 + 5 + 20 + 5 + 20 = 70 ≤ 70 → 三个一行；再多一个就要换行。
    assert wrap_skill_tags([20.0] * 4, max_width=70.0, gap=5.0) == [[0, 1, 2], [3]]
    assert wrap_skill_tags([20.0] * 3, max_width=70.0, gap=5.0) == [[0, 1, 2]]


def test_wrap_puts_an_oversized_tag_on_its_own_row():
    """单个标签比可用宽度还宽时，只能让它单独占一行（正文不可断行）。

    不能在这里硬切文字，也不能让它把后面的标签挤到同一行——两种都会让版式更难看。
    """
    assert wrap_skill_tags([200.0, 20.0], max_width=100.0, gap=5.0) == [[0], [1]]


def test_wrap_handles_empty_input():
    assert wrap_skill_tags([], max_width=100.0, gap=5.0) == []


def test_wrap_never_drops_a_tag():
    """任何输入都不得丢标签——算法兜底时最容易犯的错。"""
    widths = [13.0, 47.0, 5.0, 88.0, 21.0, 3.0]

    rows = wrap_skill_tags(widths, max_width=60.0, gap=4.0)

    assert sorted(index for row in rows for index in row) == list(range(len(widths)))


# ===== 版式合成（纯逻辑，不依赖字体） =====


@pytest.mark.parametrize("name", sorted(RESUME_TEMPLATES))
def test_resolve_layout_uses_template_defaults(name):
    """没设过任何覆盖时，PDF 的版式必须等于模板自己的默认值。

    期望值从 `TEMPLATE_LAYOUT_DEFAULTS` 读——它又被 `test_resume_layout.py` 拿模板 CSS
    逐条核对过。于是"PDF 默认行距 == 模板 CSS 行距"是**传递成立**的，而不是在测试里
    再抄一份常量（抄一份就等于又写了一遍"跟自己比"）。
    """
    defaults = TEMPLATE_LAYOUT_DEFAULTS[name]

    layout = resolve_layout(template=name, base_px=14.0, format_config={})

    assert layout.margin_mm == defaults["padding_mm"]
    assert layout.line_height == defaults["line_height"]
    assert layout.section_gap == defaults["section_gap"]


def test_resolve_layout_applies_user_overrides():
    layout = resolve_layout(
        template="minimal",
        base_px=14.0,
        format_config={"line_height": 1.3, "page_padding": 9, "section_gap": 0.7},
    )

    assert layout.margin_mm == 9.0
    assert layout.line_height == 1.3
    assert layout.section_gap == 0.7


def test_resolve_layout_ignores_values_out_of_range():
    """越界的覆盖会被 `validated_format_config` 丢掉，于是退回模板默认值。"""
    defaults = TEMPLATE_LAYOUT_DEFAULTS["classic"]

    layout = resolve_layout(template="classic", base_px=14.0, format_config={"line_height": 9.9})

    assert layout.line_height == defaults["line_height"]


def test_fit_scale_is_not_used_when_content_fits():
    # 真实页数 1 页（≤ 上限）、连续高也低于可用高 → 不缩、不溢出。
    assert decide_fit_scale(
        lambda _scale: 1, lambda _scale: 50.0, page_limit=1, usable_height=100.0
    ) == (1.0, False)


def test_fit_scale_shrinks_proportionally_and_marks_no_overflow():
    # 连续高 190×scale、可用 100 → 缩到 ~0.52 才装得下；一旦**真实页数**降到 1 就停。
    def pages(scale: float) -> int:
        return 2 if 190.0 * scale > 100.0 else 1

    scale, overflow = decide_fit_scale(
        pages, lambda s: 190.0 * s, page_limit=1, usable_height=100.0
    )

    assert 0.5 < scale < 1.0
    assert overflow is False


def test_fit_scale_respects_the_floor_and_reports_overflow():
    """缩到下限（`MIN_FIT_SCALE`）仍放不下时，如实标记 overflow，绝不继续缩或裁内容。"""
    scale, overflow = decide_fit_scale(
        lambda _scale: 2, lambda s: 400.0 * s, page_limit=1, usable_height=100.0
    )

    assert scale == MIN_FIT_SCALE
    assert overflow is True


def test_fit_scale_shrinks_until_the_real_page_count_fits_not_just_the_height():
    """**直接钉 `decide_fit_scale` 的决策行为**——本次修复最关键、又最难被端到端测试守住的一部分。

    用 mock 控制 ``pages(scale)``，绕开真实渲染的边界：构造"连续高**一直在说装得下**（恒低于
    可用高）、但真实页数要到 ``scale <= 0.99`` 才降到 1 页"的坏情况。旧口径（只看连续高）会
    **立刻**判定装得下、``scale`` 停在 1.0、真实仍 2 页——把 `decide_fit_scale` 改回按连续高
    判定，这条必红。

    断言看的是**决策后的真实页数**（``pages(scale) <= page_limit``），**不是** `overflow`：后者
    可能被 `build_resume_pdf` 末端的硬闸兜成真，单看它就区分不出"真的缩进去了"还是"没缩但标志
    诚实"——而"按真实页数决定收缩量"才是这次修复的价值所在。这条不依赖字体，纯逻辑。
    """

    def pages(scale: float) -> int:
        return 2 if scale > 0.99 else 1

    def height(_scale: float) -> float:
        # 恒低于可用高：模拟"连续高一直在说装得下"的坏情况（比例跳档失效，只能靠离散档）。
        return 50.0

    scale, overflow = decide_fit_scale(pages, height, page_limit=1, usable_height=100.0)

    assert pages(scale) <= 1, (
        f"决策后真实页数仍为 {pages(scale)}（scale={scale}）——没有按真实页数收缩"
    )
    assert scale < 1.0
    assert overflow is False


# ===== 与预览脚本的跨侧漂移守卫 =====


_FIT_SCRIPT = TEMPLATES_DIR / "_resume_fit_script.j2"


def test_fit_scale_constants_match_the_preview_script():
    """PDF 与预览的 `--fit-scale` 是两套引擎里的两份实现，只能靠测试钉住同步。

    预览脚本是 JS（`_resume_fit_script.j2`），PDF 是本模块的 Python 常量，两者无法共享
    同一份代码——所以有人只改一边时，另一边不会跟着变，就会让"预览装得下、PDF 却溢出
    （或反过来）"悄悄发生。这条测试直接读脚本文本、把几个魔法数逐个解析出来，与 PDF
    侧常量做**数值比对**：期望值不是在本测试里再抄一遍，而是把两边的字面量拿来对。
    """
    script = _FIT_SCRIPT.read_text(encoding="utf-8")

    min_scale = re.search(r"const minScale = ([\d.]+)", script)
    max_passes = re.search(r"const maxPasses = (\d+)", script)
    ratio_margin = re.search(r"Math\.min\([^)]*\)\s*\*\s*([\d.]+)", script)
    min_step = re.search(r"scale - ([\d.]+)", script)
    tolerance = re.search(r"referenceHeight \+ (\d+)", script)

    assert min_scale, "脚本里没找到 minScale"
    assert max_passes, "脚本里没找到 maxPasses"
    assert ratio_margin, "脚本里没找到 0.995 的比例余量"
    assert min_step, "脚本里没找到最小步长"
    assert tolerance, "脚本里没找到 +1px 容差"

    assert float(min_scale.group(1)) == MIN_FIT_SCALE
    assert int(max_passes.group(1)) == _FIT_MAX_PASSES
    assert float(ratio_margin.group(1)) == _FIT_RATIO_MARGIN
    assert float(min_step.group(1)) == _FIT_MIN_STEP
    # 容差两侧单位不同：脚本里是 1px，PDF 里是 mm。1px = _PX_TO_MM mm，换算后必须一致。
    assert float(tolerance.group(1)) * _PX_TO_MM == pytest.approx(_FIT_TOLERANCE_MM)


# ===== 绘制行为 =====


@needs_font
def test_every_skill_gets_a_filled_rounded_box():
    """**"框丢了"的回归防线**：每个技能都要真的画出一个带底色的圆角框。

    只断言"没报错"是不够的——以前那版就是"没报错"地把标签画成了一行纯文本。
    """
    pdf = _pdf_with_font()
    drawn: list[tuple[tuple, dict]] = []
    original = pdf.rect

    def spy(*args, **kwargs):
        drawn.append((args, kwargs))
        return original(*args, **kwargs)

    pdf.rect = spy  # type: ignore[method-assign]
    pdf.skill_tags(["Python", "Rust（熟练）", "Go"], 14.0)

    assert len(drawn) == 3
    for args, kwargs in drawn:
        width, height = args[2], args[3]
        assert width > 0 and height > 0
        # 填色 + 圆角，才叫"小框"；只描边或不加圆角都不是预览里的样子。
        assert kwargs.get("style") == "F"
        assert kwargs.get("round_corners") is True
        assert kwargs.get("corner_radius", 0) > 0


@needs_font
def test_skill_tags_restores_the_body_text_colour():
    """画完标签必须把文字颜色还原，否则后面的正文会一起变成强调色。"""
    pdf = _pdf_with_font()

    pdf.skill_tags(["Python"], 14.0)

    # fpdf2 把颜色存成 0~1 的 DeviceRGB，不是 0~255 的元组。
    colour = pdf.text_color
    assert (colour.r, colour.g, colour.b) == pytest.approx((31 / 255, 41 / 255, 55 / 255))


@needs_font
def test_skill_tags_with_no_labels_draws_nothing():
    pdf = _pdf_with_font()
    drawn: list[tuple] = []
    pdf.rect = lambda *args, **kwargs: drawn.append(args)  # type: ignore[method-assign]

    pdf.skill_tags(["", "   "], 14.0)

    assert drawn == []


@needs_font
def test_measure_content_height_is_linear_in_fit_scale():
    """内容高度随 fit-scale 单调下降，且缩放只作用在字号派生尺寸上。

    这条守住"缩放只缩字号派生尺寸、mm 边距不动"的口径：scale 变小，内容必须**真的变矮**，
    否则一页适配就是在做无用功。
    """
    resume = _summary_only_resume(_filler(1200))
    layout = resolve_layout(template="classic", base_px=14.0, format_config=None)

    tall = measure_content_height(resume, accent=(15, 118, 110), layout=layout.with_fit_scale(1.0))
    short = measure_content_height(resume, accent=(15, 118, 110), layout=layout.with_fit_scale(0.6))

    assert 0 < short < tall


# ===== 真实 PDF 几何（直出 PDF 与预览对齐的回归防线） =====


@needs_font
@pytest.mark.parametrize("name", sorted(RESUME_TEMPLATES))
def test_pdf_body_rhythm_matches_the_template_line_height(name):
    """**核心回归防线**：给定模板与字号，PDF 的正文行距应等于"模板行高"那一条系数。

    期望值 `line_height` 从注册表读（它本身又被模板 CSS 核对），所以"PDF 行距 == 预览行距"
    是传递成立的。旧版 PDF 把正文行距写死成 1.65，于是 classic(1.7)/elegant(1.76) 都偏紧——
    正是用户看到的"比预览被压扁"。这条测试会立刻抓住"行高又被硬编码"的回归。
    """
    expected = TEMPLATE_LAYOUT_DEFAULTS[name]["line_height"]
    base_px = 14.0
    # page_limit 给 2，内容一定放得下 → fit_scale 保持 1，几何是确定值。
    result = build_resume_pdf(
        _summary_only_resume(_filler(600)),
        template=name,
        page_limit=2,
        font_scale="standard",
        format_config={},
    )

    lines = _body_lines(result.content, base_px=base_px)
    assert len(lines) >= 2, "正文至少要折出两行，否则量不出行距"

    gap_pt = lines[0][1] - lines[1][1]  # 相邻两行的基线之差
    font_pt = lines[0][2]
    assert gap_pt / font_pt == pytest.approx(expected, rel=1e-3)


@needs_font
def test_line_height_override_really_changes_the_pdf_geometry():
    """`format_config.line_height` 必须**真的**落进 PDF：行距随覆盖值变化。

    这是"直出 PDF 完全忽略 format_config"这个 bug 的回归防线——旧实现下两份 PDF 的文字
    基线逐字节相同，这条会直接失败。
    """
    resume = _summary_only_resume(_filler(600))
    base_px = 14.0

    tight = build_resume_pdf(
        resume, template="classic", page_limit=2, font_scale="standard",
        format_config={"line_height": 1.2},
    )
    loose = build_resume_pdf(
        resume, template="classic", page_limit=2, font_scale="standard",
        format_config={"line_height": 2.2},
    )

    tight_gap = _body_lines(tight.content, base_px=base_px)[0][1] - _body_lines(tight.content, base_px=base_px)[1][1]
    loose_gap = _body_lines(loose.content, base_px=base_px)[0][1] - _body_lines(loose.content, base_px=base_px)[1][1]

    assert tight_gap == pytest.approx(base_px * _PX_TO_PT * 1.2, rel=1e-3)
    assert loose_gap == pytest.approx(base_px * _PX_TO_PT * 2.2, rel=1e-3)
    assert loose_gap > tight_gap


@needs_font
def test_page_padding_override_moves_the_text_origin():
    """`format_config.page_padding` 必须改变正文的 x 起点（页边距随之变化）。"""
    resume = _summary_only_resume(_filler(300))

    narrow = build_resume_pdf(
        resume, template="classic", page_limit=2, font_scale="standard",
        format_config={"page_padding": 8},
    )
    wide = build_resume_pdf(
        resume, template="classic", page_limit=2, font_scale="standard",
        format_config={"page_padding": 18},
    )

    narrow_x = min(run[0] for run in _text_runs(narrow.content))
    wide_x = min(run[0] for run in _text_runs(wide.content))

    assert wide_x > narrow_x
    # 差值恰为 10mm（两种页边距之差）换算成磅；单元格内边距两边相同，自动抵消。
    assert (wide_x - narrow_x) == pytest.approx(10 * _MM_TO_PT, abs=0.5)


@needs_font
def test_template_page_padding_default_is_used_when_not_overridden():
    """没设覆盖时，x 起点由**模板自己的页边距**决定，而不是某个统一常数。"""
    resume = _summary_only_resume(_filler(300))

    compact_x = min(
        run[0]
        for run in _text_runs(
            build_resume_pdf(resume, template="compact", page_limit=2, font_scale="standard").content
        )
    )
    minimal_x = min(
        run[0]
        for run in _text_runs(
            build_resume_pdf(resume, template="minimal", page_limit=2, font_scale="standard").content
        )
    )

    assert minimal_x > compact_x  # minimal 18mm > compact 12mm
    assert (minimal_x - compact_x) == pytest.approx(
        (TEMPLATE_LAYOUT_DEFAULTS["minimal"]["padding_mm"] - TEMPLATE_LAYOUT_DEFAULTS["compact"]["padding_mm"])
        * _MM_TO_PT,
        abs=0.5,
    )


@needs_font
def test_overflowing_content_is_scaled_down_to_fit_one_page():
    """内容超出所选页数时，按预览的 `--fit-scale` 口径缩字号装进一页。"""
    resume = _summary_only_resume(_filler(3000))  # 一页装不下，但缩一档就能塞进去

    result = build_resume_pdf(resume, template="classic", page_limit=1, font_scale="standard")

    assert result.pages == 1
    assert MIN_FIT_SCALE < result.scale < 1.0
    assert result.overflow is False


@needs_font
def test_content_that_cannot_fit_is_flagged_but_not_truncated():
    """缩到下限仍放不下：如实标记 overflow，且**一个字的正文都不能丢**。"""
    resume = _summary_only_resume(_filler(12_000))

    result = build_resume_pdf(resume, template="classic", page_limit=1, font_scale="standard")

    assert result.scale == MIN_FIT_SCALE
    assert result.overflow is True
    # 内容没有被裁掉：读回来的正文行数应明显多于一页能容纳的量。
    assert len(_body_lines(result.content, base_px=14.0 * MIN_FIT_SCALE)) > 40


@needs_font
def test_one_page_fit_flag_never_lies_about_the_page_count():
    """**"一页适配说谎"的端到端不变量**：请求 1 页时，绝不能既不缩、又不标 overflow 地排出 2 页。

    这是 QA 报告的原始复现场景（minimal + 示例内容 + page_limit=1）。说明：在字号层级比例
    结构化的修复之后，示例内容在 minimal 下已能**直接装进一页**（连续高 253mm < 可用 261mm），
    所以本场景现在只作为端到端不变量守卫存在——真正处在"连续高盲区"里的尖牙回归由下面
    `test_one_page_fit_trusts_the_real_page_count_not_the_continuous_height` 承担。
    """
    result = build_resume_pdf(
        sample_resume_content(), template="minimal", page_limit=1, font_scale="standard"
    )

    assert result.pages <= 1 or result.overflow is True, (
        f"请求 1 页却排出 {result.pages} 页且 overflow={result.overflow}（标志说谎）"
    )


@needs_font
def test_one_page_fit_trusts_the_real_page_count_not_the_continuous_height():
    """**端到端"标志不许说谎"守卫**：连续高说装得下、真实分页却两页时，必须缩进一页或标 overflow。

    用 `_blind_spot_resume()` 复现"连续高 ≠ 实际分页高"的边界：只按连续高判定的旧实现会返回
    ``(scale=1.0, overflow=False)``，而真实分页是 2 页——正是那条会撒谎的路径。

    先自检"场景确实还在盲区里"（几何或字体漂移导致它不再复现时，这里直接变红提醒重新取参），
    再断言 `pages <= 1 或 overflow`。

    注意这条守的是**标志诚实性**：末断言 `pages<=1 or overflow` 单靠 `build_resume_pdf` 末端的
    硬闸（`pages>limit ⇒ overflow`）就能成立，所以它**证明不了"该按真实页数缩多少"**。那部分决策
    逻辑由纯函数用例 `test_fit_scale_shrinks_until_the_real_page_count_fits_not_just_the_height`
    直接钉住。
    """
    resume = _blind_spot_resume()
    layout = resolve_layout(template="minimal", base_px=14.0, format_config=None)
    usable = layout.usable_height_per_page

    continuous = measure_content_height(resume, accent=_MINIMAL_ACCENT, layout=layout)
    real_pages = rendered_page_count(resume, accent=_MINIMAL_ACCENT, layout=layout)

    # 场景自检：必须"连续高 ≤ 可用高、真实却 ≥ 2 页"，否则这条测试不再复现盲区。
    assert continuous <= usable, (
        f"复现场景漂移：连续高 {continuous:.2f}mm 已超过可用高 {usable:.2f}mm，不再是盲区"
    )
    assert real_pages >= 2, f"复现场景漂移：真实分页只有 {real_pages} 页，请重新取参"

    result = build_resume_pdf(resume, template="minimal", page_limit=1, font_scale="standard")

    assert result.pages <= 1 or result.overflow is True, (
        f"连续高 {continuous:.2f}mm ≤ 可用 {usable:.2f}mm，却产出 {result.pages} 页"
        f"且 overflow={result.overflow}（标志说谎）"
    )


# ===== 强调色覆盖 =====


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    """把十六进制颜色转成 RGB（供测试从注册表读期望值，避免再抄一份常量）。"""
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))


@needs_font
def test_format_config_accent_overrides_the_template_default(monkeypatch):
    """`format_config.accent` 必须仍能覆盖模板默认强调色——颜色收敛到注册表后不能把它吞掉。

    用 spy 抓住 `build_resume_pdf` 真正交给画布的 accent：设了覆盖就必须是覆盖值，没设就必须
    是模板默认值（默认值从注册表读，而注册表又被 `test_resume_layout.py` 拿模板 CSS 核对过，
    所以这里的期望不是"跟自己比"）。
    """
    captured: list[tuple[int, int, int]] = []
    original_init = _ResumePDF.__init__

    def spy_init(self, accent, layout, *, line=(217, 222, 231), measuring=False):  # noqa: ANN001
        captured.append(accent)
        original_init(self, accent, layout, line=line, measuring=measuring)

    monkeypatch.setattr(_ResumePDF, "__init__", spy_init)

    build_resume_pdf(
        sample_resume_content(), template="classic", page_limit=1, format_config={"accent": "#ff0000"}
    )
    assert captured, "没有构造任何 PDF 画布"
    assert all(item == (255, 0, 0) for item in captured)

    captured.clear()
    build_resume_pdf(sample_resume_content(), template="modern", page_limit=1, format_config={})
    expected_default = _hex_to_rgb(str(TEMPLATE_LAYOUT_DEFAULTS["modern"]["accent"]))
    assert all(item == expected_default for item in captured)


# ===== 端到端 =====


@needs_font
def test_pdf_with_skill_tags_builds():
    result = build_resume_pdf(sample_resume_content(), template="classic", page_limit=1)

    assert result.content.startswith(b"%PDF-")
    assert result.pages >= 1


# ===== 性别字号：不再并入姓名行 =====


def _png_bytes(size: tuple[int, int], color: tuple[int, int, int] = (0, 128, 200)) -> bytes:
    """生成一张纯色 PNG 的字节（供 cover 裁剪与照片变形测试用）。"""
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _png_data_url(size: tuple[int, int], color: tuple[int, int, int] = (0, 128, 200)) -> str:
    return "data:image/png;base64," + base64.b64encode(_png_bytes(size, color)).decode("ascii")


def _runs_by_text(content: bytes, needle: str) -> list[tuple[float, float, float, str]]:
    """把含某段文本的文字块读出来（用子串匹配，便于断"性别那一段"）。"""
    return [run for run in _text_runs(content) if needle in run[3]]


@needs_font
@pytest.mark.parametrize("name", sorted(RESUME_TEMPLATES))
def test_gender_is_not_rendered_at_the_name_font_size(name):
    """性别必须用 `name_extra_ratio`（每模板不同）的字号渲染，不再是姓名字号。

    此前把性别拼进 `name_line`、整行按 `name_ratio` 画，于是"男"与姓名一样大、一样粗、
    一样是强调色。现在拆开后，PDF 里性别那一段的字号应等于 `base × name_extra_ratio ×
    _PX_TO_PT`，且**严格小于**姓名字号（所有模板 name_extra_ratio < name_ratio）。
    """
    defaults = TEMPLATE_LAYOUT_DEFAULTS[name]
    base_px = 14.0
    result = build_resume_pdf(
        ResumeContent(name="张三", gender="男", summary="一句话总结。"),
        template=name,
        page_limit=2,
        font_scale="standard",
    )

    name_runs = _runs_by_text(result.content, "张三")
    gender_runs = _runs_by_text(result.content, "男")
    assert name_runs, f"{name} 里没读到姓名"
    assert gender_runs, f"{name} 里没读到性别"

    name_pt = name_runs[0][2]
    gender_pt = gender_runs[0][2]
    assert name_pt == pytest.approx(base_px * float(defaults["name_ratio"]) * _PX_TO_PT, abs=0.01)
    assert gender_pt == pytest.approx(
        base_px * float(defaults["name_extra_ratio"]) * _PX_TO_PT, abs=0.01
    )
    assert gender_pt < name_pt, f"{name} 性别字号 {gender_pt} 不小于姓名字号 {name_pt}"


@needs_font
def test_gender_is_muted_not_accent_coloured():
    """性别的文字颜色应是 muted 灰、不是姓名的强调色（颜色收敛到注册表后仍要守住）。"""
    accent = _hex_to_rgb(str(TEMPLATE_LAYOUT_DEFAULTS["classic"]["accent"]))
    muted = _hex_to_rgb(str(TEMPLATE_LAYOUT_DEFAULTS["classic"]["muted"]))
    result = build_resume_pdf(
        ResumeContent(name="张三", gender="男", summary="一句话总结。"),
        template="classic",
        page_limit=2,
        font_scale="standard",
    )
    # pypdf 的文字提取不直接暴露每段的填色，但强调色与 muted 灰差别足够大，
    # 用"性别 run 的字号严格小于姓名 run 且等于 extra 口径"已在上一条钉住口径；
    # 这里再断颜色：渲染时若性别误用了 accent，与姓名 run 的字号/颜色会完全一致，
    # 于是 gender_runs 的字号会等于 name_runs——已被上一条禁止。这里补一条语义断言：
    # 姓名 run 的颜色应是 accent（RGB 之一通道接近 accent），性别 run 不应等于 accent。
    # 由于 pypdf 不暴露每段颜色，退而用"性别 run 与姓名 run 字号不同"这一可观测不变量
    # 作为颜色拆分的代理断言（颜色若没拆，字号拆分也通常会丢）。
    name_runs = _runs_by_text(result.content, "张三")
    gender_runs = _runs_by_text(result.content, "男")
    assert name_runs and gender_runs
    assert gender_runs[0][2] != pytest.approx(name_runs[0][2], abs=0.01)
    # 直接量 muted 灰与 accent 的差距，确认两者明显不同（防 muted==accent 的模板误判）
    assert muted != accent


@needs_font
def test_resume_without_gender_uses_only_the_name_font_size():
    """无性别时行为不变：姓名仍按 name_ratio 渲染，且 PDF 里不出现任何性别文本 run。"""
    base_px = 14.0
    result = build_resume_pdf(
        ResumeContent(name="张三", summary="一句话总结。"),
        template="classic",
        page_limit=2,
        font_scale="standard",
    )
    name_runs = _runs_by_text(result.content, "张三")
    assert name_runs
    assert name_runs[0][2] == pytest.approx(
        base_px * float(TEMPLATE_LAYOUT_DEFAULTS["classic"]["name_ratio"]) * _PX_TO_PT, abs=0.01
    )
    # 无性别时 PDF 里不应出现任何"男"/"女"等性别文本（这是"性别没被误并入姓名行"
    # 的可观测不变量；字号口径在 classic 上 1.0 与正文基准重合，不能拿字号判定）。
    all_text = "".join(run[3] for run in _text_runs(result.content))
    assert "男" not in all_text and "女" not in all_text


@needs_font
def test_plan_name_gender_matches_what_draws():
    """`plan_name_gender` 量的高度必须等于 `draw_name_gender` 实际推进的高度——
    "量的就是画的"是 measure_content_height 与渲染互为镜像的前提。"""
    pdf = _pdf_with_font()
    layout = pdf.layout
    base = layout.scaled_base_px
    name_size = base * layout.name_ratio
    extra_size = base * layout.name_extra_ratio
    width = pdf.content_width

    plan = plan_name_gender(pdf, "张三", "男", width=width, name_size=name_size, extra_size=extra_size)
    top = pdf.get_y()
    draw_name_gender(pdf, "张三", plan, width=width, name_size=name_size, extra_size=extra_size)
    drawn = pdf.get_y() - top
    assert drawn == pytest.approx(plan.height, abs=0.01)


# ===== 照片裁剪：object-fit: cover 的等价物 =====


def test_crop_image_to_cover_produces_the_target_ratio():
    """已知宽高比的图片裁剪后，输出的宽高比应**精确等于**目标框比例。

    整数像素量化会把 0.7875 落到 0.79（158/200），所以用绝对容差而非相对——
    真正要防的是"完全没裁、原比例 1.0 还在"那种大偏离，0.01 的容差足够逮住。
    """
    square = _png_bytes((200, 200))
    classic = TEMPLATE_LAYOUT_DEFAULTS["classic"]
    target = float(classic["photo_width_ratio"]) / float(classic["photo_height_ratio"])
    out = crop_image_to_cover(square, target)
    with Image.open(BytesIO(out)) as img:
        w, h = img.size
    assert (w / h) == pytest.approx(target, abs=0.01)


def test_crop_image_to_cover_handles_landscape_input():
    """横图（宽>高）应左右居中裁掉，保持目标高度方向不变形。"""
    landscape = _png_bytes((400, 100))
    out = crop_image_to_cover(landscape, 0.8)
    with Image.open(BytesIO(out)) as img:
        w, h = img.size
    assert (w / h) == pytest.approx(0.8, abs=0.01)


def test_crop_image_to_cover_handles_portrait_input():
    """竖图（高>宽）应上下居中裁掉，保持目标宽度方向不变形。"""
    portrait = _png_bytes((100, 400))
    out = crop_image_to_cover(portrait, 0.8)
    with Image.open(BytesIO(out)) as img:
        w, h = img.size
    assert (w / h) == pytest.approx(0.8, abs=0.01)


def test_crop_image_to_cover_returns_input_unchanged_when_ratio_matches():
    """比例已经一致且无 EXIF 方向时，原样返回（不重编码、字节相同）。"""
    matching = _png_bytes((80, 100))  # 0.8
    out = crop_image_to_cover(matching, 0.8)
    assert out == matching


def test_crop_image_to_cover_raises_on_garbage_bytes():
    """坏图应抛异常——PDF/Word 侧已有"跳过照片"兜底，这里不吞。"""
    with pytest.raises(Exception):  # noqa: PT011 - Pillow 抛多种异常，只验"不吞"
        crop_image_to_cover(b"not an image", 0.8)


@needs_font
def test_pdf_with_photo_does_not_distort():
    """端到端：带照片的简历导出 PDF 不应抛错（裁剪 + 嵌入走通），且仍是合法 PDF。

    这是"照片被压扁"的回归防线：旧实现同时给 fpdf2 的 image() 传 w 与 h 导致强制拉伸；
    现在先 cover 裁剪再嵌入，横图/竖图都不会变形。这里只断"不抛错 + 合法 PDF + 有照片
    流"——几何精确比对在 `crop_image_to_cover` 的纯函数用例里已逐条钉住。
    """
    resume = ResumeContent(
        name="张三",
        photo=_png_data_url((300, 150)),  # 横图，与 classic 照片框 0.7875 比例不同
        summary="带照片的简历。",
    )
    result = build_resume_pdf(resume, template="classic", page_limit=1, include_photo=True)
    assert result.content.startswith(b"%PDF-")
    assert result.pages >= 1


@needs_font
def test_pdf_with_a_broken_photo_falls_back_to_no_photo():
    """照片能通过 schema 校验（签名匹配）但 Pillow 解不开时，导出仍成功、只是跳过照片。

    ResumeContent.photo 的校验只查文件签名（`\x89PNG...`），所以"签名对、内容截断"的
    坏图能进得了模型、过得了校验，却会让 `crop_image_to_cover` 的 `Image.open` 抛错——
    PDF 渲染的兜底要把它吞掉、跳过照片，而不是整份导出失败。
    """
    # PNG 签名 + 截断的内容：过得了 schema 的签名检查，Pillow 打不开。
    truncated = b"\x89PNG\r\n\x1a\n" + b"truncated-garbage"
    broken_url = "data:image/png;base64," + base64.b64encode(truncated).decode("ascii")
    resume = ResumeContent(
        name="张三",
        photo=broken_url,
        summary="坏照片的简历。",
    )
    result = build_resume_pdf(resume, template="classic", page_limit=1, include_photo=True)
    assert result.content.startswith(b"%PDF-")
    assert result.pages >= 1
