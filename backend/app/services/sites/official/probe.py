"""站源探测：这家公司的官网背后是哪套招聘系统。

**为什么先探测再采集**：识别出系统就能走契约（公开 JSON 接口），既稳定又自带总数——而对账
要给出硬结论，恰恰依赖那个总数。全部识别不出来才退回通用抽取。

**命中判据：端点存在 且 返回 ≥1 条岗位。** 后半句不是多余的：有的系统在**公司不存在时也
返回 200 且总数为 0**，只看"端点存在"就会把"这家公司不用这套系统"读成"这家公司在用、只是没
在招"。代价是一家**真的** 0 岗位的公司不会被识别出来——这个代价可以接受，因为：
错误地认定一套系统会污染对账（"0 条，已确认为全量"），而漏识别只会退到通用路径继续找。

**唯一的例外**是用户自己给的招聘页地址：那是用户亲眼看到的页面，它本身就是"这家公司确实
在这套系统上"的证据。此时 0 岗位是真实答案（可能刚招满），如实报告比退回猜测有用得多。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .base import (
    CONFIDENCE_HIGH,
    FeedHttp,
    JobFeed,
    ProbeContext,
    ProbeHit,
)
from .registry import FeedRegistry
from ....models.official import BLOCK_NONE, is_transport_failure

logger = logging.getLogger(__name__)

# 一次探测最多打几次请求。候选数量是"线索数 × 区域数"，随注册的系统数增长；不设上限的话
# 每加一套系统都会让探测变慢、也让被探测的站点多挨几刀。达到上限时**如实记录被截断**，
# 而不是假装"已经全部试过了"。
MAX_PROBE_ATTEMPTS = 12

# 探测结果三态：与对账的三态同一个取向——"不知道"是一条独立且有用的结论。
PROBE_HIT = "hit"
PROBE_NOT_FOUND = "not_found"
PROBE_BLOCKED = "blocked"

PROBE_STATE_LABELS = {
    PROBE_HIT: "已识别招聘系统",
    PROBE_NOT_FOUND: "未识别出已知的招聘系统",
    PROBE_BLOCKED: "探测被阻断，没能得出结论",
}


@dataclass(frozen=True)
class ProbeAttempt:
    """一次候选验证的结果，供诊断展示。"""

    feed_key: str
    endpoint: str
    block: str
    job_count: int
    detail: str = ""


@dataclass
class ProbeOutcome:
    state: str
    hit: ProbeHit | None = None
    # 命中时该职位板当前的岗位数（0 是合法值，见模块说明的例外）。
    job_count: int = 0
    attempts: list[ProbeAttempt] = field(default_factory=list)
    # 因为达到尝试上限而没试完的候选数；>0 时结论要打折扣。
    untried: int = 0
    detail: str = ""

    @property
    def found(self) -> bool:
        return self.state == PROBE_HIT


async def probe_site(
    http: FeedHttp,
    ctx: ProbeContext,
    *,
    registry: FeedRegistry,
    max_attempts: int = MAX_PROBE_ATTEMPTS,
) -> ProbeOutcome:
    """依次尝试各系统给出的候选，返回第一个成立的命中。

    ``http`` 由调用方提供且**跨候选复用**（同一个连接池，同一个站点的多次请求不必反复握手）。
    """
    attempts: list[ProbeAttempt] = []
    blocked = False
    untried = 0

    for feed in registry.all():
        candidates = feed.probe_candidates(ctx)
        for candidate in candidates:
            if len(attempts) >= max_attempts:
                untried += 1
                continue

            page = await feed.fetch_page(http, candidate.target)
            rejection_reason = ""
            if page.block == BLOCK_NONE:
                rejection_reason = feed.probe_rejection_reason(ctx, candidate, page)
            attempts.append(
                ProbeAttempt(
                    feed_key=feed.key,
                    endpoint=candidate.target.endpoint,
                    block=page.block,
                    job_count=len(page.jobs),
                    detail="；".join(part for part in (page.detail, rejection_reason) if part),
                )
            )

            if page.block == BLOCK_NONE:
                if rejection_reason:
                    # 可访问但属于别家的公开端点不是网络阻断，继续试其它候选，最后让通用路径接手。
                    continue
                if page.jobs:
                    return ProbeOutcome(
                        state=PROBE_HIT,
                        hit=candidate,
                        job_count=len(page.jobs),
                        attempts=attempts,
                        detail=candidate.evidence,
                    )
                # **列表页型站点在这一步不该被判成不匹配**：它的入口页本身不带岗位，只列出
                # 一批岗位页的地址。要求"必须直接读出岗位"会把这类站点全判成不支持，
                # 而它们恰恰是通用路径的主要服务对象。
                if page.next_targets:
                    return ProbeOutcome(
                        state=PROBE_HIT,
                        hit=candidate,
                        job_count=0,
                        attempts=attempts,
                        detail=(
                            f"{candidate.evidence}；"
                            f"发现 {len(page.next_targets)} 个岗位页链接"
                        ),
                    )
                # 端点存在但没有岗位。**是否认这个"空命中"由适配器声明**（见
                # ``JobFeed.empty_entry_is_conclusive``），而不是由置信度推断。
                #
                # 注意这里**只认用户直接给出的那个地址**（``CONFIDENCE_HIGH``）：他说"这就是
                # 它的招聘页"，而我们确实取到了这一页——那是个可用的源。由域名猜出来的候选
                # 没有这份证据，读到 0 条就只说明"这个入口没有岗位"。
                if feed.empty_entry_is_conclusive and candidate.confidence == CONFIDENCE_HIGH:
                    return ProbeOutcome(
                        state=PROBE_HIT,
                        hit=candidate,
                        job_count=0,
                        attempts=attempts,
                        # 措辞要如实：认下来的是"这个源可用"，不是"这里有岗位"。通用路径后面
                        # 还有配方与模型两级没试，用户得知道接下来会发生什么。
                        detail=(
                            f"{candidate.evidence}；该职位板当前没有在招岗位"
                            if not feed.supports_recipes
                            else f"{candidate.evidence}；这一页能正常读取，但没有直接读出岗位"
                            "；采集时会用配方与大模型再试"
                        ),
                    )
                continue

            if is_transport_failure(page.block):
                # 被阻断**不代表不是这套系统**——我们只是没看到内容。记下来，最后如实汇报。
                blocked = True

    if blocked:
        return ProbeOutcome(
            state=PROBE_BLOCKED,
            attempts=attempts,
            untried=untried,
            detail=_with_untried(PROBE_STATE_LABELS[PROBE_BLOCKED], untried),
        )

    return ProbeOutcome(
        state=PROBE_NOT_FOUND,
        attempts=attempts,
        untried=untried,
        detail=_with_untried(PROBE_STATE_LABELS[PROBE_NOT_FOUND], untried),
    )


def _with_untried(detail: str, untried: int) -> str:
    """把"没试完"如实挂到结论上。

    **"试到上限就停了"与"这家公司不用这套系统"是两件事**，而它们会落到同一个状态上
    （未识别）。不说这一句，用户看到的就是"这家公司不在支持范围内"——一句我们并不知道真假
    的结论。这个模块自己的注释写着"如实记录被截断，而不是假装已经全部试过了"，这一句就是
    兑现它。
    """
    if untried <= 0:
        return detail
    return f"{detail}；还有 {untried} 个候选地址没来得及试（达到本次尝试上限）"


def feeds_for(outcome: ProbeOutcome, registry: FeedRegistry) -> JobFeed | None:
    """从探测结果还原适配器（供后续采集使用）。"""
    if outcome.hit is None:
        return None
    return registry.resolve(outcome.hit.target.feed_key)


__all__ = [
    "MAX_PROBE_ATTEMPTS",
    "PROBE_BLOCKED",
    "PROBE_HIT",
    "PROBE_NOT_FOUND",
    "PROBE_STATE_LABELS",
    "ProbeAttempt",
    "ProbeOutcome",
    "feeds_for",
    "probe_site",
]
