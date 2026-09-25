"""从详情页的 DOM 里读出**正文**（职位描述 / 任职要求）。

**它填的是一个一直空着的洞**：四级抽取里只有结构化数据（JSON-LD）会带正文，而默认配方、
学到的配方、模型三级都只给标题与地点——于是"没有 JSON-LD、JD 就摆在页面上"的站点（国内自建
招聘站几乎都是）采到的岗位**只有标题**。实测一家：55 条里 52 条没有正文，而这些岗位后面要拿去做
技能标签、岗位匹配、简历生成、面试准备——没有正文，这条链路的下游等于空转。

**为什么必须是确定性的、免费的**：详情页是**每一条岗位一页**。把模型放到这一级等于"五十个详情页
各问一次模型"——那正是 ``MAX_LLM_CALLS_PER_RUN`` 存在的理由（用户自付 key）。所以这一级只做
"按页面自己写的章节标题把段落取出来"。

## 判据复用仓库已有的词表

章节标题的识别直接用 ``app/services/job_parser/section_constants.py`` 里那套中英文标题正则
（约 50 个模式：「职位描述 / 岗位职责 / 任职要求 / Responsibilities / Qualifications」…）。
**不另造一套**：那里已经为"把 JD 文本切成章节"调好了一整套别名，再造一份必然与它漂移，
而漂移的表现是"同一个页面，一处认得出一处认不出"。

## 两条实测出来的硬约束（都拿真实页面验过）

1. **窗口不能越过祖先边界**。只按"遇到下一个标题才停"取兄弟节点的话，最后一个章节会一路吃到
   页脚——实测某站因此把「相关职位」里 50 条别的岗位全并了进来。
2. **三类标题都要参与边界判断，但只收集其中两类**。「福利待遇 / 公司介绍 / 联系方式」这些
   不在收集范围内（它们对应 ``additional_info``，见下），可是**必须当终止符**：不认它们的话，
   「福利待遇：……」整段会被粘进职位描述里。

## 它守的底线是"宁可为空"

一段错的正文比没有正文糟得多：它会被下游当成 JD 去做匹配与简历定制，而错得又不像错。
所以每条规则都往"取不到就返回空串"的方向倒——窗口太短不算命中、空窗口不算命中、
取不到任何一段就返回空 ``PageBody``。
"""
from __future__ import annotations

from dataclasses import dataclass

from ....job_parser.section_constants import (
    _ADDITIONAL_HEADING_RE,
    _DESCRIPTION_HEADING_RE,
    _REQUIREMENTS_HEADING_RE,
)
from .dom import Document, parse_document
from .recipe import tidy

# 一段正文的长度上限，与结构化数据那条路取同一个值（``jsonld._MAX_TEXT_CHARS``）——
# 两条路喂给下游的是同一个字段，上限不同会让"这条岗位的正文为什么被截了"变成随机现象。
MAX_BODY_CHARS = 20_000

# 短于这个长度就不算正文。它挡的是"标题下只有一句『详见附件』"这类页面：取回来也没用，
# 而下游会把这段残句当成完整 JD 去解析。
MIN_BODY_CHARS = 20

# 一个元素自己的文字短于这个长度才可能是章节标题。真实标题都很短（"职位描述"四个字），
# 而正文段落常常以同样的词开头——不设这个上限，"职位描述：负责……（三百字）"整段会被
# 当成标题，于是它下面的内容反而取不到了。
MAX_HEADING_CHARS = 30

# 标题取不到内容时最多向上找几层。需要上溯的情形：标题与正文分属两个包裹层
# （``<div><h3>职位描述</h3></div><div>正文</div>``），此时标题的父元素里只有标题自己。
# 3 层够覆盖见过的版式，再多就是在往外爬整页容器了。
MAX_ANCESTOR_STEPS = 3

# 章节类别。``other``（福利待遇 / 公司介绍 / 联系方式…）**只当边界，不收集**：
# 它们不是职位描述，混进来会让下游把公司福利当成岗位要求去做匹配。
_KIND_DESCRIPTION = "description"
_KIND_REQUIREMENTS = "requirements"
_KIND_OTHER = "other"

_HEADING_PATTERNS = (
    (_KIND_DESCRIPTION, _DESCRIPTION_HEADING_RE),
    (_KIND_REQUIREMENTS, _REQUIREMENTS_HEADING_RE),
    (_KIND_OTHER, _ADDITIONAL_HEADING_RE),
)

# 取正文时要跳过的元素：按钮是页面控件，不是 JD 的一部分。实测某站的「投递」按钮与
# 最后一节正文同属一个容器，不跳过就会得到一句"……英文流利，有雅思/托福分数更佳。 投递"。
_SKIP_TAGS = frozenset({"button", "script", "style", "noscript"})


@dataclass(frozen=True)
class PageBody:
    """这一页作为一条岗位时，它自己的正文两段。取不到就是空串（**不是 None**）。"""

    description: str = ""
    requirements: str = ""

    def __bool__(self) -> bool:
        return bool(self.description or self.requirements)


