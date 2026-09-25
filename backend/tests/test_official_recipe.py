"""结构签名式配方：抽取、重定位、序列化。

这一层要守的性质只有一条，但它是整个阶段 2 的地基：**读出来的东西要么是对的，要么是空的**。
配方永远不会"读出一个看起来正常但在错误位置的值"——因为那种错误没有任何下游信号能发现它，
它会一路进到用户的暂选列表里。

三组用例分别对应三处容易做错的地方：

- **默认配方**（锚文本即岗位名）必须把"查看详情""更多"这类操作文案挡掉：不挡的话，一次采集
  会把导航文案当岗位存进去，用户得自己一条条删。
- **相似度重定位治的是结构漂移，不是改名**：多包一层、class 增补要能救回来；class 被整个换掉
  救不回来，那时必须**如实留空**而不是硬匹配一个别的东西。
- **配方反序列化认不出来就返回空**：半懂的配方比没有配方危险得多。
"""
from __future__ import annotations

import pytest

from app.services.sites.official.generic.recipe import (
    MATCH_THRESHOLD,
    MAX_ANCESTOR_STEPS,
    RECIPE_SCHEMA,
    SCOPE_ANCESTORS,
    SCOPE_CARD,
    SCOPE_SELF,
    FieldRule,
    Recipe,
    Signature,
    default_recipe,
    extract_with_recipe,
    matches,
    similarity,
    squash,
)
from app.services.sites.official.generic.dom import parse_document

PAGE = "https://careers.example.com/jobs"

LIST_PAGE = """
<ul>
  <li class="job-card">
    <a href="/jobs/1">大模型应用开发工程师</a>
    <span class="job-location">北京</span>
    <time datetime="2026-09-01">9月1日</time>
  </li>
  <li class="job-card">
    <a href="/jobs/2">算法工程师</a>
    <span class="job-location">上海</span>
    <time datetime="2026-09-02">9月2日</time>
  </li>
</ul>
"""

FULL_RECIPE = Recipe(
    title=FieldRule(scope=SCOPE_SELF, signature=Signature(tag="a")),
    location=FieldRule(
        scope=SCOPE_CARD, signature=Signature(tag="span", classes=("job-location",))
    ),
    posted_at=FieldRule(
        scope=SCOPE_CARD, signature=Signature(tag="time"), attr="datetime"
    ),
)


def _titles(markup: str, recipe: Recipe | None = None, page: str = PAGE) -> list[str]:
    return [
        job.title
        for job in extract_with_recipe(recipe or default_recipe(), markup, page_url=page)
    ]


# ===== 默认配方 =====


def test_default_recipe_takes_the_anchor_text_as_the_title():
    assert _titles(LIST_PAGE) == ["大模型应用开发工程师", "算法工程师"]


def test_card_wrapped_anchor_uses_the_inner_title_instead_of_the_whole_card():
    """有些站点把完整岗位卡片放在 ``a`` 里，不能把正文存成岗位名。"""
    markup = (
        '<a href="/jobs/1">'
        '<div class="positionItem">'
        '<div class="positionItem-title"><span>高级 Java 工程师</span></div>'
        '<div class="positionItem-subTitle">上海 · 正式 · 研发 · 职位 ID：A123</div>'
        '<div class="positionItem-jobDesc">'
        "负责平台建设与服务治理，参与架构设计、研发、测试和上线，"
        "并与产品及算法团队协作完成业务目标。"
        "需要持续关注系统稳定性、可观测性、性能优化和工程质量，"
        "与产品、算法、数据和基础设施团队保持高效协作，"
        "推动复杂业务从方案评审、开发联调到灰度发布和线上复盘，"
        "同时沉淀可复用的技术方案、故障处理流程与团队工程规范。"
        "该岗位还会参与技术选型、服务治理、容量评估、风险识别，"
        "并通过自动化工具提升研发效率和交付质量。"
        "</div>"
        "</div>"
        "</a>"
    )

    assert _titles(markup) == ["高级 Java 工程师"]


@pytest.mark.parametrize(
    "anchor",
    ["查看详情", "更多", "立即申请", "more", "View More", "详情", "»", "→", "  ", "A"],
)
def test_operation_wording_is_not_a_job_title(anchor):
    """**不挡掉的话，一次采集会把导航文案当岗位存进暂选列表**，用户得自己一条条删。"""
    markup = f'<div><a href="/jobs/1">{anchor}</a></div>'

    assert _titles(markup) == []


def test_a_real_title_containing_a_stopword_is_kept():
    """**只过滤整词**：岗位名里出现"申请"两个字很常见（"申请专员"），按子串过滤会误伤。"""
    markup = '<div><a href="/jobs/1">申请专员</a></div>'

    assert _titles(markup) == ["申请专员"]


def test_default_recipe_ignores_links_that_are_not_job_pages():
    markup = (
        '<div><a href="/about">关于我们</a>'
        '<a href="/jobs">全部岗位</a>'
        '<a href="/jobs/9">后端工程师</a></div>'
    )

    assert _titles(markup) == ["后端工程师"]


