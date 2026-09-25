"""从"页面 + 模型读出的岗位"归纳出一份配方，**并用重放验证它**。

**模型的输出是数据，不是选择器。** 让它直接给 CSS 选择器有两个问题：那串东西我们无从校验
（只能照用），而且它错了以后没有任何下游信号能发现。这里换成：模型只回答"这一页上有哪些
岗位"（数据，可逐条核对——每个地址都必须在页面里真实存在），**选择器由我们反推**，再用
反推出来的配方**重放整页**：重放不出来就不落库。

这条"重放校验"是整个归纳过程能被信任的原因，也是本模块唯一不可省略的一步。它同时挡住了
两类错：归纳错了（规则选偏），和模型编了（地址在页面上不存在——那一条在归纳前就被剔掉了）。

**归纳失败不是错误**，是这一级给出的诚实答案：这次用模型读出来的结果，但不落库；下次还得
再问一次模型。报告里会如实写出这件事——用户自付 key，他有权知道钱花在哪、为什么没省下来。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from urllib.parse import urljoin, urlsplit

from ..urls import looks_like_job_url
from .dom import Document, parse_document
from .recipe import (
    SCOPE_ANCESTORS,
    SCOPE_CARD,
    SCOPE_SELF,
    ExtractedJob,
    FieldRule,
    Recipe,
    card_of,
    extract_with_recipe,
    page_base,
    signature_of,
    squash,
)

# 重放出来的岗位最多允许是模型给出的几倍。超了说明学到的地址片段太宽（比如匹配到了整站导航），
# 那种"配方"会把列表页变成站点地图。
MAX_EXTRA_RATIO = 2.0
# 条数少时比例不起作用（1 条 → 允许 2 条），给一个绝对余量。
MAX_EXTRA_ABSOLUTE = 3

# 学出来的地址片段至少要这么长、且必须是完整的路径段。``/`` 这种宽泛片段会把整站链接吸进来。
MIN_MARKER_CHARS = 3

# 字段规则的搜索顺序：**从最贴近链接的地方往外找**。先近后远不只是效率——越靠近链接的元素
# 越可能是这个岗位自己的信息，往外找容易摸到卡片的公共容器。
_TITLE_RULE_ORDER = (SCOPE_SELF, SCOPE_ANCESTORS, SCOPE_CARD)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Induction:
    """归纳结果。``recipe`` 为 ``None`` 表示重放没通过，本轮结果照用但不落库。"""

    recipe: Recipe | None
    # 模型给出、且在页面上真实存在的岗位地址数。
    grounded: int
    # 模型给出、但页面上找不到对应链接的条数（编造或地址没写全）。
    ungrounded: int
    # 重放比模型多读出来的条数。
    extra: int
    detail: str = ""


def _same(left: str, right: str) -> bool:
    """文本比较一律忽略空白，见 ``recipe.squash``。"""
    return squash(left) == squash(right)


def _resolve(url: str, base: str) -> str:
    """把地址归一化成绝对形式。**归一化只做一次、只在这里做。**

    从前模块里有三处各自解析地址（配方层认 ``<base href>``、模型层不认、归纳层又按解析后的
    形式建键却按原样查表），后果是两个：模型层把地址拼错一个路径前缀（用户点开是 404），
    归纳层因为"地址对不上"永远学不出配方——而报告把原因写成"模型给的地址在这页上一个也找不到"。
    两套归一化不一致，错的却记在我们自己头上。
    """
    cleaned = (url or "").strip()
    if not cleaned:
        # 空地址**不能**用 urljoin 兜成页面地址：那会让它碰巧对上页面里某个链接。
        return ""
    try:
        return urljoin(base, cleaned).split("#", 1)[0]
    except ValueError:
        return ""


def _model_urls(document: Document, base: str, jobs: list[ExtractedJob]) -> dict[str, int]:
    """模型给的地址 → 页面上对应的链接元素下标。**页面里没有的地址直接丢掉。**

    这是最先做的一件事，也是把幻觉挡在门外的那道闸：模型可以编一个岗位名，但编不出一个
    真实存在于页面上的链接。地址对不上的条目连参与归纳的资格都没有。

    ``jobs`` 里的地址**必须已经归一化过**（调用方用 ``_resolve`` 统一处理），这里才能直接
    拿它当键去和页面上的链接比。
    """
    host = (urlsplit(base).hostname or "").casefold()
    anchors: dict[str, int] = {}
    for index, href in document.hrefs():
        url = _resolve(href, base)
        if not url or url in anchors:
            continue
        if (urlsplit(url).hostname or "").casefold() != host:
            continue
        anchors[url] = index

    return {job.url: anchors[job.url] for job in jobs if job.url in anchors}


def _common_marker(urls: list[str]) -> str:
    """这些地址共有的路径前缀，**切到段边界**（``/p/88`` → ``/p/``）。

    切到段边界是必须的：``/p/88`` 这种半个数字的前缀在下一页就不成立了，而 ``/p/`` 能一直用。
    """
    if not urls:
        return ""
    paths = [urlsplit(url).path for url in urls]
    prefix = paths[0]
    for path in paths[1:]:
        limit = min(len(prefix), len(path))
        cut = 0
        while cut < limit and prefix[cut] == path[cut]:
            cut += 1
        prefix = prefix[:cut]
    cut = prefix.rfind("/")
    return prefix[: cut + 1] if cut >= 0 else ""


def _title_rule(document: Document, index: int, card: int, title: str) -> FieldRule | None:
    """标题从哪儿取。**从链接自己开始往外找**，第一个"文本正好等于标题"的位置就是它。"""
    scopes = {
        SCOPE_SELF: [index],
        SCOPE_ANCESTORS: document.ancestors(index),
        SCOPE_CARD: [card, *document.descendants(card)],
    }
    for scope in _TITLE_RULE_ORDER:
        for candidate in scopes[scope]:
            if _same(document.text(candidate), title):
                return FieldRule(
                    scope=scope, signature=signature_of(document, candidate)
                )
    return None


def _value_rule(document: Document, card: int, value: str) -> FieldRule | None:
    """地点/时间从哪儿取：在**卡片内部**找一个值正好等于它的元素或属性。

    取**文档序最靠后**的那个而不是最靠前的：``<div class="meta"><span class="loc">北京</span></div>``
    里两层文本都是"北京"，靠后的是更具体的 ``span``，它的签名在改版里更不容易被别的东西撞上。
    """
    for candidate in reversed([card, *document.descendants(card)]):
        element = document.elements[candidate]
        if _same(document.text(candidate), value):
            return FieldRule(scope=SCOPE_CARD, signature=signature_of(document, candidate))
        for name, raw in element.attrs.items():
            if name == "class" or not raw.strip():
                continue
            if _same(raw, value):
                return FieldRule(
                    scope=SCOPE_CARD,
                    signature=signature_of(document, candidate),
                    attr=name,
                )
    return None


def induce_recipe(
    markup: str,
    page_url: str,
    jobs: list[ExtractedJob],
) -> Induction:
    """从这一页与模型读出的岗位归纳配方；重放通不过就只返回数据、不返回配方。"""
    document = parse_document(markup)
    # **地址先归一化一次**，之后全模块都用归一化后的形式（建键、查表、重放比对），
    # 不再有"解析后 / 原样"两套形态。
    base = page_base(document, page_url)
    jobs = [replace(job, url=_resolve(job.url, base)) for job in jobs]
    grounded = _model_urls(document, base, jobs)
    ungrounded = len(jobs) - len(grounded)
    if not grounded:
        return Induction(
            recipe=None,
            grounded=0,
            ungrounded=ungrounded,
            extra=0,
            detail="模型给的岗位地址在这页上一个也找不到，不据此归纳配方",
        )

    ordered = [(job, grounded[job.url]) for job in jobs if job.url in grounded]
    # 只保留有标题的条目：没有标题的岗位连"这是不是一条岗位"都说不清。
    ordered = [(job, index) for job, index in ordered if job.title.strip()]
    if not ordered:
        return Induction(recipe=None, grounded=len(grounded), ungrounded=ungrounded, extra=0,
                         detail="模型给出的条目都没有标题，不据此归纳配方")

    urls = [job.url for job, _index in ordered]
    markers: tuple[str, ...] = ()
    if not all(looks_like_job_url(url, page_host=(urlsplit(page_url).hostname or "")) for url in urls):
        marker = _common_marker(urls)
        if len(marker) < MIN_MARKER_CHARS:
            return Induction(
                recipe=None,
                grounded=len(grounded),
                ungrounded=ungrounded,
                extra=0,
                detail="这页的岗位地址没有共同的路径特征，学不出可复用的规则",
            )
        markers = (marker,)

    link_urls = {index: job.url for job, index in ordered}
    title_rule = None
    for job, index in ordered:
        card = card_of(document, index, link_urls=link_urls)
        found = _title_rule(document, index, card, job.title)
        if found is None:
            return Induction(
                recipe=None,
                grounded=len(grounded),
                ungrounded=ungrounded,
                extra=0,
                detail=f"标题「{job.title}」在这页上找不到出处，不据此归纳配方",
            )
        if title_rule is None:
            title_rule = found
        elif title_rule != found:
            # 各条岗位的标题不在同一个位置：一条规则表达不了，只能每次问模型。
            return Induction(
                recipe=None,
                grounded=len(grounded),
                ungrounded=ungrounded,
                extra=0,
                detail="各条岗位的标题不在同一处，一条规则表达不了",
            )

    recipe = Recipe(
        title=title_rule,
        location=_consistent_rule(document, ordered, link_urls, lambda job: job.location),
        posted_at=_consistent_rule(document, ordered, link_urls, lambda job: job.posted_at),
        url_markers=markers,
        source_url=page_url,
    )
    return _verify(recipe, markup, page_url, ordered, ungrounded)


def _consistent_rule(
    document: Document,
    ordered: list[tuple[ExtractedJob, int]],
    link_urls: dict[int, str],
    picker,
) -> FieldRule | None:
    """可选字段（地点/时间）：**每个给出了该字段的岗位都要归纳出同一条规则**，否则不要它。

    少一个字段不影响配方能用；而一条时灵时不灵的规则会让读出来的值真假混杂，那比没有更糟。
    """
    rule: FieldRule | None = None
    considered = False
    for job, index in ordered:
        value = picker(job)
        if not value.strip():
            continue
        considered = True
        card = card_of(document, index, link_urls=link_urls)
        found = _value_rule(document, card, value)
        if found is None:
            return None
        if rule is None:
            rule = found
        elif rule != found:
            return None
    return rule if considered else None


def _verify(
    recipe: Recipe,
    markup: str,
    page_url: str,
    ordered: list[tuple[ExtractedJob, int]],
    ungrounded: int,
) -> Induction:
    """**重放校验：这是归纳能被信任的全部理由。**

    三条都要过：模型给出的每一条都要被重放出来且标题一致（说明规则学到了）；**每一个可选字段
    也要逐条对得上**；重放不能多读出太多（说明规则没有宽到把整站导航吸进来）。任一条不过就
    只返回数据、不返回配方——或者把不过的那条字段规则丢掉。

    **可选字段必须逐条核对，不能只看"规则选出来了"**：``_value_rule`` 是按"文本等于这个值"
    定位元素的，而写进配方的只有那个元素的**签名**。卡里若有第二个元素签名完全相同
    （``<span class="tag">社招</span><span class="tag">北京</span>``），重放时命中第一个，
    读出来的是"社招"——值看着正常，却没有任何下游信号能发现它。核对不上就把这条规则去掉：
    宁可这一站没有地点字段，也不要一个每次都给出错值的字段。
    """
    replayed = {job.url: job for job in extract_with_recipe(recipe, markup, page_url=page_url)}
    for job, _index in ordered:
        found = replayed.get(job.url)
        if found is None:
            return Induction(
                recipe=None, grounded=len(ordered), ungrounded=ungrounded, extra=0,
                detail="归纳出的规则重放时读不出模型给的那批岗位",
            )
        if not _same(found.title, job.title):
            return Induction(
                recipe=None, grounded=len(ordered), ungrounded=ungrounded, extra=0,
                detail="归纳出的规则重放出不同的标题",
            )

    recipe = _drop_fields_that_do_not_replay(recipe, replayed, ordered)
    extra = len(replayed) - len(ordered)
    if len(replayed) > len(ordered) * MAX_EXTRA_RATIO + MAX_EXTRA_ABSOLUTE:
        return Induction(
            recipe=None, grounded=len(ordered), ungrounded=ungrounded, extra=extra,
            detail="归纳出的规则读出的岗位远多于模型给出的，规则太宽，不落库",
        )
    return Induction(
        recipe=recipe,
        grounded=len(ordered),
        ungrounded=ungrounded,
        extra=max(extra, 0),
        detail="",
    )


def _drop_fields_that_do_not_replay(
    recipe: Recipe,
    replayed: dict[str, ExtractedJob],
    ordered: list[tuple[ExtractedJob, int]],
) -> Recipe:
    """把重放不出原值的可选字段规则去掉。见 ``_verify`` 的说明。

    **去掉而不是整份作废**：标题规则与地址片段仍然是对的，它们才是"读得到岗位"的关键；一个
    字段读不出来只是少一列信息。反过来（留着它）会让这一站每次采集都写进一个错值，而错值正是
    这个功能最不该产出的东西。
    """
    dropped = recipe
    for name in ("location", "posted_at"):
        if getattr(recipe, name) is None:
            continue
        for job, _index in ordered:
            expected = getattr(job, name).strip()
            if not expected:
                continue
            actual = getattr(replayed[job.url], name).strip()
            if not _same(actual, expected):
                logger.info(
                    "归纳出的 %s 规则重放对不上（期望 %r，实际 %r），不写入配方", name, expected, actual
                )
                dropped = replace(dropped, **{name: None})
                break
    return dropped


__all__ = [
    "MAX_EXTRA_ABSOLUTE",
    "MAX_EXTRA_RATIO",
    "MIN_MARKER_CHARS",
    "Induction",
    "induce_recipe",
]
