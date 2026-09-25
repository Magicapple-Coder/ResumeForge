"""元素事件流：层级记账与文本归属。

三组用例各守一条容易做错的事，而且它们的错法都**不会报错**——只会让配方莫名其妙地什么都
匹配不上，排查时没人会想到是解析层：

1. **空元素**（``<br>`` 之类）没有结束事件。不显式识别，一个 ``<br>`` 就把后面整页吞成
   它的子元素；
2. **闭合标签对不上**时要能恢复，且**不能**改错父级链；
3. **文本归属**：一个元素的文本要含子孙的文本，否则"卡片文本里找地点"永远找不到。
"""
from __future__ import annotations

from app.services.sites.official.generic.dom import VOID_ELEMENTS, parse_document


def _tags(document) -> list[str]:
    return [element.tag for element in document.elements]


def document_text(markup: str) -> str:
    """整页文本（把根元素拼起来）。"""
    document = parse_document(markup)
    return " ".join(document.text(i) for i in range(len(document)) if document.elements[i].parent < 0).strip()


# ===== 层级记账 =====


def test_void_elements_do_not_swallow_the_rest_of_the_page():
    """**这一条不做就全错**：``<br>`` 只有起始事件，压在栈上不弹，后面整页都成了它的子孙。"""
    document = parse_document("<ul><li>甲<br>乙</li></ul><div id='after'>后</div>")

    div = _tags(document).index("div")
    li = _tags(document).index("li")
    assert document.elements[div].parent == -1, "br 之后的元素被吞进了 br 里"
    # 反过来也要对：br 之后、li 闭合之前的文本仍属于 li（吞掉了就会跑到 br 里）。
    assert document.text(li) == "甲 乙"


def test_all_void_tags_are_recognised():
    """名单少一个就会在那一页上整体错位，而错位的表现是"配方突然不匹配了"。"""
    assert {"br", "img", "input", "hr", "meta", "link", "source", "wbr"} <= VOID_ELEMENTS


def test_void_elements_still_appear_as_elements():
    """不压栈**不等于**丢掉：它们仍是元素（``<img alt>`` 这类属性有时就是线索）。"""
    document = parse_document("<div><img src='a.png'><span>甲</span></div>")

    assert "img" in _tags(document)


def test_unclosed_child_does_not_break_the_parent_chain():
    """``<div><span></div>``：span 没闭合。按"向上找到同名标签再一并弹出"恢复。"""
    document = parse_document("<div><span>甲</div><p>乙</p>")

    tags = _tags(document)
    div, p = tags.index("div"), tags.index("p")
    assert document.elements[p].parent == -1, "多出来的 span 让 p 挂到了 div 里"
    assert document.text(div) == "甲"


def test_stray_closing_tag_is_ignored():
    """凭空多出的 ``</div>`` 既不能改父级链，也不能让后面的解析整体偏移。"""
    document = parse_document("<div>甲</div></div><p>乙</p>")

    tags = _tags(document)
    assert document.elements[tags.index("p")].parent == -1


def test_relative_structure_survives_an_extra_wrapper():
    """**配方比的是相对结构**：整体多包一层，卡片与卡内元素的关系不该变。

    这正是"不建真 DOM 树"成立的前提——绝对深度可能算错，但页内各元素彼此一致。
    """
    flat = parse_document("<li><span class='loc'>北京</span></li>")
    wrapped = parse_document("<div><section><li><span class='loc'>北京</span></li></section></div>")

    flat_loc = _tags(flat).index("span")
    wrapped_loc = _tags(wrapped).index("span")
    # 从地点往上找 li 的步数，两个页面必须一样。
    assert len(flat.ancestors(flat_loc)) == 1
    assert len(wrapped.ancestors(wrapped_loc)) == 3
    assert wrapped.text(wrapped.ancestors(wrapped_loc)[1]) == "北京"


# ===== 文本归属 =====


def test_element_text_includes_descendants():
    """不含子孙文本的话，"在卡片里找地点"这类查询永远找不到东西。"""
    document = parse_document("<li class='card'><a href='/jobs/1'>岗位</a><span>北京</span></li>")

    card = _tags(document).index("li")
    assert "岗位" in document.text(card)
    assert "北京" in document.text(card)


def test_text_keeps_document_order_when_text_is_interleaved():
    """``<div>甲<span>乙</span>丙</div>``：甲与丙都直接属于 div。

    按元素分桶（先把每个元素的直接文本收集起来、再拼）会得到"甲丙 乙"——**顺序错了**，
    而错序的文本在配方里表现为"标题和地点搅在一起"，很难往解析层想。
    """
    document = parse_document("<div>甲<span>乙</span>丙</div>")

    assert document.text(0) == "甲 乙 丙"
    assert document.text(1) == "乙"


def test_ancestor_text_between_siblings_does_not_shift_the_ranges():
    """**踩过的坑**：``<ul>`` 自己的换行片段插在两个 ``<li>`` 中间。

    按"每个元素的归属"做前缀和来算区间时，祖先的片段会把范围整体推偏一位——表现是列表页上
    "标题读成了地点"，而它看起来跟解析层毫无关系。区间必须在解析时按元素的开合区间记下来。
    """
    document = parse_document(
        "<ul>\n  <li><a href='/jobs/1'>大模型工程师</a><span>北京</span></li>\n"
        "  <li><a href='/jobs/2'>算法工程师</a><span>上海</span></li>\n</ul>"
    )

    texts = {element.tag: [] for element in document.elements}
    for index, element in enumerate(document.elements):
        texts[element.tag].append(document.text(index))
    assert texts["li"] == ["大模型工程师 北京", "算法工程师 上海"]
    assert texts["a"] == ["大模型工程师", "算法工程师"]
    assert texts["span"] == ["北京", "上海"]


