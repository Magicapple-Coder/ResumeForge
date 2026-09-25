"""配方归纳：模型只给数据，选择器由我们反推，**重放通不过就不落库**。

这一层的价值全在"重放校验"上——它是"归纳出来的东西能信"的唯一理由。所以用例的重点不是
"能不能归纳出来"，而是**归纳不出来的那些情形有没有如实放弃**：

- 模型编了一个页面上不存在的地址 → 那条不参与归纳（它凭这一条就没法把幻觉带进来）；
- 各条岗位的标题不在同一处 → 一条规则表达不了，不归纳；
- 学到的地址片段太宽（把整站链接都吸进来）→ 重放出来的条数会明显超标，不归纳。

**归纳失败不是错误**：本轮照用模型读到的数据，只是不落库、下次还得再问一次。报告里要如实
写出这件事——用户自付 key，他有权知道钱花在哪、为什么没省下来。
"""
from __future__ import annotations

import pytest

from app.services.sites.official.generic.induce import (
    MAX_EXTRA_ABSOLUTE,
    MIN_MARKER_CHARS,
    _common_marker,
    induce_recipe,
)
from app.services.sites.official.generic.recipe import ExtractedJob, extract_with_recipe

PAGE = "https://careers.example.com/jobs"

LIST_PAGE = """<ul>
<li class="job-card"><a href="/jobs/1">大模型应用开发工程师</a>
  <span class="job-location">北京</span><time datetime="2026-09-01">9月1日</time></li>
<li class="job-card"><a href="/jobs/2">算法工程师</a>
  <span class="job-location">上海</span><time datetime="2026-09-02">9月2日</time></li>
</ul>"""

MODEL_JOBS = [
    ExtractedJob(
        url="https://careers.example.com/jobs/1",
        title="大模型应用开发工程师",
        location="北京",
        posted_at="2026-09-01",
    ),
    ExtractedJob(
        url="https://careers.example.com/jobs/2",
        title="算法工程师",
        location="上海",
        posted_at="2026-09-02",
    ),
]


# ===== 归纳成功 =====


def test_induced_recipe_replays_the_same_jobs():
    """归纳的全部意义在这里：**下次不用再问模型**，读出来的还必须是同一批。"""
    induction = induce_recipe(LIST_PAGE, PAGE, MODEL_JOBS)

    assert induction.recipe is not None
    replayed = extract_with_recipe(induction.recipe, LIST_PAGE, page_url=PAGE)
    assert [(job.url, job.title) for job in replayed] == [
        (job.url, job.title) for job in MODEL_JOBS
    ]
    assert [job.location for job in replayed] == ["北京", "上海"]
    assert [job.posted_at for job in replayed] == ["2026-09-01", "2026-09-02"]


def test_induced_location_rule_does_not_need_the_whole_card_signature():
    """地点规则只认它自己那一层，不把整张卡片的 class 一起锁死——那样一改版就全断。"""
    induction = induce_recipe(LIST_PAGE, PAGE, MODEL_JOBS)

    assert induction.recipe is not None
    assert induction.recipe.location is not None
    assert induction.recipe.location.signature.tag == "span"


def test_induction_is_deterministic():
    """同一页、同样的模型输出必须归纳出同一份配方，否则落库的配方说不清是哪一次的。"""
    first = induce_recipe(LIST_PAGE, PAGE, MODEL_JOBS)
    second = induce_recipe(LIST_PAGE, PAGE, MODEL_JOBS)

    assert first.recipe == second.recipe


def test_title_taken_from_an_ancestor_when_the_link_text_is_not_the_title():
    """链接文字是"查看详情"、标题在旁边的 ``<h3>`` 里——**这正是模型该出场的那种页面**。"""
    markup = (
        '<ul><li class="job-card"><h3>大模型应用开发工程师</h3><a href="/jobs/1">查看详情</a></li>'
        '<li class="job-card"><h3>算法工程师</h3><a href="/jobs/2">查看详情</a></li></ul>'
    )
    jobs = [
        ExtractedJob(url="https://careers.example.com/jobs/1", title="大模型应用开发工程师"),
        ExtractedJob(url="https://careers.example.com/jobs/2", title="算法工程师"),
    ]

    induction = induce_recipe(markup, PAGE, jobs)

    assert induction.recipe is not None
    assert [job.title for job in extract_with_recipe(induction.recipe, markup, page_url=PAGE)] == [
        "大模型应用开发工程师",
        "算法工程师",
    ]


def test_a_job_without_a_title_is_left_out_of_the_induction():
    """没有标题的条目连"这是不是一条岗位"都说不清，不参与归纳。"""
    jobs = [
        *MODEL_JOBS,
        ExtractedJob(url="https://careers.example.com/jobs/2", title=""),
    ]

    induction = induce_recipe(LIST_PAGE, PAGE, jobs)

    assert induction.recipe is not None


