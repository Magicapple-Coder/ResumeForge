"""``robots.txt`` 的取回、解析与放行判定。

**这是本功能的前置条件，不是可选项**：采集的对象是用户给的任意公司域名，而"能不能抓这一页"
只有站点自己说了算。判定结果会进对账报告——用户有权知道某次没抓是因为站点不允许。

判定规则（依据 RFC 9309 的通行做法）：

- 取到且允许 → 放行；
- 取到但 disallow → **拒绝采集**，并说明是哪条规则；
- 文件不存在（404/410）→ 视为允许（这是该协议的默认语义，不是我们放宽标准）；
- **取不到（5xx / 网络失败）→ 视为拒绝**。这一条是有意保守的：读不到规则时"假定可以抓"
  等于把"站点正在故障"当成"站点允许"，而故障期恰恰是站点最不希望被压上爬虫的时候。

``crawl_delay`` 与 ``sitemap`` 一并解析出来：前者进限速画像，后者是对账 B 层（集合对账）
的输入——**sitemap 在本项目里的用途是事后核对，不是发现入口**。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from ....models.official import BLOCK_FORBIDDEN
from .base import FeedHttp, FetchResult

ROBOTS_ALLOWED = "allowed"
ROBOTS_DISALLOWED = "disallowed"
ROBOTS_ABSENT = "absent"
ROBOTS_UNREADABLE = "unreadable"

ROBOTS_STATUS_LABELS = {
    ROBOTS_ALLOWED: "站点允许采集",
    ROBOTS_DISALLOWED: "站点不允许采集",
    ROBOTS_ABSENT: "站点未声明 robots.txt（视为允许）",
    ROBOTS_UNREADABLE: "读不到 robots.txt（保守起见视为不允许）",
}

# 状态码语义：404/410 是"文件确实不存在"，其余非 200 一律算读不到。
_ABSENT_STATUSES = frozenset({404, 410})

# 我们对外自称的标识。**不冒充浏览器**——同 ``http.default_user_agent`` 的理由。
USER_AGENT_TOKEN = "ResumeForge"


@dataclass(frozen=True)
class RobotsDecision:
    """一次 robots 判定的结果。"""

    allowed: bool
    status: str
    # 面向用户的说明，直接进对账报告与界面。
    detail: str = ""
    # 站点声明的抓取间隔（秒）；未声明为 None。
    crawl_delay: float | None = None
    # 站点声明的 sitemap 地址，供集合对账使用。
    sitemaps: tuple[str, ...] = field(default_factory=tuple)


def robots_url_for(url: str) -> str:
    """由任意页面地址推出该站点的 robots.txt 地址（总是根路径下）。"""
    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.hostname:
        return ""
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}/robots.txt"


def _extract_sitemaps(text: str) -> tuple[str, ...]:
    """扫 ``Sitemap:`` 行。

    只用 ``RobotFileParser`` 拿不到 sitemap（它不解析该指令），但 sitemap 是**独立于
    放行规则**的一项声明，顺手扫行比再引一个解析器简单得多——它不是需要容错的格式，
    只可能出现在行首。
    """
    found: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, _, value = stripped.partition(":")
        if key.strip().casefold() == "sitemap" and value.strip():
            found.append(value.strip())
    return tuple(found)


def parse_robots(text: str) -> RobotFileParser:
    """把 robots.txt 正文解析成可查询的对象（**不发起任何请求**）。

    显式调用 ``modified()``：``can_fetch`` 在 ``last_checked`` 为空时**一律拒绝**（协议要求
    "读到规则前不得假设可以抓"），所以只 ``parse()`` 而不标记，会把每一份规则都读成全禁。
    """
    parser = RobotFileParser()
    parser.parse(text.splitlines())
    parser.modified()
    return parser


def decision_from_text(
    text: str, url: str, *, user_agent: str = USER_AGENT_TOKEN
) -> RobotsDecision:
    """给一份**已取到**的 robots.txt 正文下判定。"""
    parser = parse_robots(text)
    allowed = parser.can_fetch(user_agent, url)
    sitemaps = _extract_sitemaps(text)

    delay: float | None = None
    try:
        raw_delay = parser.crawl_delay(user_agent)
    except (AttributeError, ValueError):
        raw_delay = None
    if raw_delay is not None:
        delay = float(raw_delay)

    if allowed:
        detail = ROBOTS_STATUS_LABELS[ROBOTS_ALLOWED]
    else:
        detail = (
            f"{ROBOTS_STATUS_LABELS[ROBOTS_DISALLOWED]}：robots.txt 中有规则禁止抓取该地址"
        )

    return RobotsDecision(
        allowed=allowed, status=ROBOTS_ALLOWED if allowed else ROBOTS_DISALLOWED,
        detail=detail, crawl_delay=delay, sitemaps=sitemaps,
    )


async def check_robots(http: FeedHttp, url: str, *, user_agent: str = USER_AGENT_TOKEN) -> RobotsDecision:
    """取回并判定某地址的 robots 规则。

    **任何失败都返回一个判定，不抛异常**：拿不到规则本身就是要如实告诉用户的一件事。
    """
    robots_url = robots_url_for(url)
    if not robots_url:
        return RobotsDecision(
            allowed=False,
            status=ROBOTS_UNREADABLE,
            detail="无法从该地址解析出站点主机名",
        )

    result = await http.request("GET", robots_url)
    if result.status_code in _ABSENT_STATUSES:
        return RobotsDecision(
            allowed=True, status=ROBOTS_ABSENT, detail=ROBOTS_STATUS_LABELS[ROBOTS_ABSENT]
        )
    if not result.ok:
        return RobotsDecision(
            allowed=False,
            status=ROBOTS_UNREADABLE,
            detail=f"{ROBOTS_STATUS_LABELS[ROBOTS_UNREADABLE]}：{result.detail or '取回失败'}",
        )
    return decision_from_text(result.text, url, user_agent=user_agent)


class RobotsAwareHttp(FeedHttp):
    """把 robots 判定装进传输层：**任何**取回都要先过它，适配器无从绕过。

    **为什么必须在传输层，而不是在调用方各查一次**：robots 是**按主机**生效的，而一次采集
    会碰到至少两个主机——用户给的招聘页域名（``boards.example.com``）和适配器实际调的接口
    域名（``api.example.com``）。只查前者的结果是：我们遵守了用户看到的那个站点的规则，
    却对真正被打的接口域名一无所知。堵在这一层就不存在"某个适配器忘了查"这种可能，
    与 SSRF 防护放在同一处的理由完全相同。

    **按主机缓存**：robots.txt 是主机级的，一次采集里同一个主机只查一次。
    """

    def __init__(self, inner: FeedHttp, *, user_agent: str = USER_AGENT_TOKEN) -> None:
        self._inner = inner
        self._user_agent = user_agent
        self._decisions: dict[str, RobotsDecision] = {}

    @classmethod
    def wrap(cls, http: FeedHttp, *, user_agent: str = USER_AGENT_TOKEN) -> RobotsAwareHttp:
        """幂等包装。

        **必须幂等**：嵌套一层本类会导致取 robots.txt 自身时又去查它自己的 robots，
        而那条请求又要先查 robots……递归下去。已经包过就原样返回。
        """
        if isinstance(http, cls):
            return http
        return cls(http, user_agent=user_agent)

    async def decision_for(self, url: str) -> RobotsDecision:
        """该地址所在主机的 robots 判定（带缓存）。"""
        key = robots_url_for(url)
        if not key:
            return RobotsDecision(
                allowed=False, status=ROBOTS_UNREADABLE, detail="无法解析出站点主机名"
            )
        if key not in self._decisions:
            # 走 inner 取 robots，不经过本类的 request——否则就是上面说的递归。
            self._decisions[key] = await check_robots(
                self._inner, url, user_agent=self._user_agent
            )
        return self._decisions[key]

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict | None = None,
        headers: dict[str, str] | None = None,
        max_bytes: int | None = None,
    ) -> FetchResult:
        decision = await self.decision_for(url)
        if not decision.allowed:
            return FetchResult(
                block=BLOCK_FORBIDDEN,
                detail=f"robots.txt 不允许取回该地址：{decision.detail}",
            )
        # crawl-delay 不在这里等待：传输层不该有"等待"语义（那是编排层的限速画像的职责），
        # 而且逐请求 sleep 会让"打了几次"这件事变得数不清。
        return await self._inner.request(
            method,
            url,
            params=params,
            json_body=json_body,
            headers=headers,
            max_bytes=max_bytes,
        )


__all__ = [
    "ROBOTS_ABSENT",
    "ROBOTS_ALLOWED",
    "ROBOTS_DISALLOWED",
    "ROBOTS_STATUS_LABELS",
    "ROBOTS_UNREADABLE",
    "USER_AGENT_TOKEN",
    "RobotsAwareHttp",
    "RobotsDecision",
    "check_robots",
    "decision_from_text",
    "parse_robots",
    "robots_url_for",
]