def test_off_host_links_are_ignored():
    """跨站的多半是社交分享、母公司官网、招聘平台外链。"""
    markup = '<div><a href="https://weibo.com/jobs/1">岗位</a></div>'

    assert _titles(markup) == []


def test_base_href_changes_how_relative_links_resolve():
    """``<base href>`` 是站内页面的常见写法，忽略它会把相对链接全拼错。"""
    markup = '<head><base href="https://careers.example.com/v2/"></head><a href="/jobs/1">岗位</a>'

    jobs = extract_with_recipe(default_recipe(), markup, page_url="https://www.example.com/")

    assert [job.url for job in jobs] == ["https://careers.example.com/jobs/1"]


def test_fragment_is_stripped_so_one_page_is_not_collected_twice():
    markup = '<div><a href="/jobs/1#apply">岗位</a><a href="/jobs/1">岗位</a></div>'

    assert len(_titles(markup)) == 1


def test_unclosed_list_items_still_yield_titles():
    """省略 ``</li>`` 在真实页面上很常见；读不出文本的表现是"这一页没岗位"。"""
    assert _titles('<ul><li><a href="/jobs/1">岗位</a></li>') == ["岗位"]


def test_malformed_markup_does_not_raise():
    assert _titles('<div><a href="/jobs/1">岗位</a></div></div></div>') == ["岗位"]
    assert _titles("<<<>>>") == []


# ===== 卡片范围 =====


def test_card_scope_reaches_siblings_of_the_link():
    """地点与链接是**兄弟**关系，既不在链接里也不在链接的祖先上。

    少了这一档，非 JSON-LD 站点就只能读到标题。
    """
    jobs = extract_with_recipe(FULL_RECIPE, LIST_PAGE, page_url=PAGE)

    assert [job.location for job in jobs] == ["北京", "上海"]
    assert [job.posted_at for job in jobs] == ["2026-09-01", "2026-09-02"]


def test_card_is_the_largest_element_holding_only_this_link():
    """链接裹在 ``<h3>`` 里时父元素是标题而不是卡片，按"父元素"取会读不到地点。"""
    markup = (
        '<ul><li class="job-card"><h3><a href="/jobs/1">岗位</a></h3>'
        '<span class="job-location">北京</span></li></ul>'
    )

    jobs = extract_with_recipe(FULL_RECIPE, markup, page_url=PAGE)

    assert jobs[0].location == "北京"


def test_card_does_not_swallow_the_neighbour():
    """卡片是"**只含我一个链接**的最大元素"——再往外一层就把邻居框进来了。"""
    markup = (
        '<div><a href="/jobs/1">大模型工程师</a><a href="/jobs/2">算法工程师</a>'
        '<span class="job-location">北京</span></div>'
    )
    # 两个链接共处一个容器时它就不是卡片；地点在链接的兄弟位置，因此读不到。
    jobs = extract_with_recipe(FULL_RECIPE, markup, page_url=PAGE)

    assert [job.title for job in jobs] == ["大模型工程师", "算法工程师"]
    assert [job.location for job in jobs] == ["", ""]


def test_ancestor_scope_stays_close_to_the_link():
    """向上找太远会摸到页面顶部（导航栏里也有 span），所以有步数上限。"""
    deep = "".join(f"<div class='w{i}'>" for i in range(MAX_ANCESTOR_STEPS + 3))
    markup = f'<div class="top"><span class="job-location">不该读到</span>{deep}<a href="/jobs/1">岗位</a>'
    recipe = Recipe(
        title=FieldRule(scope=SCOPE_SELF, signature=Signature(tag="a")),
        location=FieldRule(
            scope=SCOPE_ANCESTORS, signature=Signature(tag="span", classes=("job-location",))
        ),
    )

    assert extract_with_recipe(recipe, markup, page_url=PAGE)[0].location == ""


# ===== 签名与相似度 =====


def test_empty_signature_matches_nothing():
    """空签名如果"什么都能命中"，配方就会读出一堆碰巧排在前面的元素。"""
    document = parse_document("<div><span>x</span></div>")

    assert matches(Signature(), document, 0) is False
    assert similarity(Signature(), "div", (), ("id",)) == 0.0


def test_tag_is_a_hard_condition():
    """``div`` 不是 ``span``。把"标签变了"当成"权重低一点"会让配方滑到别的元素上。"""
    assert similarity(Signature(tag="span", classes=("a",)), "div", ("a",), ()) == 0.0


def test_similarity_is_recall_not_jaccard():
    """**用覆盖率而不是 Jaccard**：元素上多出来的 class 不该拉低分数。

    Jaccard 会把"签名里的类还在、只是多了两个"也判成不相似（1/3 = 0.33），而 class 增补
    恰恰是最常见的一种改版。
    """
    score = similarity(
        Signature(tag="span", classes=("job-location",)),
        "span",
        ("job-location", "job-location--city", "u-text-2"),
        (),
    )

    assert score == 1.0


