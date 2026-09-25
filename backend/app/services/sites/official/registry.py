"""采集适配器注册表：按系统标识分发。

与 ``services/sites/registry.py``（写路径）**并列而非合并**——两者注册的是不同的东西，
合并会得到一个既能投递又能采集的类，而那正是把两个抽象搅在一起的开端。

业务层只调 ``get_feed_registry().all()`` / ``.resolve(key)``；加一套招聘系统 = 加一个类 +
在这里注册一行。
"""
from __future__ import annotations

from .base import JobFeed


class FeedRegistry:
    """采集适配器注册表（保持注册顺序，探测按此顺序尝试）。"""

    def __init__(self) -> None:
        self._feeds: list[JobFeed] = []

    def register(self, feed: JobFeed) -> JobFeed:
        self._feeds.append(feed)
        return feed

    def all(self) -> list[JobFeed]:
        return list(self._feeds)

    def resolve(self, key: str) -> JobFeed | None:
        """按系统标识取适配器；没有则返回 ``None``（调用方决定回退策略）。

        ``official_site.source_kind`` 存的就是这个 key，探测一次之后每次采集都靠它还原
        适配器——所以这个反查必须稳定，新增系统时**不要改已有系统的 key**。
        """
        target = (key or "").strip()
        if not target:
            return None
        for feed in self._feeds:
            if feed.key == target:
                return feed
        return None

    def supported_names(self) -> str:
        """已注册系统的展示名，用「、」连成一句（用于"目前支持：…"这类说明）。"""
        return "、".join(feed.display_name for feed in self._feeds) or "暂无"


_REGISTRY: FeedRegistry | None = None


def default_registry() -> FeedRegistry:
    """构建默认注册表。

    **顺序即优先级**：探测按注册顺序返回第一个命中，所以专用适配器在前、通用兜底在后。
    通用路径对几乎任何带岗位链接的网页都能"命中"，排在前面会把本来能走契约的站点抢过去，
    让采集从稳定接口退化成解析网页——更慢、更易碎、而且拿不到总数（对账随之从硬结论降级）。
    """
    from .feeds import GenericFeed, GreenhouseFeed, TencentFeed

    registry = FeedRegistry()
    registry.register(GreenhouseFeed())
    registry.register(TencentFeed())
    registry.register(GenericFeed())
    return registry


def get_feed_registry() -> FeedRegistry:
    """进程内共享的默认注册表（延迟构建，避免导入期循环依赖）。"""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = default_registry()
    return _REGISTRY


__all__ = ["FeedRegistry", "default_registry", "get_feed_registry"]
