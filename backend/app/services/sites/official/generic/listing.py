"""列表页抽取的**优先级**：存下的配方 → 默认配方 → 模型（顺便归纳）。

三级各自的位置不是随手排的：

1. **存下的配方**：这家站点自己的结构，最准，且零成本。
2. **默认配方**（锚文本即岗位名）：零成本、零假设。它读不出来的页面才值得花钱。
3. **模型**：最后一级。读到数据的同时**试着归纳出配方**，归纳成功就存下来——于是同一个站点
   通常只会为模型付一次钱。

**模型的调用被三道闸挡着**：前两级读出了东西就不调用；这一页已经问过、内容又没变也不调用；
没有配置模型时整级跳过（此时如实说明"没配模型，这页读不出来"，而不是假装读过了）。

这一层不做 HTTP，也不碰数据库：它只吃页面原文，吐出岗位与"该不该把记忆写回去"。落库由编排层
负责——把持久化塞进来会让这套优先级没法离线测试，而它恰恰是最需要被测的一层。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .induce import induce_recipe
from .llm_extract import ListingExtractor, LlmExtraction
from .memory import SiteMemory
from .recipe import ExtractedJob, default_recipe, extract_with_recipe

# 抽取方式。报告里如实展示——用户自付 key，他有权知道钱花在哪。
METHOD_RECIPE = "recipe"
METHOD_DEFAULT = "default"
METHOD_MODEL = "model"
METHOD_NONE = ""

METHOD_LABELS = {
    METHOD_RECIPE: "复用已存下的配方",
    METHOD_DEFAULT: "通用规则（链接文字即岗位名）",
    METHOD_MODEL: "模型抽取",
    METHOD_NONE: "没读出来",
}


@dataclass
class ListingResult:
    jobs: list[ExtractedJob] = field(default_factory=list)
    method: str = METHOD_NONE
    # 本次的模型调用次数（含重试）。
    calls: int = 0
    # 本次是否归纳并**成功存下**了配方。
    learned: bool = False
    # 这一页只读了前面几段（模型那一级的分块上限）。**必须往外传**：不然用户以为读完了，
    # 而实际上长清单的后半截一个字都没喂给模型。
    truncated: bool = False
    # 面向用户的说明。空串表示没什么要额外说的。
    detail: str = ""


async def extract_listing(
    markup: str,
    page_url: str,
    *,
    memory: SiteMemory,
    extractor: ListingExtractor | None = None,
    call_budget: int | None = None,
) -> ListingResult:
    """按优先级读一页列表。**从不抛异常**：读不出来是一级结论，不是故障。"""
    if not markup:
        return ListingResult(detail="这一页取回来是空的")

    if memory.listing is not None:
        jobs = extract_with_recipe(memory.listing, markup, page_url=page_url)
        if jobs:
            return ListingResult(jobs=jobs, method=METHOD_RECIPE)

    jobs = extract_with_recipe(default_recipe(), markup, page_url=page_url)
    if jobs:
        return ListingResult(jobs=jobs, method=METHOD_DEFAULT)

    if extractor is None:
        return ListingResult(
            detail="这一页按通用规则读不出岗位，且没有配置可用的大模型，无法进一步尝试"
        )

    if memory.should_skip_model(page_url, markup):
        # 内容没变，问过也是同样的空结果。这条判断省下的是**每次采集都会重复花掉的钱**。
        return ListingResult(
            detail="这一页此前已用模型读过、内容未变，这次没有重复调用"
        )

    extraction: LlmExtraction = await extractor.extract(
        markup, page_url, max_calls=call_budget
    )
    if not extraction.jobs:
        # 记下指纹的条件很严，三条都要满足——**记错了会让这一页此后永远不再问模型**：
        # ① 模型真的答复了（超时、401、额度用尽都不是"问了没读出来"，是"没问成"）；
        # ② 整页都读过了（只读了前几段时，没读到的部分不该被这句"内容没变"永久跳过）；
        # ③ 确实什么都没读出来（读出了东西就不该跳过，那些数据正是目的）。
        if extraction.answered and not extraction.truncated:
            memory.remember_unreadable(page_url, markup)
        return ListingResult(
            calls=extraction.calls,
            truncated=extraction.truncated,
            detail=extraction.detail
            or (
                "模型也没能从这一页读出岗位"
                if extraction.answered
                else "模型没有给出答复（超时、鉴权失败或额度用尽），这次不算数"
            ),
        )

    induction = induce_recipe(markup, page_url, extraction.jobs)
    # 截断这件事**不管归纳成没成都得说**：它描述的是"这一页我们只读了一部分"。
    if induction.recipe is not None:
        memory.remember_recipe(induction.recipe)
        return ListingResult(
            jobs=extraction.jobs,
            method=METHOD_MODEL,
            calls=extraction.calls,
            learned=True,
            truncated=extraction.truncated,
            detail=_note(
                "已归纳出这一站的页面结构并存下，之后不再需要模型", extraction
            ),
        )

    # 归纳失败**不是错误**：本轮照用模型读到的数据，只是不落库、下次还得再问一次。
    return ListingResult(
        jobs=extraction.jobs,
        method=METHOD_MODEL,
        calls=extraction.calls,
        truncated=extraction.truncated,
        detail=_note(
            induction.detail or "没能归纳出可复用的页面结构，下次仍需模型", extraction
        ),
    )


def _note(base: str, extraction: LlmExtraction) -> str:
    """把"只读了一部分"和基础说明拼起来。两件事都要说，谁也别盖住谁。"""
    if not extraction.detail:
        return base
    return f"{base}；{extraction.detail}"


__all__ = [
    "METHOD_DEFAULT",
    "METHOD_LABELS",
    "METHOD_MODEL",
    "METHOD_NONE",
    "METHOD_RECIPE",
    "ListingResult",
    "extract_listing",
]
