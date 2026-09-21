"""简历版面诊断与「自动一页」的规则。

**为什么这些规则放在后端**：它们纯是判断（多少算满、先动哪个旋钮、字号缩到哪为止），
放这里能被 pytest 逐个钉住，也能让界面、助手和导出共用同一份结论。前端只做两件它
才有能力做的事——**在真实浏览器里量出高度**、**把选中的方案应用上去**。

**测量为什么必须在浏览器里做**：版面只有真正排版之后才存在。后端既没有浏览器，
也不该为了量一个高度去引一个无头浏览器依赖。

两条容易踩错的约定：

- **溢出不能用 ``scrollHeight`` 判断**。``scrollHeight`` 会把 ``padding`` 之外的空白
  一起算进去，量出来的"内容高度"偏大；要拿"固定页高 − 上下 padding"作为可用高度，
  再比最后一个可见元素的底边。
- **字号下限按绝对像素算，不按比例算**。档位本身有大小（小字号 12px、标准 14px），
  同一个比例系数在两者上的结果差很多：标准档乘 0.88 还有 12.3px，小字号档乘 0.88
  就只剩 10.6px 了。所以下限是"不低于 12px（≈9pt）"，换算成系数时要除以基准字号。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .resume_templates import (
    format_css,
    font_scale_spec,
    template_layout_defaults,
)

# ===== 版面健康区间 =====
# 单页：低于 82% 显得空，高于 96% 显得挤。
FILL_SPARSE = 0.82
FILL_DENSE = 0.96
# 明显太空：这时候该说的是"补内容或减少页数"，而不是"调间距"。
FILL_TOO_SPARSE = 0.60
# 多页时末页的底线：低于它说明最后一张几乎是空的，应该把内容前移。
LAST_PAGE_MIN_FILL = 0.70

# ===== 收紧用的下限（自动一页最多收这么多，再往下就不像是"同一份简历"了）=====
MIN_PADDING_MM = 12.0
MIN_LINE_HEIGHT = 1.4
MIN_SECTION_GAP = 0.8
# 正文字号不低于 12px（≈9pt）。低于这个数打印出来会明显吃力。
MIN_FONT_PX = 12.0

_PADDING_STEP_MM = 2.0
_SECTION_GAP_STEP = 0.25
_LINE_HEIGHT_STEP = 0.15
_FONT_STEP = 0.02

# 版面结论
STATUS_OVERFLOW = "overflow"
STATUS_DENSE = "dense"
STATUS_HEALTHY = "healthy"
STATUS_SPARSE = "sparse"
STATUS_TOO_SPARSE = "too_sparse"
STATUS_UNKNOWN = "unknown"

STATUS_LABELS = {
    STATUS_OVERFLOW: "超出所选页数",
    STATUS_DENSE: "偏满",
    STATUS_HEALTHY: "合适",
    STATUS_SPARSE: "偏空",
    STATUS_TOO_SPARSE: "明显太空",
    STATUS_UNKNOWN: "无法测量",
}

# 建议的类别。顺序就是界面上的展示顺序，也是"先改哪个"的优先级。
SUGGESTION_RESTRUCTURE = "restructure"
SUGGESTION_STRUCTURE = "structure"
SUGGESTION_SPACING = "spacing"
SUGGESTION_FONT = "font"
SUGGESTION_EXTEND = "extend"
SUGGESTION_CONTENT = "content"


@dataclass
class PageMeasure:
    """一页的实测填充度。``fill`` 是「正文占用高度 ÷ 该页可用高度」，可以大于 1。"""

    page: int
    fill: float


@dataclass
class Suggestion:
    kind: str
    title: str
    detail: str


@dataclass
class Diagnosis:
    status: str
    status_label: str
    # 整体填充度（正文总高 ÷ 总可用高），用于界面上的百分比读数。
    fill: float
    # 按内容量算出来需要几页；比所选页数大就说明塞不下。
    pages_needed: int
    page_limit: int
    pages: list[PageMeasure] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)
    # 一句话结论，界面直接显示。
    summary: str = ""


def _round(value: float, digits: int = 3) -> float:
    return round(value + 0.0, digits)


def derive_pages(
    used_height: float, page_content_height: float, page_limit: int
) -> tuple[list[PageMeasure], int, float]:
    """把"内容总高"换算成逐页填充度、所需页数与整体填充度。

    这是纯算术，所以完整地测：客户端的职责只是把两个高度量准，剩下的换算全在这里。
    """
    if page_content_height <= 0 or page_limit < 1:
        return [], 0, 0.0

    capacity = page_content_height * page_limit
    # 至少算一页：内容为空时若算出 0 页，界面上会显示成"0 页"。
    pages_needed = max(1, int(-(-used_height // page_content_height)))

    pages: list[PageMeasure] = []
    remaining = used_height
    for index in range(1, pages_needed + 1):
        fill = min(1.0, remaining / page_content_height)
        pages.append(PageMeasure(page=index, fill=_round(max(0.0, fill))))
        remaining -= page_content_height

    return pages, pages_needed, _round(max(0.0, used_height / capacity))


def diagnose(
    *,
    used_height: float,
    page_content_height: float,
    page_limit: int,
    has_fit_room: bool = True,
) -> Diagnosis:
    """给出一份版面诊断。

    ``has_fit_room`` 为假表示版式已经没有可收紧的余地了，此时不应再建议"自动一页"。
    """
    if page_content_height <= 0 or page_limit < 1:
        return Diagnosis(
            status=STATUS_UNKNOWN,
            status_label=STATUS_LABELS[STATUS_UNKNOWN],
            fill=0.0,
            pages_needed=0,
            page_limit=max(1, page_limit),
            summary="没能量到版面尺寸，无法给出诊断。",
        )

    pages, pages_needed, fill = derive_pages(used_height, page_content_height, page_limit)
    last_page_fill = pages[-1].fill if pages else 0.0

    if pages_needed > page_limit:
        status = STATUS_OVERFLOW
    elif page_limit == 1:
        if fill < FILL_TOO_SPARSE:
            status = STATUS_TOO_SPARSE
        elif fill < FILL_SPARSE:
            status = STATUS_SPARSE
        elif fill > FILL_DENSE:
            status = STATUS_DENSE
        else:
            status = STATUS_HEALTHY
    else:
        # 多页：末页太空是最常见的问题（第一页塞满、第二页只有两行）。
        if last_page_fill < LAST_PAGE_MIN_FILL:
            status = STATUS_SPARSE
        elif fill > FILL_DENSE:
            status = STATUS_DENSE
        else:
            status = STATUS_HEALTHY

    suggestions = _suggestions(
        status=status,
        fill=fill,
        last_page_fill=last_page_fill,
        pages_needed=pages_needed,
        page_limit=page_limit,
        has_fit_room=has_fit_room,
    )
    return Diagnosis(
        status=status,
        status_label=STATUS_LABELS[status],
        fill=fill,
        pages_needed=pages_needed,
        page_limit=page_limit,
        pages=pages,
        suggestions=suggestions,
        summary=_summary(status, fill, last_page_fill, pages_needed, page_limit),
    )


def _percent(value: float) -> str:
    return f"{round(value * 100)}%"


def _summary(
    status: str, fill: float, last_page_fill: float, pages_needed: int, page_limit: int
) -> str:
    if status == STATUS_OVERFLOW:
        return (
            f"内容按当前版式需要 {pages_needed} 页，超过所选的 {page_limit} 页。"
            "可以先试试自动一页，它会按「间距 → 行高 → 字号」的顺序收紧。"
        )
    if status == STATUS_DENSE:
        return f"正文占了 {_percent(fill)}，已经接近页面上限；再添两行就会溢出去。"
    if status == STATUS_SPARSE and page_limit > 1:
        return (
            f"末页只占了 {_percent(last_page_fill)}，明显偏空。"
            "把内容往前挪、或减到更少的页数会更好看。"
        )
    if status == STATUS_SPARSE:
        return f"正文占了 {_percent(fill)}，页面下方还空着一块。"
    if status == STATUS_TOO_SPARSE:
        return f"正文只占了 {_percent(fill)}，看起来会比较单薄。"
    return f"正文占了 {_percent(fill)}，版面合适。"


def _suggestions(
    *,
    status: str,
    fill: float,
    last_page_fill: float,
    pages_needed: int,
    page_limit: int,
    has_fit_room: bool,
) -> list[Suggestion]:
    """按固定顺序给建议：重排 → 结构 → 间距/字号 → 扩页。

    **顺序本身就是规则的一部分**。先让人调间距、调不好再让人删内容，等于让人白改一轮；
    反过来先说"精简内容"，用户又可能删掉本来放得下的经历。所以只有前面几步都不够时才
    往下一步。
    """
    items: list[Suggestion] = []

    if status == STATUS_OVERFLOW:
        # ① 重排：不删东西、也不改版式，只是把顺序调一下。
        items.append(
            Suggestion(
                SUGGESTION_RESTRUCTURE,
                "先看能不能靠重排放下",
                "把最强、最相关的经历提到前面，同类的技能与奖项合并成一行，"
                "删掉重复的背景描述——通常这一轮就能省下一段的高度。",
            )
        )
        # ② 结构：不用调参数就能拿到的空间。
        items.append(
            Suggestion(
                SUGGESTION_STRUCTURE,
                "检查结构上有没有浪费",
                "确认没有多余的空标题、没有只占一行的独立区块。"
                "次要经历可以压成一行摘要，不必和主项目平均分配篇幅。",
            )
        )
        # ③ 间距 / 字号：这就是自动一页做的事，所以只在还有收紧余地时提。
        if has_fit_room:
            items.append(
                Suggestion(
                    SUGGESTION_SPACING,
                    "用「自动一页」收紧版式",
                    "按「页边距 → 区块间距 → 行高 → 字号」的顺序一项项试，"
                    "每试一项量一次，够放下就停——不会一次把字缩到很小。"
                    f"字号最多缩到 {MIN_FONT_PX:g}px（≈9pt）为止。",
                )
            )
        else:
            items.append(
                Suggestion(
                    SUGGESTION_FONT,
                    "版式已经收到最紧了",
                    "页边距、行高、字号都已经到下限量，再收会影响可读性。"
                    "接下来只能精简内容或增加页数。",
                )
            )
        # ④ 精简内容
        items.append(
            Suggestion(
                SUGGESTION_CONTENT,
                "精简内容（最后一招）",
                "删掉那些占了一行、但面试官不会追问的要点。"
                "宁可留三条扎实的，也不要写六条凑数的。",
            )
        )
        # ⑤ 扩页：明确说明代价。
        if page_limit < 3:
            items.append(
                Suggestion(
                    SUGGESTION_EXTEND,
                    "增加页数",
                    "最省事，但要确认内容值得多出一页——"
                    "一整页里只有两行是常见事故，校招简历通常一到两页最稳妥。",
                )
            )
        return items

    if status == STATUS_DENSE:
        items.append(
            Suggestion(
                SUGGESTION_RESTRUCTURE,
                "留一点余量",
                "现在只剩不到 4% 的余量，改两个字就可能溢出一行。"
                "要么把某条要点压短一点，要么先收紧行高腾出空间。",
            )
        )
        if has_fit_room:
            items.append(
                Suggestion(
                    SUGGESTION_SPACING,
                    "想更稳就先收一点",
                    "用「自动一页」收一档，页面会松快一点，也免得之后手改内容时突然溢出。",
                )
            )
        return items

    if status in (STATUS_SPARSE, STATUS_TOO_SPARSE):
        if page_limit > 1:
            if pages_needed < page_limit:
                items.append(
                    Suggestion(
                        SUGGESTION_EXTEND,
                        f"页数可以减少到 {pages_needed} 页",
                        "按当前内容量用不了这么多页。把页数调小会顺带把版式放大，"
                        "看起来更充实，也不会留出一整页空白。",
                    )
                )
            else:
                # 末页空、但页数已经压到刚好装下：这时唯一的办法是把内容再压一点，
                # 所以直接算出"还要压掉多少"——「精简一下」这种说法等于没说。
                capacity_used = fill * page_limit
                shrink = (
                    max(0.0, 1 - (pages_needed - 1) / capacity_used)
                    if capacity_used > 0
                    else 0.0
                )
                items.append(
                    Suggestion(
                        SUGGESTION_RESTRUCTURE,
                        "把内容压进一页会更利落",
                        f"末页只占了 {_percent(last_page_fill)}。"
                        f"整体再减少约 {_percent(shrink)} 的内容就能收进 {pages_needed - 1} 页——"
                        "通常合并同类项、删掉不会被追问的要点就够了。",
                    )
                )
        items.append(
            Suggestion(
                SUGGESTION_CONTENT,
                "把空间用起来",
                "补上还没写进去的经历或项目；如果确实写满了，"
                "可以调大字号或行高让版面更舒展——空着大半页反而显得准备不足。",
            )
        )
        items.append(
            Suggestion(
                SUGGESTION_STRUCTURE,
                "检查是不是筛得太狠",
                "如果生成时选的岗位太窄，很多经历会被筛掉。"
                "换一份「通用简历」或不特意筛，往往就能把版面填起来。",
            )
        )
        return items

    if status == STATUS_HEALTHY:
        items.append(
            Suggestion(
                SUGGESTION_RESTRUCTURE,
                f"占用 {_percent(fill)}，保持即可",
                "这个区间既不留大片空白，也不显得拥挤，直接导出就好。",
            )
        )
    return items


# ===== 自动一页 =====


def _effective_layout(template: str, format_config: dict | None) -> dict[str, float]:
    """把"模板默认值 + 用户已设的覆盖"合成一组当前生效的版式值。

    自动一页只会**在用户当前的基础上往紧收**，所以必须先知道当前是多少。
    """
    defaults = template_layout_defaults(template)
    config = format_config or {}
    padding = config.get("page_padding")
    line_height = config.get("line_height")
    section_gap = config.get("section_gap")
    font_adjust = config.get("font_scale_adjust")
    return {
        "page_padding": float(padding) if padding else float(defaults["padding_mm"]),
        "line_height": float(line_height) if line_height else float(defaults["line_height"]),
        "section_gap": float(section_gap) if section_gap else float(defaults["section_gap"]),
        # 没设过系数就等于 1（渲染时 base_px 不做任何缩放）。
        "font_scale_adjust": float(font_adjust) if font_adjust else 1.0,
    }


def font_adjust_floor(font_scale: str) -> float:
    """字号系数能小到多少：不低于 ``MIN_FONT_PX``，且不越过格式字段自身的下限。

    两种下限取更严的那个——档位大时是"12px"这条在管，档位小时是格式字段的 0.88 在管
    （小字号档 12px 已经等于下限，此时系数只能是 1）。
    """
    from .resume_templates import _format_field

    spec = font_scale_spec(font_scale)
    base_px = float(spec["base_px"])
    field = _format_field("font_scale_adjust") or {}
    field_min = float(field.get("min", 0.88))
    by_pixels = MIN_FONT_PX / base_px if base_px > 0 else 1.0
    return _round(max(field_min, min(1.0, by_pixels)), 3)


def _next_target(current: float, floor: float, step: float) -> float | None:
    """往紧收一档；已经到下限（或比下限还紧）就返回 None 表示这个旋钮没得收了。"""
    if current <= floor + 1e-9:
        return None
    return _round(max(floor, current - step), 3)


@dataclass
class FitCandidate:
    """一档候选版式：把它交给浏览器量一次，够放下就用它。"""

    key: str
    label: str
    # 这一档相对**原始**配置的完整覆盖（不是增量），直接存进简历的 format_config。
    config: dict[str, Any]
    # 量这一档时要注入预览的 CSS。**只用于测量**，不是最终渲染用的样式。
    css: str


def _font_scale_probe_css(font_scale: str, adjust: float) -> str:
    """把字号系数翻译成一段**只给预览探针用**的 CSS。

    字号系数在真正渲染时是由后端预先乘进 ``base_px`` 再交给模板的（见
    ``services/exporter.py``）——那是唯一对内置模板与用户自制模板都生效的路径，
    所以它**刻意没有** CSS 变量映射（有的话两者会叠乘）。

    但"自动一页"要在浏览器里逐档试，就必须让当前这一档真的作用到预览上。所以这里
    用**绝对像素**写一段等价样式覆盖 `--fs`：模板里所有尺寸都是
    `calc(var(--fs) * N)` 算出来的，改这一个变量就等于整份简历按这一档缩放。
    用绝对像素而不是再套一层变量，是因为探针注入的是最终样式，不该依赖任何尚未
    存在的变量。
    """
    base_px = float(font_scale_spec(font_scale)["base_px"])
    return f":root {{ --fs: {round(base_px * adjust, 2)}px; }}"


def build_fit_ladder(
    template: str, font_scale: str, format_config: dict | None
) -> list[FitCandidate]:
    """生成"自动一页"要依次尝试的版式清单。

    顺序是**页边距 → 区块间距 → 行高 → 字号**：越靠前的旋钮对可读性的影响越小。
    每一档都是相对原配置的**完整覆盖**，所以客户端试出哪一档就原样保存哪一档，
    不需要自己算增量。
    """
    current = _effective_layout(template, format_config)
    floor_adjust = font_adjust_floor(font_scale)
    # 保留用户已经调好的其它项（强调色、正文色等）——自动一页只该动版式，不该顺手
    # 把人选的颜色丢掉。四个版式旋钮先摘掉，下面由阶梯逐档重新写入。
    base = {
        key: value
        for key, value in (format_config or {}).items()
        if key not in {"page_padding", "line_height", "section_gap", "font_scale_adjust"}
    }

    ladder: list[FitCandidate] = []
    accumulated: dict[str, Any] = dict(base)

    def add(key: str, label: str, patch: dict[str, Any], probe_extra: str = "") -> None:
        accumulated.update(patch)
        config = dict(accumulated)
        css = format_css(config) + ("\n" + probe_extra if probe_extra else "")
        ladder.append(FitCandidate(key=key, label=label, config=config, css=css))

    padding = current["page_padding"]
    while True:
        target = _next_target(padding, MIN_PADDING_MM, _PADDING_STEP_MM)
        if target is None:
            break
        add("padding", f"页边距收到 {target:g}mm", {"page_padding": target})
        padding = target

    gap = current["section_gap"]
    while True:
        target = _next_target(gap, MIN_SECTION_GAP, _SECTION_GAP_STEP)
        if target is None:
            break
        add("section_gap", f"区块间距收到 {target:g}", {"section_gap": target})
        gap = target

    line_height = current["line_height"]
    while True:
        target = _next_target(line_height, MIN_LINE_HEIGHT, _LINE_HEIGHT_STEP)
        if target is None:
            break
        add("line_height", f"行高收到 {target:g}", {"line_height": target})
        line_height = target

    adjust = current["font_scale_adjust"]
    while True:
        target = _next_target(adjust, floor_adjust, _FONT_STEP)
        if target is None:
            break
        add(
            "font_scale_adjust",
            f"字号收到 {target:g} 倍",
            {"font_scale_adjust": target},
            # 字号在渲染时是预乘进 base_px 的，没有 CSS 变量可覆盖，所以探针要自己补一段。
            _font_scale_probe_css(font_scale, target),
        )
        adjust = target

    return ladder


def fit_room_report(template: str, font_scale: str, format_config: dict | None) -> dict[str, Any]:
    """还有没有可收紧的余地，以及下限说明。给界面用来决定要不要显示「自动一页」。"""
    ladder = build_fit_ladder(template, font_scale, format_config)
    adjust_floor = font_adjust_floor(font_scale)
    return {
        "has_room": bool(ladder),
        "steps": len(ladder),
        # 界面上要如实告诉用户字号最多缩到多少——不写清就等于让他按了才知道。
        "font_floor_px": MIN_FONT_PX,
        "font_adjust_floor": adjust_floor,
        "font_floor_note": (
            f"正文字号最多缩到 {MIN_FONT_PX:g}px（≈9pt），再小打印出来会吃力。"
            if adjust_floor < 1.0
            else "当前字号档位已经接近可读下限，自动一页不会再缩小字号。"
        ),
    }


__all__ = [
    "Diagnosis",
    "FILL_DENSE",
    "FILL_SPARSE",
    "FILL_TOO_SPARSE",
    "FitCandidate",
    "LAST_PAGE_MIN_FILL",
    "MIN_FONT_PX",
    "MIN_LINE_HEIGHT",
    "MIN_PADDING_MM",
    "MIN_SECTION_GAP",
    "PageMeasure",
    "STATUS_DENSE",
    "STATUS_HEALTHY",
    "STATUS_LABELS",
    "STATUS_OVERFLOW",
    "STATUS_SPARSE",
    "STATUS_TOO_SPARSE",
    "STATUS_UNKNOWN",
    "SUGGESTION_CONTENT",
    "SUGGESTION_EXTEND",
    "SUGGESTION_FONT",
    "SUGGESTION_RESTRUCTURE",
    "SUGGESTION_SPACING",
    "SUGGESTION_STRUCTURE",
    "Suggestion",
    "build_fit_ladder",
    "derive_pages",
    "diagnose",
    "fit_room_report",
    "font_adjust_floor",
]
