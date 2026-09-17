"""版面诊断与「自动一页」的规则。

这些规则决定"要不要让人改版式、先改哪一项、字号能缩到多小"，全是判断，所以逐条钉住。
最要紧的两条：

- **建议的顺序**：先让人调间距、调不好再让人删内容，等于让人白改一轮；反过来先说
  "精简内容"，用户又可能删掉本来放得下的经历。
- **字号下限按绝对像素算**：同一个系数在小字号档上会缩得更狠，只盯比例会让小字号档
  一路缩到 10px 以下。
"""
import re

import pytest

from app.services.resume_layout import (
    FILL_DENSE,
    FILL_SPARSE,
    MIN_FONT_PX,
    STATUS_DENSE,
    STATUS_HEALTHY,
    STATUS_OVERFLOW,
    STATUS_SPARSE,
    STATUS_TOO_SPARSE,
    STATUS_UNKNOWN,
    SUGGESTION_EXTEND,
    build_fit_ladder,
    derive_pages,
    diagnose,
    fit_room_report,
    font_adjust_floor,
)
from app.services.resume_templates import (
    RESUME_TEMPLATES,
    TEMPLATE_LAYOUT_DEFAULTS,
    TEMPLATES_DIR,
)

PAGE = 2600.0  # 一页正文可用高度，约等于 A4 去上下页边距后的像素值


# ===== 高度换算 =====


def test_derive_pages_single_page():
    pages, needed, fill = derive_pages(1300, PAGE, 1)
    assert needed == 1
    assert fill == 0.5
    assert [(p.page, p.fill) for p in pages] == [(1, 0.5)]


def test_derive_pages_exactly_full_is_one_page():
    pages, needed, fill = derive_pages(PAGE, PAGE, 1)
    assert needed == 1
    assert fill == 1.0
    assert len(pages) == 1


def test_derive_pages_overflow_by_a_hair_still_needs_a_second_page():
    """超一点点也算超——打印出来确实会多出一页，不该替用户粉饰。

    注意这里断言的是「需要第 2 页」而不是 fill > 1：fill 是给界面看的读数，
    四舍五入到三位小数后 1.0002 会显示成 1.0，**判断结论不能建立在它上面**。
    """
    pages, needed, _ = derive_pages(PAGE + 0.5, PAGE, 1)
    assert needed == 2
    assert len(pages) == 2


def test_derive_pages_multi_page_reports_the_last_page():
    pages, needed, _ = derive_pages(PAGE * 1.2, PAGE, 2)
    assert needed == 2
    assert pages[0].fill == 1.0
    assert pages[1].fill == pytest.approx(0.2)


def test_derive_pages_never_reports_zero_pages():
    pages, needed, fill = derive_pages(0, PAGE, 1)
    assert needed == 1
    assert fill == 0.0
    assert [(p.page, p.fill) for p in pages] == [(1, 0.0)]


def test_derive_pages_guards_against_a_zero_page_height():
    """页面高度量成 0（还没渲染完就量了）时不能除零，返回空结果让上层走「无法测量」。"""
    assert derive_pages(100, 0, 1) == ([], 0, 0.0)
    assert derive_pages(100, PAGE, 0) == ([], 0, 0.0)


# ===== 诊断 =====


@pytest.mark.parametrize(
    ("used", "expected"),
    [
        (PAGE * 0.50, STATUS_TOO_SPARSE),
        (PAGE * 0.70, STATUS_SPARSE),
        (PAGE * FILL_SPARSE, STATUS_HEALTHY),  # 正好在下边界上算健康
        (PAGE * 0.90, STATUS_HEALTHY),
        (PAGE * FILL_DENSE, STATUS_HEALTHY),  # 正好在上边界上也算健康
        (PAGE * 0.99, STATUS_DENSE),
        (PAGE * 1.05, STATUS_OVERFLOW),
    ],
)
def test_single_page_status_boundaries(used, expected):
    assert diagnose(used_height=used, page_content_height=PAGE, page_limit=1).status == expected


def test_multi_page_flags_an_empty_last_page():
    """第一页塞满、第二页只有两行——这是多页简历最常见的问题。"""
    result = diagnose(used_height=PAGE * 1.2, page_content_height=PAGE, page_limit=2)
    assert result.status == STATUS_SPARSE
    assert "末页" in result.summary
    # 报的是实测填充度，不是阈值——阈值写进文案等于让用户自己去对表格。
    assert "20%" in result.summary
    assert result.pages[-1].fill == pytest.approx(0.2, abs=0.01)


def test_multi_page_with_a_healthy_last_page_is_fine():
    result = diagnose(used_height=PAGE * 1.9, page_content_height=PAGE, page_limit=2)
    assert result.status == STATUS_HEALTHY


def test_unmeasurable_layout_is_reported_honestly():
    result = diagnose(used_height=100, page_content_height=0, page_limit=1)
    assert result.status == STATUS_UNKNOWN
    assert "无法" in result.summary


# ===== 建议顺序 =====


