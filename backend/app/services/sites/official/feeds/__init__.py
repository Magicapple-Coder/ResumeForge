"""各套招聘系统的采集适配器：一家系统一个模块。

加一套系统 = 加一个模块 + 在 ``registry`` 里注册一行，业务层不动。
站点知识（端点、字段名、区域、字节上限）只属于这里，不往上层渗。
"""
from .generic import GenericFeed
from .greenhouse import GreenhouseFeed
from .tencent import TencentFeed

__all__ = ["GenericFeed", "GreenhouseFeed", "TencentFeed"]
