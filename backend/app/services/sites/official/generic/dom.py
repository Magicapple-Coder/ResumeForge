"""把网页解析成"元素表 + 父子关系"，供结构签名匹配使用。

**为什么不建真正的 DOM 树**：HTML 的隐式闭合规则（``<p>`` 闭合 ``<p>``、``<li>`` 闭合
``<li>``、表格元素互相约束）是解析里最琐碎的一块，而这一层**不需要**它。配方要回答的只有
两个问题——"哪些元素像岗位条目"和"条目里哪个元素是地点"——两件事都只看标签名、class、
属性名与**相对**层级；而相对层级用 ``html.parser`` 给的起始/结束事件就能准确记账。

于是错的嵌套不影响判据：一个多出来的 ``</div>`` 会让其后的元素整体少算一层，而它们在
**同一个页面内**彼此仍然一致。配方比的正是元素之间的相对结构，不是绝对深度。

**两个必须处理的解析现实**（不处理会让层级整体错位，而错位在配方侧表现为"什么都匹配不上"）：

- **空元素**（``<br>`` ``<img>`` ``<input>`` …）只有起始事件、永远没有结束事件。不显式
  识别它们，一个 ``<br>`` 就会把后面整页吞成它的子元素。
- **闭合标签对不上**（``<div><span></div>``）：按"向上找到同名标签再一并弹出"恢复，
  找不到就忽略——忽略比强行弹出安全，它不会把父级链改错。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser

# 自闭合元素：只有起始事件。见模块说明。
VOID_ELEMENTS = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr",
    }
)

# 这些标签里的内容不是给用户看的文本，连文本一起丢掉（否则标题候选里会混进脚本）。
#
# **``head`` 不在名单里**：它的结束标签**可以省略**（HTML 规范允许，紧跟 body 内容时浏览器
# 隐式闭合），而 ``html.parser`` 不做隐式闭合——真出现省略写法时，``_skip_text_depth`` 会停在
# 1 再也不减回去，**整页所有元素的文本都变成空串**。表现是"这站的链接没有文字"，没人会想到
# 是解析层；后果是默认配方与存下的配方在这一站全部失效，每次都调模型且永远归纳不出配方。
# 要挡的东西（``title`` / ``script`` / ``style``）已经各自在名单里，``head`` 本身没有可挡的。
_SKIP_TEXT_TAGS = frozenset({"script", "style", "noscript", "title"})


@dataclass
class Element:
    """一个起始标签。``parent`` 为 ``-1`` 表示它是文档根的直接子元素。"""

    tag: str
    attrs: dict[str, str]
    parent: int
    children: list[int] = field(default_factory=list)

    @property
    def classes(self) -> tuple[str, ...]:
        """空格分隔的 class 列表。空串被丢掉——``class="a  "`` 不该产生一个空类名。"""
        return tuple(part for part in self.attrs.get("class", "").split() if part)

    @property
    def attr_names(self) -> tuple[str, ...]:
        return tuple(self.attrs)


class _TreeBuilder(HTMLParser):
    """解析成元素表。

    **元素下标就是文档序（前序）**：起始标签的出现顺序恰好是前序遍历，而前序遍历里
    "一棵子树"对应一段**连续**下标。文本查询靠这条性质做区间求和，见 ``Document.text``。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[Element] = []
        # 按文档序的文本片段。**不按元素分桶**：``<div>甲<span>乙</span>丙</div>`` 里"甲"与
        # "丙"都属于 div，分桶再拼回来会失序。
        self.text_pieces: list[str] = []
        # 每个元素的片段区间 ``[start, end)``。见 ``Document.text`` 的说明。
        self.piece_start: list[int] = []
        self.piece_end: list[int] = []
        self._closed: list[bool] = []
        self._stack: list[int] = []
        self._skip_text_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TEXT_TAGS:
            self._skip_text_depth += 1
        parent = self._stack[-1] if self._stack else -1
        index = len(self.elements)
        self.elements.append(
            Element(tag=tag, attrs={name: (value or "") for name, value in attrs}, parent=parent)
        )
        self.piece_start.append(len(self.text_pieces))
        self.piece_end.append(len(self.text_pieces))
        # 空元素永远不会有结束事件，直接当成已闭合：不然收尾时会把后面的文本都算进它名下。
        self._closed.append(tag in VOID_ELEMENTS)
        if parent >= 0:
            self.elements[parent].children.append(index)
        if tag not in VOID_ELEMENTS:
            self._stack.append(index)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TEXT_TAGS and self._skip_text_depth > 0:
            self._skip_text_depth -= 1
        # 向上找到同名标签再一并弹出：``<div><span></div>`` 里的 span 因此不会留在栈上。
        for position in range(len(self._stack) - 1, -1, -1):
            if self.elements[self._stack[position]].tag == tag:
                for popped in self._stack[position:]:
                    self.piece_end[popped] = len(self.text_pieces)
                    self._closed[popped] = True
                del self._stack[position:]
                return
        # 找不到对应的起始标签：忽略。强行弹一个会改错父级链。

    def handle_data(self, data: str) -> None:
        if self._skip_text_depth or not self._stack:
            return
        self.text_pieces.append(data)

    def finalize(self) -> None:
        """给**没闭合**的元素补上区间终点。

        省略 ``</li>`` ``</p>`` 在真实页面上很常见；不补的话它们的文本是空的，
        表现就是"这一页读不出岗位"，而原因跟配方毫无关系。
        空元素已经在开标签时记为已闭合，不受这里影响。
        """
        end = len(self.text_pieces)
        for index, closed in enumerate(self._closed):
            if not closed:
                self.piece_end[index] = end


