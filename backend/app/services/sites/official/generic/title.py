"""岗位标题的确定性清洗与卡片内回退。

通用配方默认把岗位链接的文字当标题，但有些站点把整张卡片包进 ``<a>``：这时链接文字会
同时包含地点、类型、岗位 ID 甚至完整职位描述。这个模块只在默认标题明显过长时，按卡片内
元素的结构特征寻找更像标题的短文本，不依赖某一家公司的选择器。
"""
from __future__ import annotations

from .dom import Document

MAX_TITLE_CHARS = 200
MIN_TITLE_CHARS = 2

_TITLE_STOPWORDS = frozenset(
    {
        "详情", "查看", "查看详情", "了解更多", "更多", "阅读全文", "立即申请", "申请",
        "投递", "投递简历", "申请职位", "应聘", "报名", "进入", "下一页", "上一页",
        "more", "view", "view more", "read more", "details", "detail", "apply",
        "apply now", "see more", "learn more", "next", "prev", "back",
        "职位描述", "岗位职责", "任职要求", "工作职责", "工作内容", "岗位要求", "福利待遇",
    }
)

_TITLE_HINTS = {
    "title": 4,
    "position": 3,
    "job": 3,
    "role": 3,
    "opening": 2,
    "vacancy": 2,
    "name": 2,
}

_NON_TITLE_HINTS = {
    "subtitle": 5,
    "sub-title": 5,
    "description": 5,
    "desc": 5,
    "jobdesc": 8,
    "location": 4,
    "category": 3,
    "salary": 3,
    "company": 3,
    "datetime": 3,
    "date": 3,
    "time": 3,
    "type": 3,
    "id": 3,
}


def tidy_title(text: str) -> str:
    """折叠页面文本中的换行和重复空白。"""
    return " ".join((text or "").split())


def is_usable_title(text: str) -> bool:
    """判断文本是否足够像一条可以入库的岗位名。"""
    cleaned = tidy_title(text)
    if not (MIN_TITLE_CHARS <= len(cleaned) <= MAX_TITLE_CHARS):
        return False
    if cleaned.casefold() in _TITLE_STOPWORDS:
        return False
    return any(char.isalnum() for char in cleaned)


def _hint_score(document: Document, index: int) -> int:
    element = document.elements[index]
    markers = " ".join(
        (*element.classes, *element.attrs.keys(), *[
            value for name, value in element.attrs.items() if name.casefold().startswith("data-")
        ])
    ).casefold()
    score = sum(weight for marker, weight in _TITLE_HINTS.items() if marker in markers)
    score -= sum(weight for marker, weight in _NON_TITLE_HINTS.items() if marker in markers)
    if element.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        score += 3
    return score


def refine_card_title(document: Document, *, title_index: int, card: int) -> str:
    """默认标题过长时，从同一张卡片里找结构上更像岗位名的文本。"""
    current = tidy_title(document.text(title_index))

    # 操作文案必须原样返回，交给调用方的可用性判断丢掉它。否则一个把
    # ``查看详情`` 放进链接、同时又在卡片里放了 ``h3`` 的页面，会被误
    # 修成那个 h3，进而绕过后面的模型兜底。
    if current.casefold() in _TITLE_STOPWORDS:
        return current

    # 普通短锚文本就是标题，不要因为卡片里碰巧存在 ``h3`` 或带有
    # ``title`` class 的元素而改写它。只有明显超过上限的整卡片文本才
    # 进入结构化回退。
    if len(current) <= MAX_TITLE_CHARS:
        return current

    candidates: list[tuple[int, int, int, str]] = []
    for index in document.descendants(card):
        if index == title_index:
            continue
        text = tidy_title(document.text(index))
        if not is_usable_title(text):
            continue
        score = _hint_score(document, index)
        if score <= 0:
            continue
        candidates.append((score, -len(text), len(document.ancestors(index)), text))

    if not candidates:
        return current
    candidate = max(candidates)[-1]
    # 卡片可能刚好没有超过 200 字，但链接文字仍包含地点、类型或职位 ID。只要卡片内有
    # 明确的标题结构，就优先用它；普通的纯锚文本没有这类候选，因此保持原行为。
    return candidate if candidate != current or not is_usable_title(current) else current


__all__ = [
    "MAX_TITLE_CHARS",
    "MIN_TITLE_CHARS",
    "is_usable_title",
    "refine_card_title",
    "tidy_title",
]