def extract_page_body(markup: str, *, max_chars: int = MAX_BODY_CHARS) -> PageBody:
    """从渲染后的页面里取正文。**从不抛异常**：取不到是一级结论，不是故障。"""
    if not markup:
        return PageBody()
    document = parse_document(markup)
    if not len(document):
        return PageBody()

    headings = _headings(document)
    if not headings:
        return PageBody()

    found: dict[str, str] = {}
    for position, (index, kind) in enumerate(headings):
        if kind == _KIND_OTHER or kind in found:
            # ``other`` 只用来划边界；同一个字段只认**第一次**出现的那一节——一篇 JD 里
            # 出现两个「职位描述」时，靠后的那个多半是"相关职位"那类区块里的标签。
            continue
        stop = headings[position + 1][0] if position + 1 < len(headings) else len(document)
        text = _window_text(document, index, stop=stop)
        if text:
            found[kind] = text[:max_chars]

    return PageBody(
        description=found.get(_KIND_DESCRIPTION, ""),
        requirements=found.get(_KIND_REQUIREMENTS, ""),
    )


def _heading_kind(text: str) -> str:
    """元素自己的文字整段就是一个章节标题吗。是的话返回类别，否则空串。

    **必须整段匹配**（``content`` 组为空）：不然"职位描述"这四个字出现在正文句首时，
    那一段正文会被当成标题——它下面的内容反而取不到。
    """
    cleaned = text.strip()
    if not cleaned or len(cleaned) > MAX_HEADING_CHARS:
        return ""
    for kind, pattern in _HEADING_PATTERNS:
        matched = pattern.match(cleaned)
        if matched is not None and not matched.group("content").strip():
            return kind
    return ""


def _headings(document: Document) -> list[tuple[int, str]]:
    """按文档序找出所有章节标题 ``(元素下标, 类别)``。

    **三类都在列**（含 ``other``）：它们首先是**边界**——见模块说明第 2 条。
    """
    found: list[tuple[int, str]] = []
    for index in range(len(document)):
        element = document.elements[index]
        if element.tag in _SKIP_TAGS:
            continue
        kind = _heading_kind(document.text(index))
        if kind:
            found.append((index, kind))
    return found


def _window_text(document: Document, index: int, *, stop: int) -> str:
    """标题之后、到下一个标题为止的正文。取不到返回空串。

    ``stop`` 是下一个标题的元素下标（**越不过去**：那是下一节的开头）。此外还有一道边界：
    标题所在祖先元素的子树末尾——没有它，最后一个章节会一路吃到页脚（模块说明第 1 条）。
    """
    limit = stop
    current = index
    for _ in range(MAX_ANCESTOR_STEPS):
        parent = document.elements[current].parent
        if parent < 0:
            return ""
        start = document.subtree_end(current)
        end = min(document.subtree_end(parent), limit)
        if end > start:
            text = tidy(" ".join(
                _text_without_controls(document, child)
                for child in _top_level(document, start, end)
            ))
            if len(text) >= MIN_BODY_CHARS:
                return text
        # 这一层里没内容（标题与正文分属两个包裹层的版式）：**把窗口上移一层再试**，
        # 从"父元素之后"接着取，而 ``limit`` 不动——下一个标题管着所有层。
        current = parent
    return ""


def _text_without_controls(document: Document, index: int) -> str:
    """这个元素的文本，但**去掉**页面控件（按钮之类）那部分。

    只按标签跳过整棵子树是不够的：控件往往被包在正文容器里（实测那个「投递」按钮与最后一节
    正文同属一个 ``<div>``），取容器文本时它照样被带出来。所以子树里一有控件就改成往下钻：
    **元素自己的片段 + 各子元素各自的干净文本**。

    "自己的片段"这一半不能省——``<div>正文文字<button>投递</button></div>`` 里那段文字是
    容器的**直接文本**，只拼子元素会把它整个丢掉（这一条正是测试先写出来才发现的）。
    """
    if document.elements[index].tag in _SKIP_TAGS:
        return ""
    has_control = any(
        document.elements[child].tag in _SKIP_TAGS
        for child in document.descendants(index)
    )
    if not has_control:
        return document.text(index)
    return " ".join(
        [document.own_text(index)]
        + [_text_without_controls(document, child) for child in document.elements[index].children]
    )


def _top_level(document: Document, start: int, end: int) -> list[int]:
    """区间里**不被同区间其他元素包住**的那些元素下标。

    直接用区间内全部元素会重复：父元素与子元素的 ``text()`` 有重叠部分，拼起来会把同一段
    文字算两遍（这正是 ``Document.text()`` 当年踩过的那个坑）。
    """
    picked: list[int] = []
    for index in range(start, end):
        parent = document.elements[index].parent
        if start <= parent < end:
            continue
        if document.elements[index].tag in _SKIP_TAGS:
            continue
        picked.append(index)
    return picked


__all__ = ["MAX_BODY_CHARS", "PageBody", "extract_page_body"]
