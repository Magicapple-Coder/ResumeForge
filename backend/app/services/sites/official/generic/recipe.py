"""结构签名式抽取配方：把"这一页的岗位在哪"变成一份可复用、可校验、零模型的数据。

**为什么不是 CSS 选择器**（这是本阶段要拍的板）：

1. **生成方与匹配方是同一份契约。** 配方由本模块自己归纳、也由本模块自己执行，签名集合因此
   是闭合的——不会出现"配方里写了 ``:nth-child(2)``、匹配器不认识"这类**只在用户机器上**
   出现的问题。用通用 CSS 则要额外写一层校验，或者接受静默不匹配。
2. **相似度重定位本来就要打分匹配。** 站点改版后要按"像不像原来那个元素"去找，而 CSS 选择器
   是精确匹配——走那条路等于精确与模糊两套实现并存，而两套必然漂移。这里**一套**：先精确
   命中，不中再按相似度取最优。
3. **不引入新依赖。** ``start.cmd`` 的硬约束是"首次启动必须能在什么都没装的电脑上跑通"。
   开发机的虚拟环境里确实有 ``bs4`` / ``lxml``，但它们**没有写进 requirements.txt**，
   发布包里根本没有——依赖它们等于让功能只在开发机上成立。

**签名是三样东西**：标签名、class 集合、属性名集合。都是"页面结构"层面的特征，与文案无关
（文案会随岗位变，结构不会）。**标签是硬条件**——``div`` 不是 ``span``；class 与属性按
相似度打分，因为站点改版最先动的就是它们。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlsplit

from ..urls import looks_like_job_url
from .dom import Document, parse_document
from .title import MAX_TITLE_CHARS, MIN_TITLE_CHARS, is_usable_title, refine_card_title

# 配方格式版本。落库时一并存下：以后改结构能认出旧配方并走迁移，而不是拿新代码去读旧数据。
RECIPE_SCHEMA = 1

# 相似度阈值。含义是"**签名里一半的特征还在**"。低于它就不认为是同一个元素——
# 宁可判"配方失效"退回上一级，也不要硬匹配：硬匹配出来的值会一路进到用户的暂选列表里，
# 而"读不出来"至少是诚实的。
#
# 取一半而不是更高，是因为它**不影响最常见的那一类**：签名里的特征一个不少时，精确匹配
# （子集判定）早就命中了，轮不到相似度。这里放宽只影响"特征掉了一部分"的情形，而那种情形
# 本来就没有更好的判据。这个值没有实测数据支撑，是按"改版后还剩多少特征仍可辨认"定的。
MATCH_THRESHOLD = 0.5

# class 与属性的权重。class 更能说明"这是同一类元素"（``job-card`` 这种名字信息量大），
# 属性名次之（``data-id`` 这类每个站点都有）。
_CLASS_WEIGHT = 0.7
_ATTR_WEIGHT = 0.3

def tidy(text: str) -> str:
    """折叠空白但**保留词间的一个空格**。用于要**存下来**的文本。

    与 ``squash`` 的分工：``squash`` 删掉全部空白，只用于**比较**；拿它去存值会把
    ``Machine Learning Engineer`` 存成 ``MachineLearningEngineer``。
    """
    return " ".join((text or "").split())


def squash(text: str) -> str:
    """忽略空白的归一化。**所有文本比较都走它**。

    页面里的换行、缩进、标签之间的空白与模型回复里的写法不会完全一致，逐字比较会把好配方
    判成失效（表现是"每次都重新调模型"，用户只会看到账单变高）。
    """
    return "".join((text or "").split())


@dataclass(frozen=True)
class Signature:
    """一个元素的结构特征。空签名**不匹配任何东西**——见 ``similarity``。"""

    tag: str = ""
    classes: tuple[str, ...] = ()
    attrs: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.tag and not self.classes and not self.attrs

    def to_dict(self) -> dict[str, Any]:
        return {"tag": self.tag, "classes": list(self.classes), "attrs": list(self.attrs)}

    @classmethod
    def from_dict(cls, raw: Any) -> Signature:
        if not isinstance(raw, dict):
            return cls()
        return cls(
            tag=str(raw.get("tag") or "").casefold(),
            classes=tuple(str(item) for item in raw.get("classes") or () if str(item)),
            attrs=tuple(str(item) for item in raw.get("attrs") or () if str(item)),
        )


def _coverage(needed: tuple[str, ...], available: tuple[str, ...]) -> float:
    """**签名的特征还有多少在**（召回，不是 Jaccard）。

    用覆盖率而不是 Jaccard，是因为两者的失败方向不同：Jaccard 把"元素上多了几个 class"
    也算成不相似，而增补 class（``job-card`` → ``job-card job-card--wide``）恰恰是最常见的
    一种改版。判"相似"时要知道的是**原来那些特征还在不在**，元素多出来的部分不影响这个判断。
    """
    needed_set = set(needed)
    if not needed_set:
        return 0.0
    return len(needed_set & set(available)) / len(needed_set)


def signature_of(document: Document, index: int, *, with_classes: bool = True) -> Signature:
    """现场量一个元素的签名。

    ``with_classes=False`` 用于生成``标签 + 属性名``的退化签名：class 名是站点自己起的、
    改版最先换的就是它，所以某些字段（位置、时间）只认标签与属性反而更耐用。
    """
    element = document.elements[index]
    return Signature(
        tag=element.tag,
        classes=element.classes if with_classes else (),
        attrs=element.attr_names,
    )


def similarity(
    signature: Signature, element_tag: str, classes: tuple[str, ...], attrs: tuple[str, ...]
) -> float:
    """0~1 的相似度。用于站点改版后的重定位。

    **它治的是"签名的一部分特征消失了"**：``class="job-item full-time remote"`` 改版后只剩
    ``job-item``，覆盖率 1/3——仍达不到阈值，但两个里还剩一个时就能救回来。

    三件事**不归它管**，别指望：

    - **class 增补**：那种情况``matches`` 的子集判定已经命中了，轮不到相似度；
    - **改名**：``job-location`` 改成 ``loc-text`` 时没有任何信息能说明它们是同一个东西，
      分数如实低于阈值，配方判失效——**这是对的**，硬匹配会读出一个位置错误却看似正常的值；
    - **换标签**：``div`` 不是 ``span``，标签不等直接判 0。把"标签变了"当成"权重低一点"
      会让配方滑到某个碰巧也像的元素上。
    """
    if signature.is_empty:
        return 0.0
    if signature.tag and element_tag != signature.tag:
        return 0.0
    parts: list[tuple[float, float]] = []
    if signature.classes:
        parts.append((_CLASS_WEIGHT, _coverage(signature.classes, classes)))
    if signature.attrs:
        parts.append((_ATTR_WEIGHT, _coverage(signature.attrs, attrs)))
    if not parts:
        # 只有标签的签名：前面已确认标签相同，就是命中。
        return 1.0
    weight = sum(item[0] for item in parts)
    return sum(item[0] * item[1] for item in parts) / weight


def matches(signature: Signature, document: Document, index: int) -> bool:
    """精确命中：标签相同，且签名的 class 与属性都在元素上。"""
    if signature.is_empty:
        return False
    element = document.elements[index]
    if signature.tag and element.tag != signature.tag:
        return False
    return set(signature.classes) <= set(element.classes) and set(signature.attrs) <= set(
        element.attr_names
    )


def _score_at(signature: Signature, document: Document, index: int) -> float:
    element = document.elements[index]
    return similarity(signature, element.tag, element.classes, element.attr_names)


# 字段取值的四种范围。**相对岗位链接**而言，不写绝对路径——站点在中间插一层 wrapper 是
# 改版里最常见的一种，按绝对层级找会全断，而相对查找不受影响。
SCOPE_SELF = "self"
SCOPE_ANCESTORS = "ancestors"
# **卡片内**：地点、时间这些字段通常与链接是**兄弟**关系（``<li><a>岗位</a><span>北京</span></li>``），
# 既不在链接里也不在链接的祖先上。少了这一档，非 JSON-LD 站点只能读到标题。
SCOPE_CARD = "card"
SCOPE_DESCENDANTS = "descendants"
SCOPES = (SCOPE_SELF, SCOPE_ANCESTORS, SCOPE_CARD, SCOPE_DESCENDANTS)

# 向上找的最大层数。给得太大就会"找到页面顶部去"（导航栏里也有 span），
# 4 层足够覆盖"链接 → 标题 → 卡片"这种常见嵌套。
MAX_ANCESTOR_STEPS = 4

# 文本属性：直接取元素文本，其余按属性名取。
TEXT_ATTR = "text"


@dataclass(frozen=True)
class FieldRule:
    """一个字段怎么取：在哪找（``scope``）、找什么样的元素（``signature``）、取什么（``attr``）。"""

    scope: str = SCOPE_SELF
    signature: Signature = field(default_factory=Signature)
    attr: str = TEXT_ATTR

    def to_dict(self) -> dict[str, Any]:
        return {"scope": self.scope, "signature": self.signature.to_dict(), "attr": self.attr}

    @classmethod
    def from_dict(cls, raw: Any) -> FieldRule | None:
        if not isinstance(raw, dict):
            return None
        scope = str(raw.get("scope") or SCOPE_SELF)
        if scope not in SCOPES:
            return None
        return cls(
            scope=scope,
            signature=Signature.from_dict(raw.get("signature")),
            attr=str(raw.get("attr") or TEXT_ATTR),
        )


@dataclass(frozen=True)
class Recipe:
    """一份抽取配方。

    ``url_markers`` 为空表示"用通用的岗位地址判据"（``looks_like_job_url``）；非空表示这份
    配方是从模型给的地址里**学出来的**路径片段，适用于岗位地址长得不像 ``/jobs/123`` 的站点。
    """

    title: FieldRule = field(
        default_factory=lambda: FieldRule(scope=SCOPE_SELF, signature=Signature(tag="a"))
    )
    location: FieldRule | None = None
    posted_at: FieldRule | None = None
    url_markers: tuple[str, ...] = ()
    # 归纳自哪一页。只为展示与排查，**不参与匹配**——同一个站点的分页列表结构相同，
    # 按地址锁死会让第二页起用不上配方。
    source_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RECIPE_SCHEMA,
            "url_markers": list(self.url_markers),
            "source_url": self.source_url,
            "title": self.title.to_dict(),
            "location": self.location.to_dict() if self.location else None,
            "posted_at": self.posted_at.to_dict() if self.posted_at else None,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> Recipe | None:
        """从库里读回配方。**认不出来就返回 ``None``**，由调用方退回上一级。

        版本不符、字段缺失、结构怪——一律当作"没有配方"。返回一个半懂的配方比没有配方更危险：
        它会产出看似正常的结果，而没人知道该怀疑它。
        """
        if not isinstance(raw, dict) or raw.get("schema") != RECIPE_SCHEMA:
            return None
        title = FieldRule.from_dict(raw.get("title"))
        if title is None:
            return None
        return cls(
            title=title,
            location=FieldRule.from_dict(raw.get("location")),
            posted_at=FieldRule.from_dict(raw.get("posted_at")),
            url_markers=tuple(str(item) for item in raw.get("url_markers") or () if str(item)),
            source_url=str(raw.get("source_url") or ""),
        )


@dataclass(frozen=True)
class ExtractedJob:
    """配方从页面上读到的一条岗位。字段与 ``FeedJob`` 对齐，但**保持独立**：

    配方层不该知道采集层的数据结构，它只回答"这一页上读到什么"。
    """

    url: str
    title: str
    location: str = ""
    posted_at: str = ""


def _value_at(document: Document, index: int, rule: FieldRule) -> str:
    element = document.elements[index]
    if rule.attr == TEXT_ATTR:
        return document.text(index)
    return element.attrs.get(rule.attr, "").strip()


def card_of(document: Document, anchor: int, *, link_urls: dict[int, str]) -> int:
    """岗位链接所在的**卡片**：包含这个链接、却不再包含**别的岗位**的那个最大的元素。

    这条定义比"父元素"或"第 N 层祖先"都稳：链接常常裹在 ``<h3><a>`` 里，父元素是标题而不是
    卡片；而"往外走一步就会框进邻居"的那一层恰好就是卡片。

    **按去重后的地址计数，不按链接个数**：卡片里常有第二个指向同一个岗位的链接（"申请"
    按钮），按个数算会把它当成邻居，卡片于是塌成链接自己，地点与时间就都读不到了。

    **卡片在现场重算、不进配方**：站点改版时卡片本身会变，而这条规则不依赖任何 class 名，
    改版后照样成立。找不到卡片时返回链接自身——那时字段读不到，如实留空。
    """
    current = anchor
    while True:
        parent = document.elements[current].parent
        if parent < 0:
            return current
        start, end = parent, document.subtree_end(parent)
        inside = {
            url for index, url in link_urls.items() if start <= index < end
        }
        if len(inside) > 1:
            return current
        current = parent


def _find(document: Document, anchor: int, rule: FieldRule, *, card: int | None = None) -> int | None:
    """按范围找元素：先精确命中，不中再按相似度取最优（这就是改版后的重定位）。

    两道判据各管一段，合起来才是完整的重定位：

    - **精确命中**（子集判定）管"多了东西"：class 增补、属性增删都还是同一个元素；
    - **相似度**管"少了东西"：签名里的特征掉了一部分时仍认得出。

    两段都过不去就返回 ``None``——**不硬匹配**。读不出来是诚实的（下游会如实报告这条没有
    该字段），而硬匹配出来的是一个位置错误却看似正常的值。
    """
    if rule.scope == SCOPE_SELF:
        return anchor if matches(rule.signature, document, anchor) else None

    if rule.scope == SCOPE_ANCESTORS:
        candidates = document.ancestors(anchor)[:MAX_ANCESTOR_STEPS]
    elif rule.scope == SCOPE_CARD:
        if card is None:
            return None
        candidates = [card, *document.descendants(card)]
    else:
        candidates = document.descendants(anchor)

    for index in candidates:
        if matches(rule.signature, document, index):
            return index
    best, best_score = None, MATCH_THRESHOLD
    for index in candidates:
        score = _score_at(rule.signature, document, index)
        if score >= best_score:
            best, best_score = index, score
    return best


def link_candidates(document: Document, *, url_markers: tuple[str, ...] = ()) -> list[tuple[int, str]]:
    """页面里的候选链接元素。``url_markers`` 为空时不做地址层面的筛选。

    ``url_markers`` 的匹配**只在这里**发生，且是"地址里含这个片段"。学出来的片段可能是
    ``/`` 这种过于宽泛的东西，所以归纳阶段会用重放校验把它筛掉（见 ``induce``）。
    """
    found: list[tuple[int, str]] = []
    for index, href in document.hrefs():
        if not url_markers:
            found.append((index, href))
            continue
        folded = href.casefold()
        if any(marker.casefold() in folded for marker in url_markers):
            found.append((index, href))
    return found


def page_base(document: Document, page_url: str) -> str:
    """页面里声明了 ``<base href>`` 时以它为准——站内页面用它很常见，忽略会让相对链接全拼错。"""
    first_base = next(
        (element for element in document.elements if element.tag == "base"), None
    )
    if first_base is None:
        return page_url
    href = first_base.attrs.get("href", "").strip()
    return urljoin(page_url, href) if href else page_url


def extract_with_recipe(recipe: Recipe, markup: str, *, page_url: str) -> list[ExtractedJob]:
    """用配方读一页。

    **读不出就返回空列表**，不抛异常、不猜：调用方据此退回上一级（默认配方 → 模型）。

    地址的取舍在这里一次做完（相对地址、``<base>``、同主机、"像不像岗位页"），调用方不需要
    自己拼一套——两处各判一次的结果是"清单里认成岗位页、抽取时又认不出来"这类只有用户会
    撞上的偏差。
    """
    document = parse_document(markup)
    if not len(document):
        return []

    base = page_base(document, page_url)
    host = (urlsplit(base).hostname or "").casefold()
    if not host:
        return []

    # 第一遍：把合格的目标地址挑出来。卡片的判据要用它（"这一层里还有没有别的岗位"），
    # 所以必须先定下来——卡片是链接之间的相对位置，一边过滤一边算会得到自相矛盾的结果。
    accepted: list[tuple[int, str]] = []
    seen: set[str] = set()
    for index, href in link_candidates(document, url_markers=recipe.url_markers):
        try:
            url = urljoin(base, href).split("#", 1)[0]
        except ValueError:
            # 一个畸形链接不该让整页读不出来。
            continue
        if not url or url in seen:
            continue
        if (urlsplit(url).hostname or "").casefold() != host:
            # 只认同主机：跨站的多半是社交分享、母公司官网、招聘平台外链。
            continue
        if not recipe.url_markers and not looks_like_job_url(url, page_host=host):
            continue
        seen.add(url)
        accepted.append((index, url))

    # 同一个岗位地址可能出现在多个链接上（标题一个、"申请"一个），卡片判据按地址去重。
    link_urls = dict(accepted)

    jobs: list[ExtractedJob] = []
    for index, url in accepted:
        card = card_of(document, index, link_urls=link_urls)
        title_index = _find(document, index, recipe.title, card=card)
        if title_index is None:
            continue
        title = _value_at(document, title_index, recipe.title)
        title = refine_card_title(document, title_index=title_index, card=card)
        if not is_usable_title(title):
            continue
        jobs.append(
            ExtractedJob(
                url=url,
                title=title,
                location=_field_value(document, index, card, recipe.location),
                posted_at=_field_value(document, index, card, recipe.posted_at),
            )
        )
    return jobs


def _field_value(document: Document, anchor: int, card: int, rule: FieldRule | None) -> str:
    if rule is None:
        return ""
    index = _find(document, anchor, rule, card=card)
    if index is None:
        return ""
    return _value_at(document, index, rule)


def default_recipe() -> Recipe:
    """默认配方：岗位链接的锚文本就是岗位名。

    **零模型、零配置**，因此它是列表页的第一道抽取手段。它读不到地点与时间，也读不出
    "锚文本不是标题"的那种页面——那正是模型兜底存在的理由。
    """
    return Recipe(title=FieldRule(scope=SCOPE_SELF, signature=Signature(tag="a")))


__all__ = [
    "MATCH_THRESHOLD",
    "MAX_ANCESTOR_STEPS",
    "MAX_TITLE_CHARS",
    "MIN_TITLE_CHARS",
    "RECIPE_SCHEMA",
    "SCOPES",
    "SCOPE_ANCESTORS",
    "SCOPE_CARD",
    "SCOPE_DESCENDANTS",
    "SCOPE_SELF",
    "TEXT_ATTR",
    "ExtractedJob",
    "FieldRule",
    "Recipe",
    "Signature",
    "default_recipe",
    "extract_with_recipe",
    "link_candidates",
    "matches",
    "signature_of",
    "similarity",
    "page_base",
    "squash",
    "tidy",
]
