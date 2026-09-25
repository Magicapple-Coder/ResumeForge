"""官网采集：从公司自己的招聘站点取岗位，并给出**完整性对账**。

与 ``services/sites/`` 的写路径（驱动浏览器投递）是两条独立链路，共享数据结构但不共享抽象——
理由见 ``base.py`` 的模块说明。设计与实施路线见 ``docs/official-collect-plan.md``。

本包的对外契约只在这里导出；业务层应当**只**依赖 ``base`` 里的抽象，不直接 import 某个
适配器，这样加一套招聘系统（加一个类 + 注册一行）不需要动业务层。
"""
from .base import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LABELS,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    FeedHttp,
    FeedJob,
    FeedPage,
    FeedTarget,
    FetchResult,
    JobFeed,
    ProbeContext,
    ProbeHit,
)

__all__ = [
    "CONFIDENCE_HIGH",
    "CONFIDENCE_LABELS",
    "CONFIDENCE_LOW",
    "CONFIDENCE_MEDIUM",
    "FeedHttp",
    "FeedJob",
    "FeedPage",
    "FeedTarget",
    "FetchResult",
    "JobFeed",
    "ProbeContext",
    "ProbeHit",
]
