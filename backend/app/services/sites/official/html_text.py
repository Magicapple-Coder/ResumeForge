"""把**已知是正文**的 HTML 片段转成纯文本。

**为什么不用搜索层的 ``page_reader.extract_text``**：它的契约是"在一个完整网页里*找出*正文"，
因此带一条启发式——太短的段落当作导航丢弃（阈值 20 字符）。招聘接口给的 ``content`` 字段里
我们已经**知道**那就是职位描述，对它套用"找正文"的启发式是范畴错误：一段写得很短的要求
（"熟悉 Python。"）会被整段吃掉，而岗位描述恰恰是这一层最不能丢的东西。

两边的契约因此是不同的，各自一份实现是有意的：
- ``extract_text``：给我一个网页，我猜哪部分像正文；
- ``html_to_text``：这**就是**正文，把标记去掉。
"""
from __future__ import annotations

from html.parser import HTMLParser

# 这些标签里的内容不是正文（保留标记语言、脚本与样式）。
_SKIP_TAGS = frozenset({"script", "style", "noscript", "head"})
# 遇到这些标签要换行：职位描述的分段靠的就是它们，全部拼成一行会让"职责/要求"糊在一起。
_BLOCK_TAGS = frozenset(
    {
        "p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article",
        "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "hr",
    }
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self.parts.append(data)


def html_to_text(markup: str, *, max_chars: int = 20_000) -> str:
    """去标记、折叠空白、按段落拼回纯文本，按字符上限截断。

    页面再乱也不抛：解析失败时退回"原样返回去掉标签的粗结果"，而不是丢掉整段描述。
    """
    if not markup:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:  # noqa: BLE001 - 描述再乱也不该让一条岗位取不回来
        return " ".join(markup.split())[:max_chars]

    lines = [" ".join(line.split()) for line in "".join(parser.parts).split("\n")]
    text = "\n".join(line for line in lines if line)
    return text[:max_chars]


__all__ = ["html_to_text"]
