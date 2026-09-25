"""把已知是正文的 HTML 转成纯文本。

**与搜索层的 `extract_text` 是两份不同的实现，不能互相替代**：那一个的契约是"在一个完整
网页里*找出*正文"，因此带一条"短段落当作导航丢弃"的启发式（阈值 20 字符）。招聘接口给的
``content`` 字段我们已经**知道**它就是职位描述，套用"找正文"的启发式会把「熟悉 Python。」
这样的短要求整段吃掉——而职位描述恰恰是这一层最不能丢的东西。

这里守的就是这条区别，外加两类会静默污染描述的东西：脚本内容、以及一行行糊在一起的分段。
"""
from __future__ import annotations

from app.services.sites.official.html_text import html_to_text


def test_short_paragraphs_survive():
    """短段落必须保留——这正是不能复用搜索层抽取器的原因。"""
    text = html_to_text("<p>熟悉 Python。</p><p>有责任心。</p>")
    assert "熟悉 Python。" in text
    assert "有责任心。" in text


def test_block_tags_produce_line_breaks():
    """职责与要求要分行：全部拼成一行会让边界糊在一起。"""
    text = html_to_text("<h3>岗位职责</h3><p>负责模型落地</p><ul><li>调参</li><li>评估</li></ul>")
    lines = text.split("\n")
    assert "岗位职责" in lines
    assert "负责模型落地" in lines
    assert "调参" in lines and "评估" in lines


def test_script_and_style_contents_are_dropped():
    """脚本与样式的内容不是正文。

    不丢的话，一段内联 JS 会被原样写进岗位描述，接着进提示词——既是噪声，也是把站点的
    代码搬进模型上下文的坏习惯。
    """
    markup = (
        "<div><script>var tracking = 'should not appear';</script>"
        "<style>.job { color: red }</style>"
        "<p>这才是职位描述</p></div>"
    )
    text = html_to_text(markup)

    assert "这才是职位描述" in text
    assert "should not appear" not in text
    assert "color: red" not in text


def test_nested_script_regions_are_fully_skipped():
    """嵌套结构里也不能漏出脚本文本。"""
    markup = "<div><div><script><p>藏在脚本里的假段落</p></script><p>真段落</p></div></div>"
    text = html_to_text(markup)

    assert "真段落" in text
    assert "假段落" not in text


def test_entities_are_decoded():
    assert "研发 & 设计" in html_to_text("<p>研发 &amp; 设计</p>")


def test_whitespace_is_collapsed():
    text = html_to_text("<p>第一行      有很多空格</p>\n\n\n<p>第二行</p>")
    assert "第一行 有很多空格" in text
    assert "  " not in text.replace("\n", "")


def test_empty_markup_returns_empty_string():
    assert html_to_text("") == ""
    assert html_to_text("   ") == ""


def test_max_chars_truncates():
    text = html_to_text("<p>" + "字" * 500 + "</p>", max_chars=100)
    assert len(text) == 100


def test_malformed_markup_does_not_raise():
    """页面再乱也不该让一条岗位取不回来。"""
    assert "内容" in html_to_text("<p>内容</p><div><span>未闭合")


def test_tags_without_block_semantics_stay_inline():
    """行内标签不该产生换行：``<strong>`` 断开会把一句话拆成两行。"""
    text = html_to_text("<p>熟悉 <strong>Python</strong> 与 SQL</p>")
    assert text.strip() == "熟悉 Python 与 SQL"