def test_partially_surviving_classes_still_relocate():
    """**这正是相似度唯一能多做的那件事**：签名的特征掉了一部分时仍认得出是同一个元素。"""
    signature = Signature(tag="li", classes=("job-item", "full-time"))

    assert similarity(signature, "li", ("job-item",), ()) == pytest.approx(0.5)
    assert similarity(signature, "li", ("job-item",), ()) >= MATCH_THRESHOLD
    # 一个都不剩：如实判失效，而不是硬匹配到某个碰巧也像的元素上。
    assert similarity(signature, "li", ("other",), ()) < MATCH_THRESHOLD


def test_similarity_grades_with_how_much_survives():
    signature = Signature(tag="li", classes=("a", "b", "c"))

    assert similarity(signature, "li", ("a",), ()) == pytest.approx(1 / 3)
    assert similarity(signature, "li", ("a", "b"), ()) == pytest.approx(2 / 3)
    assert similarity(signature, "li", ("a", "b", "c"), ()) == 1.0


def test_completely_renamed_classes_do_not_match():
    """**改名救不回来，也不该硬救**：硬匹配会读出一个看似正常却在错误位置的值。"""
    score = similarity(
        Signature(tag="span", classes=("job-location",)), "span", ("loc-text",), ()
    )

    assert score < 0.6


def test_tag_only_signature_matches_on_tag_alone():
    assert similarity(Signature(tag="time"), "time", ("x",), ("datetime",)) == 1.0


def test_similarity_stays_within_range():
    for classes in [(), ("a",), ("a", "b")]:
        score = similarity(Signature(tag="div", classes=("a",)), "div", classes, ("id",))
        assert 0.0 <= score <= 1.0


# ===== 重定位 =====


def test_wrapper_insertion_and_added_classes_are_survived():
    """**结构漂移正是相似度重定位存在的理由**：站点改版时最先动的就是这些。"""
    drifted = LIST_PAGE.replace(
        'class="job-card"', 'class="job-card job-card--wide"'
    ).replace("<ul>", '<ul><div class="list-wrap">').replace("</ul>", "</div></ul>")

    jobs = extract_with_recipe(FULL_RECIPE, drifted, page_url=PAGE)

    assert [job.location for job in jobs] == ["北京", "上海"]


def test_a_renamed_field_goes_empty_rather_than_wrong():
    """**留空是对的，硬匹配是错的**：空值下游会如实报告"这条没有地点"，
    而错误的值没有任何下游信号能发现它。"""
    drifted = LIST_PAGE.replace("job-location", "loc-text")

    jobs = extract_with_recipe(FULL_RECIPE, drifted, page_url=PAGE)

    assert [job.title for job in jobs] == ["大模型应用开发工程师", "算法工程师"]
    assert [job.location for job in jobs] == ["", ""]
    # 其余字段不受影响——一个字段失效不该拖垮整条记录。
    assert [job.posted_at for job in jobs] == ["2026-09-01", "2026-09-02"]


# ===== 学出来的地址片段 =====


def test_learned_url_markers_let_unusual_job_urls_through():
    """岗位地址长得不像 ``/jobs/123`` 的站点（``/p/8821``）靠这一条才读得到。"""
    markup = '<div><a href="/p/8821">岗位</a></div>'
    recipe = Recipe(
        title=FieldRule(scope=SCOPE_SELF, signature=Signature(tag="a")),
        url_markers=("/p/",),
    )

    assert extract_with_recipe(default_recipe(), markup, page_url=PAGE) == []
    assert [job.url for job in extract_with_recipe(recipe, markup, page_url=PAGE)] == [
        "https://careers.example.com/p/8821"
    ]


# ===== 序列化 =====


def test_recipe_round_trips_through_json():
    import json

    restored = Recipe.from_dict(json.loads(json.dumps(FULL_RECIPE.to_dict())))

    assert restored == FULL_RECIPE


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        [],
        "配方",
        {"schema": RECIPE_SCHEMA + 1, "title": {"scope": "self"}},
        {"schema": RECIPE_SCHEMA},
        {"schema": RECIPE_SCHEMA, "title": {"scope": "别的地方"}},
    ],
)
def test_unreadable_recipe_is_none_rather_than_a_guess(raw):
    """**半懂的配方比没有配方危险**：它会产出看似正常的结果，而没人知道该怀疑它。"""
    assert Recipe.from_dict(raw) is None


def test_unknown_optional_fields_default_to_absent():
    recipe = Recipe.from_dict({"schema": RECIPE_SCHEMA, "title": {"scope": "self"}})

    assert recipe is not None
    assert recipe.location is None
    assert recipe.posted_at is None


def test_default_recipe_does_not_learn_any_url_markers():
    """默认配方走通用判据；带上"学出来的片段"会让它偏离"什么都不假设"的定位。"""
    assert default_recipe().url_markers == ()


def test_squash_ignores_whitespace():
    """页面与模型回复的空白写法不会一致，逐字比较会把好配方判成失效——
    表现是"每次都重新调模型"，用户只会看到账单变高。"""
    assert squash("大模型\n  应用\t开发") == squash("大模型应用开发")
    assert squash("") == ""
