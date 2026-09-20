"""比率口径的唯一实现：四舍五入到四位小数，分母为 0 时返回 0.0。

**为什么单独一个叶子模块**：求职看板（``analytics``）需要复用内推模块的转化口径，
所以 ``analytics`` 必须 import ``referral_service``；反过来 ``referral_service`` 就
不能再 import ``analytics``，否则两边成环。而"分子/分母算个比率、空分母给 0"这件事
两边都要用，于是放在一个不依赖任何业务模块的叶子上，由双方共同引用。

放在这里而不是某一方内部，是为了让"百分比保留四位小数"只有一处定义——此前
``analytics._rate`` 与 ``referral_service.referral_stats`` 各写了一份 ``round(..., 4)``。
"""
from __future__ import annotations


def rate(numerator: int, denominator: int) -> float:
    """``numerator / denominator``，保留四位小数；分母为 0 时返回 ``0.0``（不抛除零）。"""
    return round(numerator / denominator, 4) if denominator else 0.0


__all__ = ["rate"]
