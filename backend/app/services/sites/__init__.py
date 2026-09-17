"""站点适配器层：把"某个招聘网站特有的事"收敛到可插拔的适配器里。

业务层只通过注册表拿到适配器，不感知具体站点；加站点 = 加一个类 + 注册一行。
"""
from .base import (
    ApplyOutcome,
    CollectQuery,
    RiskProfile,
    SearchPage,
    SearchResult,
    SiteAdapter,
    SiteFailure,
)
from .boss import BossAdapter
from .registry import SiteRegistry, default_registry, get_registry

__all__ = [
    "ApplyOutcome",
    "BossAdapter",
    "CollectQuery",
    "RiskProfile",
    "SearchPage",
    "SearchResult",
    "SiteAdapter",
    "SiteFailure",
    "SiteRegistry",
    "default_registry",
    "get_registry",
]
