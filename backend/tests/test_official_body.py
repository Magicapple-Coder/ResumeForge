"""从详情页 DOM 里读正文——**每条判据都对应一个实测过的失败形态**。

这一级的产出会直接进 ``CandidateJob.description``，再流进技能标签、岗位匹配、简历定制。
**一段错的正文比没有正文糟得多**：它会以"这就是这份 JD"的身份参与匹配，而错得又不像错。
所以这里的反例比正例多：每个测试守的都是"宁可返回空，也不能返回那段错的"。
"""
from __future__ import annotations

from app.services.sites.official.generic.body import extract_page_body

DESCRIPTION = (
    "1、负责平台广告策略的制定与迭代，结合行业数据与客户诉求给出可执行的方案；"
    "2、协同产品、数据与销售推动投放能力升级。"
)
REQUIREMENTS = "1、本科及以上学历，五年以上相关行业经验；2、沟通能力强，英文流利。"


def _page(*sections: str, tail: str = "") -> str:
    """一个常见的 JD 版式：每个章节是 ``<div class="title">`` + ``<div class="body">``。"""
    body = "".join(
        f'<div class="block-title">{title}</div><div class="block-content">{text}</div>'
        for title, text in sections
    )
    return f"<html><body><div class='job'>{body}</div>{tail}</body></html>"


# ===== 正常路径 =====


def test_reads_description_and_requirements_separately():
    """两段**分开返回**：``CandidateJob`` 本来就把它们分成两列存（下游解析也认这两列）。"""
    body = extract_page_body(_page(("职位描述", DESCRIPTION), ("职位要求", REQUIREMENTS)))

    assert body.description == DESCRIPTION
    assert body.requirements == REQUIREMENTS


def test_reads_english_section_titles():
    """词表是中英双语的（``section_constants``），别把英文站漏在外面。"""
    body = extract_page_body(
        _page(("Responsibilities", DESCRIPTION), ("Qualifications", REQUIREMENTS))
    )

    assert body.description == DESCRIPTION
    assert body.requirements == REQUIREMENTS


def test_keeps_a_section_whose_content_is_wrapped_next_to_the_title():
    """标题与正文分属两个包裹层的版式：标题那一层里没内容，要**往上一层**接着找。

    这类版式在真实站点上很常见（``<div><h3>职位描述</h3></div><div>正文</div>``）。
    不做上溯的话这一页会被判成"没有正文"——而那是一条**误判**：页面写得清清楚楚。
    """
    markup = (
        "<html><body><div class='job'>"
        "<div class='row'><div class='t'>职位描述</div></div><div class='c'>"
        f"{DESCRIPTION}</div>"
        "</div></body></html>"
    )

    body = extract_page_body(markup)

    assert body.description == DESCRIPTION


# ===== 反例：宁可空，也不要错的那一段 =====


def test_content_is_not_glued_past_the_ancestor_boundary():
    """**实测过的失败形态**：只按"遇到下一个标题才停"取兄弟节点时，最后一节会一路吃到页脚。

    真实站点上因此把「相关职位」里几十条**别的岗位**全并进了正文——那不只是难看：
    下游会拿这些文字去算技能标签与匹配度。
    """
    tail = (
        "<div class='related'><div>相关职位</div>"
        "<a href='/jobs/9'>另一个岗位的名称</a><a href='/jobs/8'>再一个岗位的名称</a></div>"
    )
    body = extract_page_body(_page(("职位描述", DESCRIPTION), tail=tail))

    assert body.description == DESCRIPTION
    assert "相关职位" not in body.description
    assert "另一个岗位的名称" not in body.description


def test_additional_sections_terminate_the_window():
    """「福利待遇 / 公司介绍」这些**不收集，但必须当终止符**。

    不认它们的话，「福利待遇：……」整段会被粘进职位描述里——而下游会把公司福利
    当成岗位要求去算匹配。它们对应的是另一个字段（``additional_info``），不是描述。
    """
    body = extract_page_body(
        _page(
            ("职位描述", DESCRIPTION),
            ("福利待遇", "五险一金、免费三餐、弹性工作制、年度体检、补充医疗保险、带薪年假。"),
        )
    )

    assert body.description == DESCRIPTION
    assert "五险一金" not in body.description


def test_a_page_without_section_titles_yields_nothing():
    """普通列表页、栏目页没有 JD 章节——返回空，而不是把整页文字当成正文。"""
    markup = (
        "<html><body><ul>"
        "<li><a href='/jobs/1'>岗位一</a></li><li><a href='/jobs/2'>岗位二</a></li>"
        "</ul></body></html>"
    )

    assert not extract_page_body(markup)
    assert extract_page_body("") == extract_page_body("<html></html>")


def test_a_navigation_link_named_like_a_section_is_not_a_heading():
    """导航里出现一个叫「职位描述」的链接时不算命中——**它后面没有内容**。

    这条既是"空窗口不算命中"，也顺带挡住"页面正文里出现这个词"的误命中。
    """
    markup = (
        "<html><body><nav><a href='/a'>职位描述</a><a href='/b'>职位要求</a></nav>"
        "<main><p>这是页面正文，与章节标题无关。</p></main></body></html>"
    )

    assert not extract_page_body(markup)


def test_a_section_with_only_a_stub_is_not_taken_as_the_body():
    """标题下只有一句残句时不要——下游会把这段残句当成完整 JD 去解析。"""
    markup = _page(("职位描述", "详见附件"))

    assert not extract_page_body(markup)


def test_page_controls_are_not_glued_onto_the_last_section():
    """页面控件（按钮）挨着最后一节时不能被带进来。

    实测：那个「投递」按钮与最后一节正文同属一个容器，取容器文本时会得到
    "……英文流利。 投递"——按钮文字对下游是纯噪音。
    """
    markup = (
        "<html><body><div class='job'>"
        f"<div class='block-title'>职位要求</div><div class='block-content'>{REQUIREMENTS}"
        "<div class='apply'><button type='button'><span>投递</span></button></div></div>"
        "</div></body></html>"
    )

    body = extract_page_body(markup)

    assert body.requirements == REQUIREMENTS
    assert "投递" not in body.requirements


def test_the_body_is_capped():
    """封顶：一次误判把整页塞进文本列、再进岗位表，是这个功能唯一难恢复的后果。"""
    huge = "甲" * 50_000
    body = extract_page_body(_page(("职位描述", huge)), max_chars=1000)

    assert len(body.description) == 1000
