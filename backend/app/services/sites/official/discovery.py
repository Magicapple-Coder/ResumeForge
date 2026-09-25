"""按岗位需求发现候选公司。

用户最早的需求是"填入要找的岗位需求，就能拿到官网的实时信息"，而在这之前他得先知道**有哪些
公司**。本模块补的就是这一步：把岗位关键词变成一份候选公司清单，由用户勾选后进入正常的
探测与采集流程。

**它给的是一份线索，不是一份名单。** 这一点必须说在最前面，因为它和这个功能的其他部分
遵循同一条原则——不把不确定说成确定：

- 线索来自公开搜索，所以**只有被索引到、且排在靠前的那些才会出现**。搜不到的公司不代表它
  不在招，只代表这次没搜到；
- 因此界面上**不能**说"共 N 家在招"，只能说"找到 N 条线索"。用户如果当成完整名单，会漏掉
  一大批公司而不自知——那正是这个功能最该避免的错误。

**第三方招聘平台的页面整个剔掉**：把智联、拉勾的页面当成"某公司的官网"去采集是错的，而且
用户会以为那就是官网。判据与助手排序共用同一份实现（``is_third_party_source``）。

**不做"顺手验证"**：本模块一个请求都不发。候选是否真的可用由后续的探测回答——那一步本来
就要做，在这里提前做一遍只会让发现变慢、还要处理同一批失败。
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from ....schemas.setting import SearchConfig
from ...assistant.assistant_web_search import (
    AssistantSearchError,
    is_third_party_source,
)
from ...search.aggregate import aggregate_search
from .urls import host_label, looks_like_careers_index

logger = logging.getLogger(__name__)

# 最多给多少条候选。搜索能返回几十条，但用户是在**勾选**而不是在读，超过这个量就没人看了。
CANDIDATE_LIMIT = 15

# 标题里出现这些词，前面的部分多半就是公司名。**按长到短**匹配：先切「校园招聘」再切
# 「招聘」，否则"腾讯校园招聘"会被切成"腾讯校园"。
_RECRUITMENT_WORDS = (
    "校园招聘",
    "社会招聘",
    "人才招聘",
    "招聘官网",
    "招贤纳士",
    "诚聘英才",
    "加入我们",
    "招聘",
    "诚聘",
    "招贤",
)

# 标题里这些前缀是站点/栏目名，不是公司名。
_TITLE_NOISE_PREFIXES = ("百度知道", "知乎", "CSDN", "博客园", "简书", "搜狐", "网易", "新浪")

SearchFn = Callable[[str, SearchConfig], Awaitable[list[dict[str, str]]]]


@dataclass(frozen=True)
class CompanyCandidate:
    """一条候选：建议的公司名 + 一个看起来是它招聘页的地址。

    ``company`` 是**建议**，由标题或域名猜出来（见 ``_suggest_company``），界面要允许用户改
    ——猜错的代价不该由用户承担（删掉重加）。
    """

    company: str
    url: str
    host: str
    # 为什么认为这是这家公司的招聘页（来源标题），供用户判断。
    evidence: str = ""
    # True → 这个地址本身就是招聘页；False → 是公司站点但看不出招聘页在哪，
    # 交给通用适配器的"多跳找招聘栏目"去处理。
    is_careers_page: bool = True

    @property
    def target_field(self) -> str:
        """这个地址该填进新增公司表单的哪个字段。

        放在这里而不是让界面自己判：界面按地址再猜一遍，就会出现"清单里认成招聘页、提交后却
        被当成首页"这类两边判据不一致的怪现象，而且只有用户会撞上。
        """
        return "careers_url" if self.is_careers_page else "homepage_url"


@dataclass
class DiscoveryResult:
    candidates: list[CompanyCandidate] = field(default_factory=list)
    # 实际发出去的查询。**要给用户看**：他才能判断我们是怎么找的、要不要换个词再找。
    queries: list[str] = field(default_factory=list)
    # 面向用户的说明。找不到时也要说清是"没搜到"而不是"没有公司在招"。
    detail: str = ""


def build_queries(keywords: str, city: str = "") -> list[str]:
    """把岗位需求变成搜索词。

    用**两条**查询换召回：一条通用，一条带上招聘页常见的措辞。真实的中文招聘页大量使用
    「加入我们」这类说法，而它们往往不出现在通用查询的前排结果里。
    """
    cleaned = " ".join(keywords.split())
    if not cleaned:
        return []
    where = " ".join(city.split())
    prefix = f"{cleaned} {where}".strip() if where else cleaned
    return [f"{prefix} 招聘", f"{prefix} 加入我们 招聘"]


def _suggest_company(title: str, host: str) -> str:
    """从标题猜公司名，猜不出就用域名里的标签。

    **两边都是猜**，所以界面必须允许用户改。反过来（不给建议、让用户自己填）等于把这一步
    的手工活全丢回给用户，那这个功能就白做了。
    """
    head = (title or "").strip()
    for prefix in _TITLE_NOISE_PREFIXES:
        if head.startswith(prefix):
            head = head[len(prefix) :].lstrip("-_ |·")
            break
    for word in _RECRUITMENT_WORDS:
        index = head.find(word)
        if index > 0:
            # 公司名在标记**之前**：「示例科技招聘」。
            head = head[:index]
            break
        if index == 0:
            # 标记就在开头，公司名只可能在**它后面**：「招聘 - 某某科技」是常见写法；
            # 而标题**只有**这个标记时（"招聘"），这里切出空串，由下面的兜底接手。
            head = head[len(word) :]
            break
    cleaned = head.strip(" -_|·—,，。:：;；()（）[]【】《》\"'")
    # 切完还是另一个招聘词时同样不算公司名（"招聘 - 加入我们"这类标题确实存在）。
    if len(cleaned) >= 2 and cleaned not in _RECRUITMENT_WORDS:
        return cleaned[:128]
    return host_label(host)[:128]


def _target_field(url: str) -> bool:
    """这个地址自己就是招聘页吗（决定它进 ``careers_url`` 还是 ``homepage_url``）。"""
    host = (urlsplit(url).hostname or "").casefold()
    return looks_like_careers_index(url, page_host=host) or any(
        marker in url.casefold()
        for marker in ("career", "job", "recruit", "zhaopin", "zhiwei", "talent", "campus")
    )


async def discover_companies(
    keywords: str,
    city: str = "",
    *,
    config: SearchConfig,
    search: SearchFn | None = None,
) -> DiscoveryResult:
    """按岗位需求搜出一份候选公司线索。**任何失败都收敛成结果，不抛异常。**

    ``search`` 可注入，测试因此完全离线（``aggregate_search`` 会走真实网络）。默认值在
    **调用时**解析而不是写进参数默认值：写成默认参数则它在导入那一刻就被绑定，之后替换
    ``discovery.aggregate_search`` 不会生效——接口层的用例就只能去替换更深的一层
    （搜索引擎本身），测的东西和想测的错位。
    """
    engine = search or aggregate_search
    queries = build_queries(keywords, city)
    if not queries:
        return DiscoveryResult(detail="请先填写要找的岗位关键词")

    collected: list[dict[str, str]] = []
    for query in queries:
        try:
            collected.extend(await engine(query, config))
        except AssistantSearchError as exc:
            # 单条查询没有结果（或搜索源不配合）不该让整次发现失败——另一条查询可能还有货。
            logger.info("发现查询无结果：%s", exc)

    candidates: list[CompanyCandidate] = []
    seen_hosts: set[str] = set()
    for item in collected:
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        # **第三方平台整个剔掉**，不是降权：把招聘网站的页面当成某公司的官网去采集是错的，
        # 而用户看到它在清单里就会以为那就是官网。
        if is_third_party_source(url):
            continue
        host = (urlsplit(url).hostname or "").casefold()
        if not host or host in seen_hosts:
            continue
        seen_hosts.add(host)
        candidates.append(
            CompanyCandidate(
                company=_suggest_company(str(item.get("title") or ""), host),
                url=url,
                host=host,
                evidence=str(item.get("title") or "").strip()[:200],
                is_careers_page=_target_field(url),
            )
        )
        if len(candidates) >= CANDIDATE_LIMIT:
            break

    if not candidates:
        return DiscoveryResult(
            queries=queries,
            detail=(
                "没有搜到像是用人单位官网的线索。可以换成更具体的岗位名或技术方向，"
                "或者直接把公司名填进「添加公司」——搜不到不代表没有公司在招，"
                "只代表这次公开搜索没找到。"
            ),
        )

    return DiscoveryResult(
        candidates=candidates,
        queries=queries,
        # **必须说清这是线索**：用户把它当完整名单，就会漏掉一大批公司而不自知。
        # 这句话是给用户看的**纯文本**（界面不渲染 markdown），所以不用 ``**`` 加重——
        # 那会在界面上原样显示成星号。
        detail=(
            f"找到 {len(candidates)} 条线索。这些来自公开搜索，"
            "只有被搜到的公司才会出现，不代表在招的公司就这些；勾选后仍要经过识别才算可用。"
        ),
    )


__all__ = [
    "CANDIDATE_LIMIT",
    "CompanyCandidate",
    "DiscoveryResult",
    "SearchFn",
    "build_queries",
    "discover_companies",
]