def test_overflow_suggestions_follow_the_documented_order():
    """重排 → 结构 → 间距/字号 → 精简内容 → 扩页。顺序本身就是规则。"""
    result = diagnose(used_height=PAGE * 1.4, page_content_height=PAGE, page_limit=1)
    kinds = [item.kind for item in result.suggestions]
    assert kinds == [
        "restructure",
        "structure",
        "spacing",
        "content",
        "extend",
    ]


def test_no_fit_room_changes_the_advice_instead_of_repeating_itself():
    """版式已经收到底时不该再让人「自动一页」——那是条死路。"""
    result = diagnose(
        used_height=PAGE * 1.4, page_content_height=PAGE, page_limit=1, has_fit_room=False
    )
    kinds = [item.kind for item in result.suggestions]
    assert "spacing" not in kinds
    assert "font" in kinds
    assert "已经到下限量" in " ".join(item.detail for item in result.suggestions)


def test_overflow_at_the_page_limit_does_not_offer_more_pages():
    """页数上限已经是 3 页时不该再说"增加页数"。"""
    result = diagnose(used_height=PAGE * 3.5, page_content_height=PAGE, page_limit=3)
    assert SUGGESTION_EXTEND not in [item.kind for item in result.suggestions]


def test_sparse_single_page_suggests_filling_not_shrinking():
    result = diagnose(used_height=PAGE * 0.5, page_content_height=PAGE, page_limit=1)
    kinds = [item.kind for item in result.suggestions]
    assert "content" in kinds
    assert "spacing" not in kinds
    assert "extend" not in kinds


def test_sparse_multi_page_suggests_reducing_the_page_count():
    result = diagnose(used_height=PAGE * 0.6, page_content_height=PAGE, page_limit=2)
    first = result.suggestions[0]
    assert first.kind == SUGGESTION_EXTEND
    # 内容本来一页就够，可以直接减页。
    assert "1 页" in first.title


def test_empty_last_page_with_no_spare_page_counts_how_much_to_cut():
    """末页空、但页数已经压到刚好装下时，要说清"还要压掉多少"，而不是「精简一下」。"""
    result = diagnose(used_height=PAGE * 1.19, page_content_height=PAGE, page_limit=2)
    assert result.status == STATUS_SPARSE
    first = result.suggestions[0]
    assert first.kind == "restructure"
    # 需要再压掉约 16%（1.19 页 -> 1 页）
    percent = re.search(r"约 (\d+)%", first.detail)
    assert percent is not None
    assert 12 <= int(percent.group(1)) <= 20


def test_healthy_layout_says_so_without_pushing_changes():
    result = diagnose(used_height=PAGE * 0.9, page_content_height=PAGE, page_limit=1)
    assert result.status == STATUS_HEALTHY
    assert len(result.suggestions) == 1
    assert "保持即可" in result.suggestions[0].title


# ===== 字号下限 =====


def test_font_floor_is_governed_by_absolute_pixels_not_ratio():
    """标准档乘 0.88 还有 12.3px，小字号档乘 0.88 就只剩 10.6px 了。"""
    base_px = {"small": 12.0, "standard": 14.0, "large": 15.5}
    for name, size in base_px.items():
        floor = font_adjust_floor(name)
        assert size * floor >= MIN_FONT_PX - 1e-9, name
    # 小字号档本身就等于下限，系数只能是 1——不允许再缩。
    assert font_adjust_floor("small") == 1.0
    # 其余档位受格式字段自身的 0.88 下限约束（比像素下限更严）。
    assert font_adjust_floor("standard") == 0.88
    assert font_adjust_floor("large") == 0.88


def test_font_floor_never_exceeds_one():
    for scale in ("small", "standard", "large", "不存在的档位"):
        assert font_adjust_floor(scale) <= 1.0


# ===== 收紧阶梯 =====


def test_ladder_order_is_padding_then_gap_then_line_height_then_font():
    """越靠前的旋钮对可读性的影响越小，所以先动它们。"""
    keys = [item.key for item in build_fit_ladder("minimal", "standard", {})]
    # 去掉连续重复后，顺序必须是这四类
    deduped = [key for index, key in enumerate(keys) if index == 0 or key != keys[index - 1]]
    assert deduped == ["padding", "section_gap", "line_height", "font_scale_adjust"]


def test_ladder_is_cumulative_and_only_ever_tightens():
    ladder = build_fit_ladder("classic", "standard", {})
    assert ladder, "经典模板默认 14mm 页边距，应当还有收紧余地"
    # 第一档只动页边距
    assert ladder[0].config["page_padding"] < 14
    # 之后每一档都建立在前一档之上：前面的旋钮一个都不能丢，重叠的键只会更紧、不会反弹。
    for previous, current in zip(ladder, ladder[1:]):
        assert set(previous.config) <= set(current.config)
        for key, value in previous.config.items():
            assert current.config[key] <= value, f"{key} 反弹了"
    # 末档：四个旋钮都到下限量
    last = ladder[-1].config
    assert last["page_padding"] == 12
    assert last["section_gap"] == 0.8
    assert last["line_height"] == 1.4
    assert last["font_scale_adjust"] == 0.88


