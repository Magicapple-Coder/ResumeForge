"""存活校验：某个岗位页现在还在不在招。

**它是对账里唯一能把"待核实"变成硬结论的一步**。站点地图与实抓集合的差额中既可能有漏抓、
也可能有早就招满的历史岗位，逐个访问才能分清。

**两个方向的错误代价差得很远，判据因此不对称**：

- 把「还在招」误判成「已下架」→ 对账会宣称**已确认为全量**，而实际上漏了岗位。这是本功能
  最坏的结果——用户会在漏掉的岗位上投简历而不自知。所以 **``GONE`` 必须有硬证据**。
- 把「已下架」误判成「还在招」→ 结论保守地停在「已确认不全」或「无法确认」。用户多看一眼，
  没有实质损害。

因此 ``GONE`` 只认两种**结构化、非启发式**的证据：

1. **HTTP 404 / 410**——页面确实不存在；
2. **``validThrough`` 已过期**——页面自己声明了有效期，且那是个过去的时刻。

**刻意不做的**：靠"职位已关闭 / no longer accepting applications"这类**文案**判下架。它在多数
站点上确实成立，但误判方向正好是最危险的那一侧，而本项目已经吃过一次同类教训（拦截判据里
一个「登录」单词让每次采集都变成"需要登录"）。要收它，得先有真实样本校准假阳性率——与国内
自建站适配器是同一个理由。在拿到样本之前，判不出来就如实返回 ``UNKNOWN``。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from .base import FeedHttp
from .generic.jsonld import extract_job_postings

logger = logging.getLogger(__name__)

# 还在招。
VERIFIED_LIVE = "live"
# 已下架（有硬证据）。
VERIFIED_GONE = "gone"
# 判不出来（取不到、被阻断、或页面本身给不出信号）。
VERIFIED_UNKNOWN = "unknown"

VERIFY_STATE_LABELS = {
    VERIFIED_LIVE: "仍在招聘",
    VERIFIED_GONE: "已经下架",
    VERIFIED_UNKNOWN: "无法判断",
}

# 校验单个页面的大小上限：只需要其中的结构化数据，不需要整页。
MAX_BYTES = 2_000_000

# 一次最多校验多少个地址。**这是对站点的礼貌约束，不是性能考虑**：待核实候选可能有上千条，
# 逐条访问等于对站点发起一次扫描。核实是抽查，不是补抓。
MAX_VERIFY_PER_RUN = 20


@dataclass(frozen=True)
class Verification:
    url: str
    state: str
    detail: str = ""

    @property
    def conclusive(self) -> bool:
        return self.state in (VERIFIED_LIVE, VERIFIED_GONE)


def _parse_time(value: object) -> datetime | None:
    """解析 ``validThrough`` / ``datePosted`` 这类 ISO 时间串；解析不了返回 ``None``。

    ``fromisoformat`` 在 3.10 上不认末尾的 ``Z``（3.11 才支持），而本项目支持 3.10–3.13，
    所以先把它换成 ``+00:00``。
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    # 没带时区的按 UTC 理解——本功能只判断"是不是过去了"，差几个时区不影响结论。
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def is_expired(valid_through: object, *, now: datetime | None = None) -> bool:
    """``validThrough`` 是否已经过去。**解析不出来时返回 ``False``**（不据此判下架）。"""
    parsed = _parse_time(valid_through)
    if parsed is None:
        return False
    return parsed < (now or datetime.now(timezone.utc))


async def verify_job_url(http: FeedHttp, url: str) -> Verification:
    """查一个岗位页现在还在不在。**任何失败都返回 ``UNKNOWN``，不抛异常。**"""
    if not url.strip():
        return Verification(url=url, state=VERIFIED_UNKNOWN, detail="地址为空")

    result = await http.request("GET", url, max_bytes=MAX_BYTES)

    if result.status_code in (404, 410):
        return Verification(
            url=url, state=VERIFIED_GONE, detail=f"页面不存在（HTTP {result.status_code}）"
        )
    if not result.ok:
        # 被拦住时我们并不知道那边是什么，绝不能因此判它下架。
        return Verification(
            url=url, state=VERIFIED_UNKNOWN, detail=result.detail or "取回失败"
        )

    postings = extract_job_postings(result.text, base_url=url)
    if not postings:
        # 200 但不是岗位页（被重定向到列表页、或页面结构不认识）。**判不出来**——
        # 这类"看起来还在但不是岗位页"的情况正是文案判据会误判的地方。
        return Verification(
            url=url, state=VERIFIED_UNKNOWN, detail="页面还在，但读不到岗位信息"
        )

    for posting in postings:
        if not is_expired(posting.extra.get("valid_through")):
            return Verification(url=url, state=VERIFIED_LIVE, detail=posting.title)
    # 页面里的岗位全都过了有效期：这是站点自己声明的，可以据此判下架。
    return Verification(url=url, state=VERIFIED_GONE, detail="页面声明的有效期已过")


async def verify_all(http: FeedHttp, urls: list[str]) -> list[Verification]:
    """逐个校验（**串行**）。

    刻意不并发：待核实地址最多几十条，而并发会给站点一瞬间的压力峰值——被限流的代价是
    全部返回"无法判断"，比慢一点糟得多。
    """
    return [await verify_job_url(http, url) for url in urls[:MAX_VERIFY_PER_RUN]]


__all__ = [
    "MAX_VERIFY_PER_RUN",
    "VERIFIED_GONE",
    "VERIFIED_LIVE",
    "VERIFIED_UNKNOWN",
    "VERIFY_STATE_LABELS",
    "Verification",
    "is_expired",
    "verify_all",
    "verify_job_url",
]
