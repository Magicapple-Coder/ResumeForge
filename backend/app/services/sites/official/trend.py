"""趋势离群：这次抓到的条数，和这家公司近期相比算不算异常。

**它治的是单次对账看不见的病**：「今天抓全了，但站点改版后每天只抓到 3 条」。单次对账会
如实报告"已确认为全量"——因为站点自己声明的总数就是 3，账目对得上——而它无从知道这家公司
上周还有 40 条在招。

**它不是一条对账依据，而是一个独立的提醒。** 这一点必须说清楚，因为条数下降有两个来源，
**只看条数是分不出来的**：

- 站点改版导致我们少抓了（我们的问题，该修）；
- 这家公司真的关掉了那些岗位（不是问题）。

所以它给出的措辞是"值得看一眼"，而不是"出问题了"；也**绝不参与** ``reconcile`` 的结论。
把它塞进对账会让"公司缩减招聘"这种正常情况被报成故障。
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Protocol

# 至少要有这么多次**有效测量**才谈得上基线：两次数不出趋势，只数得出噪声。
MIN_HISTORY = 3

# 掉到基线的这个比例以下算显著。取 0.6 的理由：真实的选择器失效往往让条数**腰斩或更惨**
# （只剩还能匹配的那几条），而正常的岗位增减很少超过一两成，中间留出了很宽的余量。
DROP_RATIO = 0.6
# 涨到基线的这个倍数以上算显著。翻倍在正常经营里不常见，而站点改版导致"返回了本来不该返回的
# 内容"（例如把全站招聘页都塞进列表）常常是数倍。
JUMP_RATIO = 2.0

# 绝对差额的下限。**比例在小数上不可靠**：4 条掉到 2 条也是"腰斩"，但那多半只是正常的岗位
# 增减。要求绝对差额也够大，才能把小数噪声挡在外面。
MIN_ABSOLUTE_CHANGE = 3

TREND_STABLE = "stable"
TREND_DROPPED = "dropped"
TREND_JUMPED = "jumped"
# 历史不够，**说不了**。它不是"正常"，而是"还没有可比的东西"——三态里的"不知道"。
TREND_INSUFFICIENT = "insufficient"
# **这次采集本身就没拿到有效结果**（被阻断 / 已停止 / 失败）。
# 单独一类而不是并进"少于近期"：那种情况下条数低的原因我们**是知道的**（被拦了、被停了），
# 而"明显少于近期"那句话会邀请用户往"公司是不是关掉岗位了"去想——那是错的答案。
TREND_UNMEASURED = "unmeasured"

TREND_LABELS = {
    TREND_STABLE: "与近期持平",
    TREND_DROPPED: "明显少于近期",
    TREND_JUMPED: "明显多于近期",
    TREND_INSUFFICIENT: "历史不足，暂无法比较",
    TREND_UNMEASURED: "这次没有拿到有效结果",
}


class RunLike(Protocol):
    """参与趋势判断的一次运行。用 Protocol 而不是直接吃 ORM 对象，测试里给个简单对象即可。"""

    status: str
    collected: int
    blocks: list[str]


@dataclass(frozen=True)
class TrendSignal:
    state: str
    label: str
    detail: str
    # 基线（历史的中位数）与本次条数；历史不足时 ``baseline`` 为 ``None``。
    baseline: int | None = None
    latest: int = 0


def is_measurement(run: RunLike) -> bool:
    """这次运行的条数**是不是一次有效测量**。

    被阻断、被 robots 拒绝、用户停止、失败的那些都**不是**：它们的 0 是"我们没拿到"，
    而不是"这家公司没有岗位"。混进基线会把基线越拉越低，最终把一次真实的掉量掩盖掉——
    而那正是这个模块要发现的东西。
    """
    from ....models.official import (
        RUN_DONE,
        is_transport_failure,
    )

    if run.status != RUN_DONE:
        return False
    # robots 拒绝也记成 RUN_DONE，但它根本没尝试采集——同样不是测量。
    return not any(is_transport_failure(block) for block in (run.blocks or []))


def measured_counts(runs: list[RunLike]) -> list[int]:
    """从运行记录里挑出有效测量的条数（保持传入顺序）。"""
    return [run.collected for run in runs if is_measurement(run)]


def compare_trend(prior: list[int], latest: int, *, measured: bool = True) -> TrendSignal:
    """把本次条数与历史比较，给出一个**提醒**。

    ``prior`` 是**本次之前**的有效测量（由旧到新，顺序不影响结果），``latest`` 是本次条数，
    ``measured`` 说明**本次本身**是不是一次有效测量（见 :func:`is_measurement`）。

    基线取**中位数**而不是平均数：一次被阻断的采集已经由 ``measured_counts`` 挡在外面了，
    但（例如）一次"站点只返回了一半"的采集仍会混进来，平均数会被它单条拽偏，中位数不会。
    """
    if not measured:
        return TrendSignal(
            state=TREND_UNMEASURED,
            label=TREND_LABELS[TREND_UNMEASURED],
            detail="这次采集被阻断或已停止，没有拿到可比的结果；先看这次自己的结论",
            baseline=None,
            latest=latest,
        )

    if len(prior) < MIN_HISTORY:
        return TrendSignal(
            state=TREND_INSUFFICIENT,
            label=TREND_LABELS[TREND_INSUFFICIENT],
            detail=(
                f"这家公司还只有 {len(prior)} 次有效采集记录，"
                f"满 {MIN_HISTORY} 次之后才能看出这次是否异常"
            ),
            baseline=None,
            latest=latest,
        )

    baseline = int(median(prior))
    if baseline <= 0:
        # 基线是 0：之前每次都抓不到东西。此时"突然抓到了"是有信息量的（要么站点通了、
        # 要么路径修好了），而"仍然是 0"什么也说明不了。
        if latest > 0:
            return TrendSignal(
                state=TREND_JUMPED,
                label=TREND_LABELS[TREND_JUMPED],
                detail=f"之前的采集一条都没抓到，这次抓到了 {latest} 条",
                baseline=baseline,
                latest=latest,
            )
        return TrendSignal(
            state=TREND_STABLE,
            label=TREND_LABELS[TREND_STABLE],
            detail="这家公司的采集一直是 0 条",
            baseline=baseline,
            latest=latest,
        )

    change = abs(latest - baseline)
    significant = change >= MIN_ABSOLUTE_CHANGE

    if significant and latest < baseline * DROP_RATIO:
        return TrendSignal(
            state=TREND_DROPPED,
            label=TREND_LABELS[TREND_DROPPED],
            detail=(
                f"这次抓到 {latest} 条，而近 {len(prior)} 次的中位数是 {baseline} 条。"
                "这不一定是漏抓——也可能是这家公司真的关掉了那些岗位；"
                "两条线索都看一下：报告里的对账依据，以及这家公司自己的招聘页"
            ),
            baseline=baseline,
            latest=latest,
        )

    if significant and latest > baseline * JUMP_RATIO:
        return TrendSignal(
            state=TREND_JUMPED,
            label=TREND_LABELS[TREND_JUMPED],
            detail=(
                f"这次抓到 {latest} 条，而近 {len(prior)} 次的中位数是 {baseline} 条。"
                "可能是这家公司在扩招，也可能是站点改了返回的内容（例如把不相关的岗位也列出来）"
            ),
            baseline=baseline,
            latest=latest,
        )

    return TrendSignal(
        state=TREND_STABLE,
        label=TREND_LABELS[TREND_STABLE],
        detail=f"这次抓到 {latest} 条，与近 {len(prior)} 次的中位数 {baseline} 条相当",
        baseline=baseline,
        latest=latest,
    )


__all__ = [
    "DROP_RATIO",
    "JUMP_RATIO",
    "MIN_ABSOLUTE_CHANGE",
    "MIN_HISTORY",
    "TREND_DROPPED",
    "TREND_INSUFFICIENT",
    "TREND_JUMPED",
    "TREND_LABELS",
    "TREND_STABLE",
    "TREND_UNMEASURED",
    "RunLike",
    "TrendSignal",
    "compare_trend",
    "is_measurement",
    "measured_counts",
]