def test_ladder_never_loosens_a_value_the_user_tightened():
    """用户已经把行高调到 1.3 了，自动一页不该把它放大回 1.4。"""
    ladder = build_fit_ladder("classic", "standard", {"line_height": 1.3})
    assert ladder
    for item in ladder:
        assert "line_height" not in item.config


def test_ladder_skips_knobs_already_at_the_floor():
    ladder = build_fit_ladder(
        "compact", "standard", {"page_padding": 12, "section_gap": 0.8, "line_height": 1.4}
    )
    keys = {item.key for item in ladder}
    assert keys == {"font_scale_adjust"}


def test_ladder_keeps_the_users_colours():
    """自动一页只该动版式，不该顺手把人选的强调色丢掉。"""
    ladder = build_fit_ladder("classic", "standard", {"accent": "#166534", "line_height": 1.6})
    assert ladder
    for item in ladder:
        assert item.config["accent"] == "#166534"


def test_ladder_is_empty_when_everything_is_at_the_floor():
    ladder = build_fit_ladder(
        "compact",
        "small",  # 小字号档的系数下限是 1
        {"page_padding": 12, "section_gap": 0.8, "line_height": 1.4},
    )
    assert ladder == []


def test_ladder_css_starts_from_the_shared_builder_then_adds_the_font_probe():
    """阶梯里的 css = 渲染同款 CSS + 一段只给探针用的字号覆盖。

    前半段必须复用 `format_css`（否则量出来的版式和真正渲染的不是一回事）；
    后半段只补字号——因为字号系数在渲染时是预乘进 `base_px` 的，没有 CSS 变量可覆盖。
    """
    from app.services.resume_templates import format_css

    ladder = build_fit_ladder("classic", "standard", {})
    last = ladder[-1]
    assert last.css.startswith(format_css(last.config))
    # 末档字号收到 0.88 → 标准档 14px × 0.88 = 12.32px，写成绝对的 --fs。
    assert "--fs: 12.32px;" in last.css


def test_font_probe_only_appears_on_the_font_rung():
    """前几档不该带字号覆盖：量的时候要如实反映"只收了间距/行高"的效果。"""
    ladder = build_fit_ladder("classic", "standard", {})
    for item in ladder:
        if item.key == "font_scale_adjust":
            assert "--fs:" in item.css
        else:
            assert "--fs:" not in item.css


def test_room_report_explains_the_font_floor():
    room = fit_room_report("minimal", "standard", {})
    assert room["has_room"] is True
    assert room["font_floor_px"] == MIN_FONT_PX
    assert "9pt" in room["font_floor_note"] or "12px" in room["font_floor_note"]

    tight = fit_room_report("compact", "small", {"page_padding": 12, "section_gap": 0.8, "line_height": 1.4})
    assert tight["has_room"] is False
    assert "不会再缩小字号" in tight["font_floor_note"]


# ===== 与模板文件的漂移守卫 =====


def test_template_layout_defaults_match_the_template_files():
    """`TEMPLATE_LAYOUT_DEFAULTS` 上的数字必须与模板 CSS 一致。

    自动一页靠它们判断「当前值是多少、还能往紧收多少」。抄错会让它收紧一个用户根本
    没设过的值，或者该收没收——而这两件事在界面上都看不出来，只会表现为"按了没反应"。
    """
    for name, spec in RESUME_TEMPLATES.items():
        css = (TEMPLATES_DIR / spec["file"]).read_text(encoding="utf-8")
        defaults = TEMPLATE_LAYOUT_DEFAULTS[name]

        padding = re.search(r"padding:\s*([\d.]+)mm", css)
        assert padding, f"{spec['file']} 里没找到页边距"
        assert float(padding.group(1)) == defaults["padding_mm"], name

        line_height = re.search(r"line-height:\s*([\d.]+)", css)
        assert line_height, f"{spec['file']} 里没找到行高"
        assert float(line_height.group(1)) == defaults["line_height"], name

        gap = re.search(r"\.section\s*\{\s*margin-bottom:\s*calc\(var\(--fs\)\s*\*\s*([\d.]+)\)", css)
        assert gap, f"{spec['file']} 里没找到区块间距"
        assert float(gap.group(1)) == defaults["section_gap"], name


def test_every_template_has_layout_defaults():
    assert set(TEMPLATE_LAYOUT_DEFAULTS) == set(RESUME_TEMPLATES)


def test_every_template_sizes_everything_from_the_fs_variable():
    """所有尺寸都必须由 `--fs` 派生，否则整份简历无法按档位整体缩放。

    自动一页最细的一档就是改这一个变量：模板里若混着写死的 px，那一档就会只缩一部分
    文字，版面看起来"没收紧多少"——而用户完全看不出原因。
    """
    for name, spec in RESUME_TEMPLATES.items():
        css = (TEMPLATES_DIR / spec["file"]).read_text(encoding="utf-8")
        assert "--fs: {{ base_px }}px;" in css, name
        # 正文与标题的主要尺寸都要走 calc(var(--fs) * N)。
        assert "font-size: var(--fs);" in css, name
        assert "calc(var(--fs) *" in css, name
