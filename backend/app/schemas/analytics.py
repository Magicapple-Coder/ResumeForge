"""求职数据看板（R-14）的响应结构。

只承载结构，**所有计数口径的唯一来源是 ``models/tracker.py`` 的 ``STATUSES`` /
``STATUS_RANK`` / ``STATUS_LABELS``**，看板不另写枚举。具体口径定义与计算见
``services/analytics.py`` 的模块 docstring。
"""
from pydantic import BaseModel, Field


class FunnelStage(BaseModel):
    """漏斗里的一个阶段：状态键、面向用户的中文名与计数。"""

    status: str
    label: str
    count: int


class TrendPoint(BaseModel):
    """趋势图上的一个点：一个自然月的投递数量。"""

    month: str = ""  # YYYY-MM
    label: str = ""  # 面向展示的短标签（如 "9月"）
    count: int = 0


class DashboardOut(BaseModel):
    """看板整体响应：四个指标 + 六阶段漏斗 + 月度投递趋势。"""

    total_applications: int = 0
    valid_applications: int = 0
    interview_count: int = 0
    interview_rate: float = 0.0
    assessment_count: int = 0
    assessment_to_interview_count: int = 0
    assessment_pass_rate: float = 0.0
    offer_count: int = 0
    funnel: list[FunnelStage] = Field(default_factory=list)
    trend: list[TrendPoint] = Field(default_factory=list)


__all__ = ["DashboardOut", "FunnelStage", "TrendPoint"]
