"""求职数据看板（R-14）的本地聚合，**不依赖 LLM，离线可用**。

口径的唯一来源是 ``models/tracker.py`` 的 ``STATUSES`` / ``STATUS_RANK`` /
``STATUS_LABELS``，这里不另写枚举：

- **投递总量** = 未软删除的 ``ApplicationTrack`` 行数。
- **有效投递数** = 投递总量减去「待确认」（``unknown``）——待确认尚未核实为真实投递，
  不进入转化率分母；「已结束」（``rejected``）仍是真实投递，计入分母。
- **面试数** = 阶段达到「面试」及以上的行数（``interview`` / ``offer``）。
- **面试率** = 面试数 / 有效投递数。
- **测评笔试数** = 阶段达到「测评/笔试」及以上的行数（``assessment`` / ``interview`` /
  ``offer``）。
- **测评笔试→面试转化数** = 面试数；**笔试通过率** = 面试数 / 测评笔试数。
- **Offer 数** = 阶段为 ``offer`` 的行数。
- **六阶段漏斗** = ``STATUSES`` 的完整计数（含「已结束」「待确认」两个分支），标签用
  ``STATUS_LABELS``。
- **趋势** = 最近 ``trend_months`` 个自然月（默认 6，接口可传 1..24）的投递数量，
  按 ``applied_at`` 的前缀匹配（空日期不落入趋势）。
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from . import trash
from ..models.tracker import (
    STATUSES,
    STATUS_LABELS,
    STATUS_RANK,
    STATUS_ASSESSMENT,
    STATUS_INTERVIEW,
    STATUS_OFFER,
    STATUS_UNKNOWN,
    ApplicationTrack,
)

TREND_MONTHS = 6


def _rate(numerator: int, denominator: int) -> float:
    """百分比保留四位小数，分母为 0 时返回 0，避免除零。"""
    return round(numerator / denominator, 4) if denominator else 0.0


def _month_window(count: int) -> list[str]:
    """返回最近 ``count`` 个自然月的 ``YYYY-MM`` 列表（升序，含当月）。"""
    today = date.today()
    year, month = today.year, today.month
    months: list[str] = []
    for _ in range(count):
        months.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    months.reverse()
    return months


def build_dashboard(db: Session, trend_months: int = TREND_MONTHS) -> dict:
    """聚合看板所需的全部计数与序列，返回可被 ``DashboardOut`` 校验的字典。

    ``trend_months`` 只影响趋势序列的长度，其余指标口径不变。
    """
    tracks = db.query(ApplicationTrack).filter(trash.live_only(ApplicationTrack)).all()

    counts: dict[str, int] = {status: 0 for status in STATUSES}
    valid_applications = 0
    interview_count = 0
    assessment_count = 0
    offer_count = 0

    for track in tracks:
        counts[track.status] = counts.get(track.status, 0) + 1
        if track.status != STATUS_UNKNOWN:
            valid_applications += 1
        rank = STATUS_RANK.get(track.status, -1)
        if rank >= STATUS_RANK[STATUS_INTERVIEW]:
            interview_count += 1
        if rank >= STATUS_RANK[STATUS_ASSESSMENT]:
            assessment_count += 1
        if track.status == STATUS_OFFER:
            offer_count += 1

    funnel = [
        {"status": status, "label": STATUS_LABELS.get(status, status), "count": counts[status]}
        for status in STATUSES
    ]

    months = _month_window(trend_months)
    month_counts: dict[str, int] = {month: 0 for month in months}
    for track in tracks:
        prefix = (track.applied_at or "")[:7]
        if prefix in month_counts:
            month_counts[prefix] += 1
    trend = [
        {"month": month, "label": f"{int(month[5:7])}月", "count": month_counts[month]}
        for month in months
    ]

    return {
        "total_applications": len(tracks),
        "valid_applications": valid_applications,
        "interview_count": interview_count,
        "interview_rate": _rate(interview_count, valid_applications),
        "assessment_count": assessment_count,
        "assessment_to_interview_count": interview_count,
        "assessment_pass_rate": _rate(interview_count, assessment_count),
        "offer_count": offer_count,
        "funnel": funnel,
        "trend": trend,
    }


__all__ = ["TREND_MONTHS", "build_dashboard"]