def test_text_whitespace_is_folded():
    document = parse_document("<li>\n  大模型   应用\n  <b>工程师</b>\n</li>")

    assert document.text(0) == "大模型 应用 工程师"


def test_script_and_style_text_is_dropped():
    """脚本内容混进标题候选会变成一条以代码开头的"岗位名"。"""
    document = parse_document(
        "<div><script>var a = 1;</script><style>.x{}</style><head><title>页</title></head>正文</div>"
    )

    text = document.text(0)
    assert text == "正文"
    assert "var a" not in text


def test_text_of_empty_element_is_empty_string():
    assert parse_document("<div></div>").text(0) == ""


# ===== 属性 =====


def test_placeholder_attributes_become_empty_strings():
    """``html.parser`` 对无值属性给 ``None``。留 ``None`` 会让下游在做字符串比较时炸掉。"""
    document = parse_document("<input disabled>")

    assert document.elements[0].attrs["disabled"] == ""


def test_classes_are_split_and_blank_ones_dropped():
    document = parse_document("<div class='card  job-item '>x</div>")

    assert document.elements[0].classes == ("card", "job-item")
    assert parse_document("<div>y</div>").elements[0].classes == ()


def test_attr_names_preserves_order():
    document = parse_document("<a href='/x' data-id='7' class='c'>x</a>")

    assert document.elements[0].attr_names == ("href", "data-id", "class")


# ===== 遍历 =====


def test_ancestors_are_parent_first():
    document = parse_document("<div id='a'><section id='b'><span>x</span></section></div>")

    chain = document.ancestors(_tags(document).index("span"))
    assert [document.elements[i].attrs["id"] for i in chain] == ["b", "a"]


def test_descendants_are_in_document_order():
    document = parse_document("<div><i>1</i><b><u>2</u></b><em>3</em></div>")

    order = [_tags(document)[i] for i in document.descendants(0)]
    assert order == ["i", "b", "u", "em"]


def test_hrefs_are_in_document_order_and_skip_empties():
    document = parse_document(
        "<a href='/jobs/2'>二</a><a>无</a><a href='  '>空</a><a href='/jobs/1'>一</a>"
    )

    assert [href for _index, href in document.hrefs()] == ["/jobs/2", "/jobs/1"]


# ===== 容错 =====


def test_garbage_input_does_not_raise():
    """页面再乱也只是匹配不上，不该让整页采集失败。"""
    assert len(parse_document("")) == 0
    assert len(parse_document("纯文本，没有任何标签")) == 0
    # ``<`` 后面不是字母时按文本处理（浏览器也是这么做的），不会凭空造出元素。
    assert _tags(parse_document("<div><<<>>>")) == ["div"]


def test_partial_result_is_kept_when_parsing_explodes():
    """解析中途出错时保留已解出的部分——丢掉整页等于漏掉这一页上的所有岗位。"""
    document = parse_document("<div>甲</div>" + "\x00" * 10)

    assert "div" in _tags(document)


def test_an_omitted_head_end_tag_does_not_eat_the_page():
    """``</head>`` **可以省略**（HTML 规范允许），而解析器不做隐式闭合。

    真出现这种写法时，跳过深度会停在 1 再也不减回去，**整页所有元素的文本都变成空串**。
    表现是"这站的链接没有文字"——没人会想到是解析层；后果是默认配方与存下来的配方在这一站
    全部失效，每次都调模型且永远归纳不出配方。
    """
    without_head_end = "<html><head><title>页</title><body><a href='/jobs/1'>岗位</a></body></html>"
    with_head_end = "<html><head><title>页</title></head><body><a href='/jobs/1'>岗位</a></body></html>"

    assert document_text(without_head_end) == document_text(with_head_end) == "岗位"


def test_script_text_is_still_dropped_after_that_change():
    """去掉 head 不能把要挡的东西一起放进来。"""
    assert document_text("<div><script>var a=1</script>正文</div>") == "正文"
    assert document_text("<div><title>页标题</title>正文</div>") == "正文"


def test_own_text_excludes_descendant_text():
    """``own_text`` 只要元素**自己**的那段文字。

    它存在的理由是正文抽取里的一种版式：``<div>正文文字<button>投递</button></div>``。
    要去掉按钮，就得能拿到"容器的直接文字 + 各子元素各自的文字"——只拿子元素会把那段
    直接文字整个丢掉（``text()`` 又做不到，它把子孙也算进来）。
    """
    document = parse_document("<div>正文文字<button><span>投递</span></button></div>")
    div = 0

    assert document.own_text(div) == "正文文字"
    assert "投递" in document.text(div)


def test_own_text_keeps_pieces_between_children():
    """夹在子元素**之间**的那些片段也是父元素自己的（``<ul>`` 里两个 ``li`` 之间的换行）。

    这条与 ``text()`` 的区间记账是同一个坑：父元素的片段会插在子元素的片段中间，
    按"减掉所有子区间"取是对的，按"取第一个子元素之前的那一段"是错的。
    """
    document = parse_document("<ul>\n<li>甲</li>\n<li>乙</li>\n</ul>")
    ul = 0

    assert document.own_text(ul).strip() == ""
    assert document.text(ul) == "甲 乙"