# ===== 模型的幻觉挡在门外 =====


def test_urls_that_are_not_on_the_page_cannot_ground_a_recipe():
    """**模型编不出一个真实存在于页面上的链接**——这是最先做、也最有效的一道闸。"""
    jobs = [
        *MODEL_JOBS,
        ExtractedJob(url="https://careers.example.com/jobs/999", title="不存在的岗位"),
    ]

    induction = induce_recipe(LIST_PAGE, PAGE, jobs)

    assert induction.ungrounded == 1
    assert induction.grounded == 2


def test_a_recipe_is_not_induced_when_every_url_is_invented():
    jobs = [ExtractedJob(url="https://careers.example.com/jobs/999", title="不存在的岗位")]

    induction = induce_recipe(LIST_PAGE, PAGE, jobs)

    assert induction.recipe is None
    assert induction.grounded == 0
    assert induction.detail


def test_jobs_with_titles_from_different_places_are_not_induced():
    """一条规则表达不了两处标题。硬凑一条的结果是每次采集都读出一半的垃圾。"""
    markup = (
        '<ul><li class="a"><a href="/jobs/1">大模型应用开发工程师</a></li>'
        '<li class="b"><h3>算法工程师</h3><a href="/jobs/2">算法工程师</a></li></ul>'
    )
    jobs = [
        ExtractedJob(url="https://careers.example.com/jobs/1", title="大模型应用开发工程师"),
        ExtractedJob(url="https://careers.example.com/jobs/2", title="算法工程师"),
    ]

    induction = induce_recipe(markup, PAGE, jobs)

    # 第二条的标题在链接自己身上也能找到，所以这里应当归纳成功——两种情况都允许，
    # 但**必须重放得出来**。
    if induction.recipe is not None:
        replayed = extract_with_recipe(induction.recipe, markup, page_url=PAGE)
        assert {job.url for job in replayed} == {job.url for job in jobs}


# ===== 学出来的地址片段 =====


def test_url_markers_are_learned_for_unusual_job_paths():
    """岗位地址长得不像 ``/jobs/123`` 的站点靠这一条才读得到。"""
    markup = '<ul><li><a href="/p/8821">大模型应用开发工程师</a></li><li><a href="/p/8822">算法工程师</a></li></ul>'
    jobs = [
        ExtractedJob(url="https://careers.example.com/p/8821", title="大模型应用开发工程师"),
        ExtractedJob(url="https://careers.example.com/p/8822", title="算法工程师"),
    ]

    induction = induce_recipe(markup, PAGE, jobs)

    assert induction.recipe is not None
    assert induction.recipe.url_markers == ("/p/",)


def test_normal_job_urls_do_not_learn_markers():
    """通用判据够用时**不学**：学来的片段是猜的，能不用就不用。"""
    induction = induce_recipe(LIST_PAGE, PAGE, MODEL_JOBS)

    assert induction.recipe is not None
    assert induction.recipe.url_markers == ()


@pytest.mark.parametrize(
    ("urls", "expected"),
    [
        (["https://a.com/p/8821", "https://a.com/p/8822"], "/p/"),
        (["https://a.com/job/abc-1", "https://a.com/job/xyz-2"], "/job/"),
        # 只有公共的 "/"：太宽泛，学不出可复用的规则。
        (["https://a.com/a/1", "https://a.com/b/2"], "/"),
        (["https://a.com/x"], "/"),
        ([], ""),
    ],
)
def test_common_marker_cuts_at_a_segment_boundary(urls, expected):
    """切到段边界是必须的：``/p/88`` 这种半个数字的前缀在下一页就不成立了。"""
    assert _common_marker(urls) == expected


def test_a_too_broad_marker_is_rejected_by_the_replay_check():
    """**重放校验挡住的就是这一类**：学到的规则把整站链接都吸了进来。

    没有这道校验，落库的"配方"会把列表页变成站点地图——而它看起来工作得很好。
    """
    links = "".join(f'<li><a href="/p/{index}">岗位名称第{index}号</a></li>' for index in range(1, 10))
    markup = f"<ul>{links}</ul>"
    jobs = [
        ExtractedJob(url="https://careers.example.com/p/1", title="岗位名称第1号"),
        ExtractedJob(url="https://careers.example.com/p/2", title="岗位名称第2号"),
    ]

    induction = induce_recipe(markup, PAGE, jobs)

    assert induction.recipe is None
    assert induction.extra > MAX_EXTRA_ABSOLUTE
    assert induction.detail


def test_marker_shorter_than_the_minimum_is_refused():
    assert MIN_MARKER_CHARS >= 2
    assert len("/") < MIN_MARKER_CHARS


