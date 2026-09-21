"""站点适配器注册表：按站点标识 / URL 主机分发到具体适配器。

业务层只管调用 ``registry.for_job(job)``；加站点时只要新增一个类并在默认注册表里
``register`` 一行，业务层一行都不用改。
"""
from __future__ import annotations

from typing import Any

from ...models.apply import FAILURE_UNKNOWN, FAILURE_CATEGORY_LABELS
from .base import SiteAdapter, SiteFailure


class SiteRegistry:
    """适配器注册表（保持注册顺序，便于"先注册先匹配"）。"""

    def __init__(self) -> None:
        self._adapters: list[SiteAdapter] = []

    def register(self, adapter: SiteAdapter) -> SiteAdapter:
        self._adapters.append(adapter)
        return adapter

    def all(self) -> list[SiteAdapter]:
        return list(self._adapters)

    def resolve(self, key: str) -> SiteAdapter | None:
        """按站点标识取适配器；没有则返回 ``None``（调用方决定回退策略）。

        "当前站点"这个概念就靠它落地：配置里存 ``site_key``，业务层 ``resolve`` 出对应适配器。
        加站点时这个函数无需改动——新站点注册进来自动可见。
        """
        target = (key or "").strip()
        if not target:
            return None
        for adapter in self._adapters:
            if adapter.key == target:
                return adapter
        return None

    def default_key(self) -> str:
        """注册表里第一个站点的标识（作为"当前站点"的出厂默认）。"""
        return self._adapters[0].key if self._adapters else ""

    def supported_names(self) -> str:
        """已注册站点的展示名，用「、」连成一句（用于错误信息里"目前支持：…"）。"""
        return "、".join(adapter.display_name for adapter in self._adapters) or "暂无"

    def for_target(self, url_or_source: str) -> SiteAdapter:
        """按站点标识或域名分发站点适配器。"""
        for adapter in self._adapters:
            if adapter.matches(url_or_source):
                return adapter
        raise SiteFailure(
            FAILURE_UNKNOWN,
            f"暂不支持该招聘网站（{FAILURE_CATEGORY_LABELS[FAILURE_UNKNOWN]}）；"
            f"目前支持：{self.supported_names()}",
        )

    def for_url(self, url: str) -> SiteAdapter:
        return self.for_target(url)

    def for_job(self, job: Any) -> SiteAdapter:
        """按岗位的 ``source`` 与 ``source_url`` 反查适配器。"""
        source = getattr(job, "source", "") or ""
        url = getattr(job, "source_url", "") or ""
        return self.for_target(f"{source} {url}".strip())

    def resolve_for_job(self, job: Any) -> SiteAdapter | None:
        """``for_job`` 的**不抛异常**版本：解析不出来就返回 ``None``。

        两个版本的差别就是使用场景：
        - ``for_job``：投递执行时用，解析不出来是**真的出错**，要带诊断抛出去；
        - ``resolve_for_job``：**入队校验、开始投递前的拦截、列表上的"能不能投"标记**用。
          这三处只想知道"行不行"，不该各自写一遍 try/except（写三遍就迟早判得不一样）。
        """
        try:
            return self.for_job(job)
        except SiteFailure:
            return None


def default_registry() -> SiteRegistry:
    """构建默认注册表：首期只注册 BOSS 直聘。"""
    from .boss import BossAdapter

    registry = SiteRegistry()
    registry.register(BossAdapter())
    return registry


_REGISTRY: SiteRegistry | None = None


def get_registry() -> SiteRegistry:
    """进程内共享的默认注册表（延迟构建，避免导入期循环依赖）。"""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = default_registry()
    return _REGISTRY


__all__ = ["SiteRegistry", "default_registry", "get_registry"]