class Document:
    """解析结果。所有查询都按**文档序**返回，因此同一份输入必然给出同一个答案。"""

    def __init__(
        self,
        elements: list[Element],
        pieces: list[str],
        piece_start: list[int],
        piece_end: list[int],
    ) -> None:
        self.elements = elements
        self._pieces = pieces
        self._piece_start = piece_start
        self._piece_end = piece_end
        self._subtree_end = self._compute_subtree_ends()

    def _compute_subtree_ends(self) -> list[int]:
        """每个元素的子树在文档序里的**开区间终点**（不含）。

        自底向上累加：一个元素的子树 = 它自己 + 各子元素的子树；子元素的下标一定大于父元素，
        所以**倒着遍历一遍**就够，不需要递归。取 ``max`` 而不是求和——前序里子元素的子树本身
        就是连续的，最后一个子元素的终点即父元素的终点。
        """
        ends = [index + 1 for index in range(len(self.elements))]
        for index in range(len(self.elements) - 1, -1, -1):
            for child in self.elements[index].children:
                ends[index] = max(ends[index], ends[child])
        return ends

    def __len__(self) -> int:
        return len(self.elements)

    def text(self, index: int) -> str:
        """该元素的完整文本（含所有子孙），空白已折叠。

        区间在**解析时**就记好了：元素打开到闭合之间产生的每一个文本片段都属于它或它的子孙，
        且这段区间在整个片段序列里是连续的。于是这里只是一次切片。

        （曾经用"按归属元素做前缀和"来算，那是错的：祖先自己的文本片段会插在子元素片段
        之间——``<ul>\\n<li>甲</li>\\n<li>乙</li></ul>`` 里 ul 的换行片段就在两个 li 中间，
        前缀和会把范围整体算偏，表现为"标题读成了地点"。）

        片段之间补一个空格：``<b>大模型</b>工程师`` 直接拼接会得到"大模型工程师"，
        而对英文（``View<b> More</b>``）拼接会把词粘在一起。空格对中文只是略多余，
        且所有比较都做**忽略空白**的归一化，所以这里选信息更全的一侧。
        """
        return " ".join(" ".join(self._pieces[self._piece_start[index] : self._piece_end[index]]).split())

    def own_text(self, index: int) -> str:
        """该元素**自己的**文本（**不含**任何子孙元素的文字）。

        与 ``text()`` 的区别只在"要不要子孙"：``<div>正文<a>链接</a></div>`` 的 ``text()``
        是"正文 链接"，这里是"正文"。

        片段区间在解析时按文档序记录，子元素直接列在 ``children`` 里且区间互不重叠，所以
        自己的片段就是"父区间减去各个子区间之后剩下的那几段"——包括夹在子元素之间的那些
        （``<ul>\\n<li>甲</li>\\n<li>乙</li></ul>`` 里的换行）。
        """
        start, end = self._piece_start[index], self._piece_end[index]
        parts: list[str] = []
        cursor = start
        for child in self.elements[index].children:
            child_start, child_end = self._piece_start[child], self._piece_end[child]
            if child_start > cursor:
                parts.extend(self._pieces[cursor:child_start])
            cursor = max(cursor, child_end)
        if end > cursor:
            parts.extend(self._pieces[cursor:end])
        return " ".join(" ".join(parts).split())

    def ancestors(self, index: int) -> list[int]:
        """从**父**到根，由近及远。"""
        chain: list[int] = []
        current = self.elements[index].parent
        while current >= 0:
            chain.append(current)
            current = self.elements[current].parent
        return chain

    def descendants(self, index: int) -> list[int]:
        """文档序的全部子孙。"""
        return list(range(index + 1, self._subtree_end[index]))

    def subtree_end(self, index: int) -> int:
        """该元素子树在文档序里的开区间终点（不含）。用于"某个元素是不是在它里面"。"""
        return self._subtree_end[index]

    def contains(self, ancestor: int, index: int) -> bool:
        return ancestor <= index < self._subtree_end[ancestor]

    def hrefs(self) -> list[tuple[int, str]]:
        """文档序的 ``(元素下标, href)``。只收带非空 ``href`` 的 ``<a>``。"""
        found: list[tuple[int, str]] = []
        for index, element in enumerate(self.elements):
            if element.tag != "a":
                continue
            href = element.attrs.get("href", "").strip()
            if href:
                found.append((index, href))
        return found


def parse_document(markup: str) -> Document:
    """解析网页。**再乱也不抛**：解析失败时返回已解出的那部分，而不是丢掉整页。"""
    builder = _TreeBuilder()
    if markup:
        try:
            builder.feed(markup)
            builder.close()
        except Exception:  # noqa: BLE001 - 页面再乱也只是匹配不上，不该让采集整页失败
            pass
    builder.finalize()
    return Document(
        builder.elements, builder.text_pieces, builder.piece_start, builder.piece_end
    )


__all__ = ["VOID_ELEMENTS", "Document", "Element", "parse_document"]