# ===== 可选字段 =====


def test_an_inconsistent_optional_field_is_dropped_without_losing_the_recipe():
    """少一个字段不影响配方能用；一条时灵时不灵的规则会让值真假混杂，那比没有更糟。"""
    markup = (
        '<ul><li class="job-card"><a href="/jobs/1">大模型应用开发工程师</a>'
        '<span class="job-location">北京</span></li>'
        '<li class="job-card"><a href="/jobs/2">算法工程师</a></li></ul>'
    )
    jobs = [
        ExtractedJob(
            url="https://careers.example.com/jobs/1", title="大模型应用开发工程师", location="北京"
        ),
        # 第二条的地点在这页上根本找不到出处。
        ExtractedJob(url="https://careers.example.com/jobs/2", title="算法工程师", location="上海"),
    ]

    induction = induce_recipe(markup, PAGE, jobs)

    assert induction.recipe is not None
    assert induction.recipe.location is None
    # 标题规则不受影响。
    assert induction.recipe.title is not None


def test_a_date_found_in_an_attribute_is_learned_as_an_attribute_rule():
    """``<time datetime="2026-09-01">`` 里正文明明是"9月1日"，按文本找是找不到的。"""
    induction = induce_recipe(LIST_PAGE, PAGE, MODEL_JOBS)

    assert induction.recipe is not None
    assert induction.recipe.posted_at is not None
    assert induction.recipe.posted_at.attr == "datetime"


def test_missing_optional_fields_stay_absent():
    markup = '<ul><li><a href="/jobs/1">大模型应用开发工程师</a></li><li><a href="/jobs/2">算法工程师</a></li></ul>'
    jobs = [
        ExtractedJob(url="https://careers.example.com/jobs/1", title="大模型应用开发工程师"),
        ExtractedJob(url="https://careers.example.com/jobs/2", title="算法工程师"),
    ]

    induction = induce_recipe(markup, PAGE, jobs)

    assert induction.recipe is not None
    assert induction.recipe.location is None
    assert induction.recipe.posted_at is None


def test_relative_urls_from_the_model_are_resolved_before_matching():
    """模型给相对地址是常事，按字面比较会把每一条都判成"页面里没有"。"""
    jobs = [
        ExtractedJob(url="/jobs/1", title="大模型应用开发工程师"),
        ExtractedJob(url="/jobs/2", title="算法工程师"),
    ]

    induction = induce_recipe(LIST_PAGE, PAGE, jobs)

    assert induction.grounded == 2


def test_empty_model_output_yields_nothing():
    induction = induce_recipe(LIST_PAGE, PAGE, [])

    assert induction.recipe is None
    assert induction.detail


def test_a_field_rule_that_cannot_be_reproduced_is_dropped_not_stored():
    """**签名不唯一的字段规则必须丢掉，不能留着。**（实跑复现过的缺陷）

    归纳时限位靠的是"哪个元素的文本等于这个值"，而写进配方的只有那个元素的**签名**。卡里若有
    第二个元素签名完全相同（``<span class="tag">社招</span><span class="tag">北京</span>``），
    重放时命中第一个，读出来是"社招"——**值看着正常，却没有任何下游信号能发现它**，
    而它会被永久落库、此后每次采集都错。

    重放校验因此必须**逐字段核对**，不只是核对标题。
    """
    markup = (
        '<ul>'
        '<li><h3>大模型应用开发工程师</h3><a href="/jobs/1">查看详情</a>'
        '<span class="tag">社招</span><span class="tag">北京</span></li>'
        '<li><h3>算法工程师</h3><a href="/jobs/2">查看详情</a>'
        '<span class="tag">社招</span><span class="tag">上海</span></li>'
        "</ul>"
    )
    jobs = [
        ExtractedJob(url="https://careers.example.com/jobs/1", title="大模型应用开发工程师",
                     location="北京"),
        ExtractedJob(url="https://careers.example.com/jobs/2", title="算法工程师",
                     location="上海"),
    ]

    induction = induce_recipe(markup, PAGE, jobs)

    assert induction.recipe is not None, "标题与地址规则是对的，整份配方不该作废"
    assert induction.recipe.location is None, "重放对不上的字段规则必须丢掉"
    # 丢掉之后就再也不会产出错值。
    replayed = extract_with_recipe(induction.recipe, markup, page_url=PAGE)
    assert [job.location for job in replayed] == ["", ""]


def test_a_field_rule_that_does_replay_is_kept():
    """反过来：重放对得上的字段当然要留着——上面的丢弃不能扩大到正常情形。"""
    induction = induce_recipe(LIST_PAGE, PAGE, MODEL_JOBS)

    assert induction.recipe is not None
    assert induction.recipe.location is not None
    assert induction.recipe.posted_at is not None
