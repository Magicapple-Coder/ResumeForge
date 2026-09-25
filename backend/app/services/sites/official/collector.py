"""官网采集编排：翻页、去重、限速、可中断，最后给出对账结论。

与 ``services/apply/collector.py``（投递台的采集）是**两条独立链路**，共享的只有纪律：
每一步之前 ``checkpoint()``（用户点停止要真的停得下来）、去重判据复用同一份实现、
拿到的东西先落「备选岗位」暂存区而不是直接进岗位广场。

与那条链路的三处不同：

1. **结果收敛成对账报告**，而不是只给一个"采到 N 条"。这里真正的产品是
   "到底抓全了没有"，条数只是它的输入之一。
2. **限速按站点画像 + 站点的 crawl-delay 取较大者**。取较大者而不是较小者：站点自己声明的
   间隔是它的底线，我们的默认值只在站点没声明时才作数。
3. **被阻断时立即停止翻页**，不继续试探。继续试只会让情况更糟（更容易被升级封禁），
   而且已经拿到的阻断分类足够让对账给出"无法确认"这个正确答案了。
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from sqlalchemy.orm import Session

from ....models.official import BLOCK_NONE, is_transport_failure
from ....schemas.job import RECOGNITION_SOURCE_OFFICIAL
from ... import trash
from ....models.material import CandidateJob
from ...candidate_jobs import find_staged_candidate, stage_candidate_job
from ...job.job_service import find_job_by_identity
from .base import FeedHttp, FeedJob, FeedPage, FeedTarget, JobFeed
from .generic.listing import METHOD_LABELS, extract_listing
from .generic.memory import SiteMemory
from .reconcile import ReconcileInput, ReconcileReport, reconcile

logger = logging.getLogger(__name__)


def _job_filter_terms(value: str | None) -> tuple[str, ...]:
    """把用户给的一次性岗位筛选拆成少量、可解释的关键词。"""
    if not value:
        return ()
    terms = re.split(r"[,，;；、\n]+", value)
    return tuple(dict.fromkeys(term.strip().casefold() for term in terms if term.strip()))


def _normalize_job_filter(value: str | None) -> str:
    return "、".join(_job_filter_terms(value))


def _job_matches_terms(job: FeedJob, terms: tuple[str, ...]) -> bool:
    haystack = "\n".join(
        str(getattr(job, field, "") or "")
        for field in ("title", "company", "location", "description", "requirements")
    ).casefold()
    return any(term in haystack for term in terms)

# 一次采集最多翻多少页。达到上限**不是"抓完了"**，对账会把终止状态记成"未走完"——
# 这条区分是对账里最容易做错的地方之一。
MAX_COLLECT_PAGES = 30

# 一次采集最多花多少次模型调用（含重试）。
#
# **必须有这个上限，而且是按"一次采集"算的**：单页的上限挡不住"五十个详情页各问一次"。
# 用户自付 key，成本必须可预测；达到上限时如实记进报告，而不是悄悄继续花。
MAX_LLM_CALLS_PER_RUN = 8

# 一次采集最多展开到第几层。**1 表示"入口页 → 它的直接子页"**：接口型适配器永远停在 0
# （一个端点返回全部岗位），列表页型适配器在 1（列表页派发详情页）。再深就是站点的导航
# 结构而不是岗位了，而且自身链接成环会让采集无限递归。
MAX_FETCH_DEPTH = 1


class CollectCancelled(Exception):
    """用户要求停止采集。不是错误，不需要记进失败原因。"""


@dataclass
class OfficialCollectReport:
    """一次采集的账目 + 对账结论。"""

    pages: int = 0
    # **去重后的取回条数**。对总数比的是它，不是 ``stored``：已存在于岗位广场或暂存区的
    # 岗位会被跳过，但它们确实被这一次采集抓到了（见 ``reconcile`` 的模块说明）。
    collected: int = 0
    stored: int = 0
    skipped: int = 0
    # 其中"跳过"里有多少是因为岗位广场的**回收站**里已经有一条（用户之前删过）。
    # 与"早就在库里了"分开计数：两者对用户的含义不同。
    skipped_trashed: int = 0
    # 暂存了、但正文为空的条数——站点漂移唯一留下的痕迹。
    detail_missing: int = 0
    # 每次取回的阻断分类，按发生顺序。
    blocks: list[str] = field(default_factory=list)
    # 每页的 ``(实际解析出的条数, 列表页自称条数)``。
    page_counts: list[tuple[int, int | None]] = field(default_factory=list)
    reached_page_limit: bool = False
    # 用户这次设的条数上限命中时的那个数（``None`` = 没设/没命中）。
    #
    # **与 ``reached_page_limit`` 分开记**：两者都会让列表"没走完"，但一个是工具的边界、
    # 一个是用户自己的决定，报告里的说法必须不同——说成"页数上限"会让设了 20 条的用户
    # 去翻一个他根本没碰过的设置。
    hit_job_limit: int | None = None
    last_has_more: bool = False
    total_hint: int | None = None
    # 总请求数仍写入 ``pages``，但页数纪律只看列表/分页页，详情页不应挤占上限。
    listing_pages: int = 0
    pagination_seen: bool = False
    # 本次临时岗位筛选条件；不落公司配置，只跟随运行记录保存。
    job_filter: str = ""
    # 采集到的岗位快照，供历史报告回看；即使候选后来被导入/删除，历史仍有可读内容。
    collected_jobs: list[dict[str, Any]] = field(default_factory=list)
    collected_urls: set[str] = field(default_factory=set)
    reconcile: ReconcileReport | None = None
    # 这次对账**用的输入**。存下来是为了事后能原样重放——存活校验会往里面补核实结果、
    # 再算一遍结论；从运行记录反推输入既脆弱又会悄悄偏离原值。
    reconcile_input: ReconcileInput | None = None
    # 提前中止的原因（被阻断 / 用户停止），供界面显示。
    stopped_reason: str = ""
    # 因为超过层级上限而没有跟进的地址数。**它不中止采集**（见循环里的说明），只是记下来：
    # 报告里要能回答"为什么这次只翻了这么几页"。
    deep_links_skipped: int = 0
    # 站点地图那层的说明被替换时的正文（见 ``_usable_expectations``）。为空表示用调用方给的。
    sitemap_note: str = ""
    # ===== 抽取方式（阶段 2）=====
    # 本次的模型调用次数。**用户自付 key，必须可查**。
    llm_calls: int = 0
    # 本次归纳并成功存下的配方数。
    recipes_learned: int = 0
    # 逐页的抽取说明（"这一页是怎么读出来的"），报告里如实展示。
    extraction_notes: list[str] = field(default_factory=list)
    # 本次改了站点记忆（配方或"问过没读出来"的记录），由调用方写回。
    memory: SiteMemory | None = None

    @property
    def blocked(self) -> bool:
        return any(is_transport_failure(block) for block in self.blocks)


def _diff(expected: frozenset[str], collected: set[str]) -> frozenset[str]:
    """可枚举全集里、实抓没有的地址。

    两边都做一次规整（去空白、去尾部斜杠）：站点地图与岗位链接对同一页面的写法常常差一个
    斜杠，逐字比较会把它们当成两个地址，凭空造出一堆"没抓到"。
    """
    normalized_collected = {_normalize_url(url) for url in collected}
    return frozenset(
        url for url in expected if _normalize_url(url) not in normalized_collected
    )


def _host_of(url: str) -> str:
    """地址的主机名（小写）。集合对账要判断"两边说的地址是不是同一个地址空间"。"""
    try:
        return (urlsplit(url).hostname or "").casefold()
    except ValueError:
        return ""


def _normalize_url(url: str) -> str:
    # 去片段：``/jobs/1#apply`` 与 ``/jobs/1`` 是同一页。站点地图与实际抓到的地址写法经常
    # 只差一个片段，不去掉会凭空造出一堆"没抓到"的差额。
    cleaned = url.strip().split("#", 1)[0].rstrip("/")
    return _without_tracking(cleaned).casefold()


# 已知的**跟踪类**查询参数：它们只说明"这个链接是从哪来的"，不影响页面内容。
#
# **为什么必须去掉**：站点自己在页面里给出的链接常常带这些。实测某站——列表页给出的岗位地址
# 是干净的 ``…/position/<id>/detail``，而详情页里「相关职位」的链接是
# ``…/position/<id>/detail?recomId=…&sourceJobId=…``。两者判重不相等，于是**同一条岗位被当成
# 两条**：备选岗位里多出一行重复记录，``collected`` 也跟着多计。
#
# **不能反过来"一概去掉整个查询串"**：有些站点把岗位 id 放进查询参数（``?jobId=123``），
# 全去掉会把整站岗位压成一条——那是比重复严重得多的错。所以这里只认名单。
_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAMS = frozenset(
    {
        "recomid", "sourcejobid", "ref", "referer", "referrer", "from", "spm", "src",
        "trackingid", "tracking_id", "trk", "trk_module", "fbclid", "gclid", "msclkid",
        "share_token", "sharetoken", "gh_src", "lever-origin", "lever-source",
        "jobboard", "job_board", "jobboardid",
    }
)


def _is_tracking_param(name: str) -> bool:
    lowered = name.casefold()
    return lowered in _TRACKING_PARAMS or lowered.startswith(_TRACKING_PARAM_PREFIXES)


def _without_tracking(url: str) -> str:
    """去掉跟踪参数。**没去掉任何东西时原样返回**——重建查询串会改动它的写法（编码、
    顺序），而绝大多数地址根本没有跟踪参数，不该被顺手改写。
    """
    parts = urlsplit(url)
    if not parts.query:
        return url
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    kept = [(name, value) for name, value in pairs if not _is_tracking_param(name)]
    if len(kept) == len(pairs):
        return url
    return urlunsplit(parts._replace(query=urlencode(kept)))


def _staged_record_by_url(session: Session, page_url: str) -> Any | None:
    """按地址找一条**上一轮就已经在库里**的待处理候选。

    只找**正文还空着**的那些：已经填过的行不用再看，而这一条限制顺带把扫描范围压到"还没补上
    正文的岗位"——没它的话每取一页详情就要把整个候选表过一遍。

    地址比较走 ``_normalize_url``（**两边都过**）：库里那批可能是"去掉跟踪参数"这条规则生效
    之前落的（实测用户的库里 42 行带着 ``?recomId=…``），拿原始字符串比会一条都对不上，
    而表现正是"正文明明取回来了却一条也补不进去"。
    """
    target = _normalize_url(page_url)
    if not target:
        return None
    rows = (
        session.query(CandidateJob)
        .filter(CandidateJob.description == "")
        .all()
    )
    for row in rows:
        if _normalize_url(str(row.source_url or "")) == target:
            return row
    return None


def _attributed(job: FeedJob, site: OfficialSiteLike) -> FeedJob:
    """岗位没有公司名时，用**源**的公司名补上。

    适配器不知道自己在采哪家公司——它只拿到一个地址。而"这家公司叫什么"是用户建源时填的，
    也是唯一权威的来源（页面上的 ``hiringOrganization`` 常常缺失，或者写的是集团里另一家的
    名字）。留空的话，暂存区里会是一堆没有公司名的岗位，用户没法按公司筛选也没法判断来源。
    """
    if job.company.strip() or not site.company.strip():
        return job
    return replace(job, company=site.company)


def _target_matches_job(target: FeedTarget, job: FeedJob) -> bool:
    """判断详情目标是否对应列表页里的这条岗位。"""
    post_id = str(target.params.get("post_id") or "").strip()
    external_id = job.external_id.strip()
    if post_id and external_id:
        return post_id == external_id
    if not target.endpoint or not job.url:
        return False
    return _normalize_url(target.endpoint) == _normalize_url(job.url)


def _targets_for_jobs(targets: list[FeedTarget], jobs: list[FeedJob]) -> list[FeedTarget]:
    """只保留与选中岗位对应的详情页目标。

    先用岗位 id / URL 精确匹配，匹配不到的才按同页顺序兜底。这样条数上限截断一页时，
    仍然会读取选中岗位的详情，而不会把整页五十个详情页都排进队列。
    """
    if not targets or not jobs:
        return []
    selected: list[FeedTarget] = []
    used: set[int] = set()
    for index, job in enumerate(jobs):
        match = next(
            (
                target_index
                for target_index, target in enumerate(targets)
                if target_index not in used and _target_matches_job(target, job)
            ),
            None,
        )
        if match is None:
            if index < len(targets) and index not in used:
                match = index
            else:
                match = next(
                    (target_index for target_index in range(len(targets)) if target_index not in used),
                    None,
                )
        if match is None:
            break
        used.add(match)
        selected.append(targets[match])
    return selected


# 能区分"两条不同岗位"的字段。**只有没有地址、只能靠标题认时才用得上**：
# 两条无地址、同标题同公司的记录，只要这几项里有一项两边都有值却不一样，它们就是两个岗位。
# ``description`` 刻意不在其列——它正是我们想补的那个字段，不算身份。
_DISCRIMINATING = ("location", "posted_at", "job_type", "salary")


def _discriminators(job: FeedJob) -> tuple[str, ...]:
    return tuple(
        str(getattr(job, name, "") or "").strip().casefold() for name in _DISCRIMINATING
    )


class StagedIndex:
    """本轮已落暂存区的记录，**两个索引、两种判据**。

    "同一条岗位"有两个独立信号：

    - **地址相同**——列表页与详情页对同一个岗位给出的标题常常不一样（一个来自锚文本、一个来自
      结构化数据），只按标题看会把它们当成两条，用户在暂存区里就看到同一岗位两遍；
    - **标题 + 公司相同，且两边至少有一边没有地址**——结构化数据里常常不带 ``url``，那条记录
      只能靠标题认。

    **两边都有地址却对不上**时一律当成两条：同一家公司不同城市各招一个同名岗位很常见，
    猜错会把一家的正文写到另一家那条记录上。

    只有标题可用时还要**再核一层字段**（见 ``_agree``）：两条无地址、同标题同公司、但地点不同的
    岗位确实是两个岗位，光看标题会吞掉一条——而"少一条"和"多一条"一样是错。
    """

    def __init__(self) -> None:
        self._by_url: dict[str, Any] = {}
        # 一个标题可能对应多条（同名不同城市的岗位），所以是列表而不是单值。
        # 每项是 ``(记录, 这条记录有没有地址)``——判断能不能靠标题合并要用到后者。
        self._by_title: dict[tuple[str, str], list[tuple[Any, bool]]] = {}

    @staticmethod
    def _title_key(job: FeedJob) -> tuple[str, str]:
        return (job.title.strip().casefold(), job.company.strip().casefold())

    @staticmethod
    def _agree(record: Any, job: FeedJob) -> bool:
        """两条记录**互不矛盾**吗。见 ``key_for`` 与 ``_DISCRIMINATING`` 的说明。"""
        for name in _DISCRIMINATING:
            mine = str(getattr(record, name, "") or "").strip()
            theirs = str(getattr(job, name, "") or "").strip()
            if mine and theirs and mine != theirs:
                return False
        return True

    @staticmethod
    def key_for(job: FeedJob) -> str:
        """这条岗位在**本轮**的计数键。

        与 ``find`` 的判据是两件事，刻意分开：``find`` 回答"这是不是我已经落下的那条"（用于
        合并字段），这里回答"这一轮我是不是已经数过它了"（用于计数）。**合成一件事会出错**：
        上一轮就在库里的岗位不会被本次落库，于是每一页再遇到它都会被当成新的一条计进
        ``collected``——报告里的条数会凭空翻好几倍，而对账正是拿这个数去比总数的。

        没有地址时，键里必须带上**能区分两条岗位的那几项**（地点、时间…）：两条无地址、同标题
        同公司、地点不同的岗位是两个岗位，只用标题当键会把后一条当成"已经数过"直接跳过——
        用户看不到它，而报告还会说"只抓到 1 条、站点声明 2 条"，凭空造出一句漏抓警报。
        """
        url = job.url.strip()
        if url:
            return f"url:{_normalize_url(url)}"
        title = job.title.strip().casefold()
        company = job.company.strip().casefold()
        return f"t:{title}|{company}|{'|'.join(_discriminators(job))}"

    def _sole_match(self, job: FeedJob, *, require_no_url: bool) -> Any | None:
        """标题 + 公司命中的记录，**且只有一条、字段不矛盾**时才认。

        有多条同名记录时无从判断这次说的是哪一个——把正文补到错误的那条上，比不补糟得多。

        ``require_no_url`` 为真时只认"那条记录本身没有地址"：这次带了地址却对不上、而暂存里
        那条**有**地址，说明它们是两个岗位（同名不同城市很常见）。
        """
        matches = [
            record
            for record, had_url in self._by_title.get(self._title_key(job), [])
            if (not require_no_url or not had_url) and self._agree(record, job)
        ]
        return matches[0] if len(matches) == 1 else None

    def find(self, job: FeedJob) -> Any | None:
        url = job.url.strip()
        if not url:
            # 这次没有地址，只能靠标题认（结构化数据里经常不带 ``url``）。
            return self._sole_match(job, require_no_url=False)
        found = self._by_url.get(_normalize_url(url))
        if found is not None:
            return found
        # 地址对不上时**只在"暂存里那条根本没有地址"时**才退回标题：那种记录除了标题没有别的
        # 线索，而它多半就是这次的这一条（同一页里先读到无地址的摘要版、再读到带地址的完整版）。
        # 两边都有地址却不同则一律当成两条。
        return self._sole_match(job, require_no_url=True)

    def find_by_url(self, url: str) -> Any | None:
        """按**地址**查本轮已落的记录。``None`` = 这一页不是任何一条已暂存岗位的页。

        ``find`` 干不了这件事：它的判据里有标题，而页面级的正文回填**没有标题可用**——
        这一页的正文该给谁，唯一的判据是"那条岗位的地址就是这一页"。**不退回按标题猜**：
        一页的正文与列表页给出的条目名之间没有可靠对应，猜错就是把 A 的正文写到 B 那条记录上。

        空地址不查（同 ``find``）：没有地址的页面认不出是"哪一条岗位的页"。
        """
        cleaned = (url or "").strip()
        if not cleaned:
            return None
        return self._by_url.get(_normalize_url(cleaned))

    def add(self, job: FeedJob, record: Any) -> None:
        url = job.url.strip()
        if url:
            self._by_url[_normalize_url(url)] = record
        # **两个索引都登记**：这次有地址的那条，下次可能由一条没有地址的记录来描述
        # （结构化数据里经常不带 ``url``），那时只有标题这条线索可用。
        self._by_title.setdefault(self._title_key(job), []).append((record, bool(url)))


class OfficialSiteLike(Protocol):
    """采集需要的站点信息。用 Protocol 而不是直接吃 ORM 对象，测试里给个简单对象即可。"""

    company: str
    endpoint: str
    params: dict[str, Any]
    min_interval_seconds: int
    max_per_hour: int
    # 这一站攒下的抽取知识（配方 + "问过没读出来"的页面）。采集结束后由调用方写回。
    recipe: dict[str, Any]


class OfficialCollector:
    """官网采集编排器。

    ``sleeper`` / ``clock`` 注入是为了测试：限速逻辑必须能在毫秒级验证，而不是真的等十几秒
    （项目的既有做法——"慢的用例要优化，不是删掉"）。
    """

    def __init__(
        self, *, max_pages: int = MAX_COLLECT_PAGES, max_jobs: int | None = None
    ) -> None:
        self._max_pages = max_pages
        # 用户这次设的条数上限。``None`` = 没设，也就是只有页数上限在管（今天的行为）。
        #
        # 与 ``max_pages`` 是两个不同性质的东西：页数上限是**工具的纪律**（保护站点、也防止
        # 一次点下去十分钟回不来），不由用户配置；条数上限是**用户的决定**——"这个站有一万个
        # 岗位，我只要前几十条看看"。所以命中时要记的是哪个上限，报告里的说法完全不同。
        self._max_jobs = max_jobs

    async def run(
        self,
        *,
        session: Session,
        site: OfficialSiteLike,
        feed: JobFeed,
        http: FeedHttp,
        crawl_delay_seconds: float | None = None,
        checkpoint: Callable[[], None] | None = None,
        sleeper: Callable[[float], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        expected_urls: frozenset[str] = frozenset(),
        on_progress: Callable[[OfficialCollectReport], None] | None = None,
        extractor: Any = None,
        job_keywords: str | None = None,
        task_id: int | None = None,
    ) -> OfficialCollectReport:
        """采一次。任何失败都收敛进 ``report``，不抛异常（``CollectCancelled`` 除外）。

        ``extractor`` 是配方与模型那一级的执行者（见 ``generic/listing.py``）。它是**可选**的：
        没配模型时为 ``None``，此时前两级照常工作，只是读不出来的页面如实说明"没配模型"。
        """
        check = checkpoint or (lambda: None)
        sleep = sleeper or asyncio.sleep
        report = OfficialCollectReport()
        report.job_filter = _normalize_job_filter(job_keywords)
        target = FeedTarget(
            feed_key=feed.key, endpoint=site.endpoint, params=dict(site.params or {})
        )
        interval = self._interval(site, crawl_delay_seconds)
        # 站点记忆只在通用路径上有意义：接口型适配器读的是契约，没有"页面结构"可记。
        report.memory = SiteMemory.from_blob(site.recipe) if feed.supports_recipes else None

        def still_running() -> bool:
            """跑一次检查；用户要求停止时返回 False 并记下原因。

            取消信号在**每一个**检查点都收敛成同一个返回值，而不是靠 try/except 只包住循环
            顶部——那样在 ``_ingest`` 里抛出的取消会一路逃逸出去，用户看到的是"采集失败"
            而不是"已停止"。
            """
            if report.stopped_reason:
                return False
            try:
                check()
            except CollectCancelled:
                report.stopped_reason = "已停止"
                return False
            return True

        # 本轮已落暂存区的记录（用于合并字段），以及本轮已计过数的岗位（用于计数）。
        # 两者**不能合并成一个**：上一轮就在库里的岗位不会被本次落库，只有计数那一份认得它。
        staged = StagedIndex()
        seen: set[str] = set()
        last_request_at: float | None = None

        # 待取地址队列：``(目标, 游标)``。接口型适配器靠游标自我续接（队列里始终只有一个目标），
        # 列表页型适配器靠 ``next_targets`` 派发详情页。**队列走空就是"确认到底"**——
        # 这是唯一不需要额外信号即可成立的终止条件。
        queue: deque[tuple[FeedTarget, str]] = deque([(target, "")])
        # 已经取过的地址，防止站点自身链接成环时反复取同一页。
        # **入口地址要一开始就记进去**：详情页指回入口是极常见的站点结构，不记的话
        # 入口会被取两次，而第二次多半只会再派发一遍那批详情页。
        visited: set[str] = {self._target_key(target)}

        while True:
            # **先看队列空不空，再看页数**：反过来会把"恰好翻到上限、而且列表确实走完了"
            # 报成"达到页数上限，列表尚未走完"——一句假话，而且它会作为终止依据进报告、
            # 被存进对账输入、在存活校验时被原样重放。
            if not queue:
                break
            queued_target = queue[0][0]
            is_listing_page = (
                queued_target.depth == 0 or queued_target.target_kind == "pagination"
            )
            if is_listing_page and report.listing_pages >= self._max_pages:
                report.reached_page_limit = True
                break
            if not still_running():
                break

            current, cursor = queue.popleft()
            last_request_at = await self._throttle(last_request_at, interval, clock, sleep)
            page = await feed.fetch_page(http, current, cursor=cursor)
            report.pages += 1
            if is_listing_page:
                report.listing_pages += 1
            if current.target_kind == "pagination":
                report.pagination_seen = True
            report.blocks.append(page.block)

            if page.block != BLOCK_NONE:
                # 不在被阻断后继续取：继续试只会让升级封禁更容易，而当前的阻断分类已经
                # 足够让对账给出正确答案（"无法确认"）。
                report.stopped_reason = page.detail or "取回失败"
                break

            page = await self._fill_from_listing(
                page,
                current,
                site=site,
                feed=feed,
                report=report,
                extractor=extractor,
                still_running=still_running,
            )
            page = self._restrict_generic_detail_jobs(page, current, feed)
            page = self._filter_page_jobs(page, current, report.job_filter)
            page = self._trim_to_job_budget(page, current, report, seen)

            if page.total_hint is not None and report.total_hint is None:
                report.total_hint = page.total_hint
            # 只对**带岗位的那次取回**记条数账：派发地址的那一次没有条数可比，
            # 记进去会凭空造出一堆"解析出的条数与页面自称不符"的假漂移。
            if page.jobs or page.claimed_count is not None:
                report.page_counts.append((len(page.jobs), page.claimed_count))
            # 公司名在**这里**统一补：适配器只认得地址，不认得"我们采的是哪家公司"。
            # 在这一步做，适配器给出的、以及上层兜底给出的岗位走的是同一条规则。
            attributed = [_attributed(job, site) for job in page.jobs]
            self._ingest(
                session,
                report,
                attributed,
                staged,
                seen,
                still_running,
                task_id=task_id,
            )
            # **正文回填排在 ``_ingest`` 之后**，顺序不能反：两级都是"只补空"，所以先落的那一份赢。
            # 排在这里 = JSON-LD / 配方 / 模型给出的正文优先，这一级只补仍然空着的字段；
            # 反过来则是这个**启发式**规则抢在作者声明的结构化数据前面占位，把优先级表倒过来写。
            self._fill_page_body(report, current.endpoint, page, staged, session)
            # 进度在**每一页之后**上报：多页站点可能跑好几分钟，不报的话用户既不知道进展，
            # 也分不出它是在慢慢跑还是卡住了。
            if on_progress is not None:
                on_progress(report)
            if report.stopped_reason:
                break

            # 用户设的条数上限：抓够了就停翻页，但**当前页已经选中的详情页仍要取**。
            #
            # ``_trim_to_job_budget`` 已经把列表页裁到预算内，并同步裁了它派发的详情目标。
            # 因此这里不能像旧实现那样直接 ``break``：那会让列表岗位只有标题，正文回填永远
            # 没机会发生。详情页自己再派发的相关岗位则在下面被挡住。
            job_limit_reached = (
                self._max_jobs is not None and report.collected >= self._max_jobs
            )
            if job_limit_reached:
                report.hit_job_limit = self._max_jobs
            else:
                report.last_has_more = page.has_more
                if page.has_more:
                    if not page.cursor:
                        # 站点说还有下一页、却没给游标：我们无法继续。**记成"没走完"**，
                        # 不能当作抓到底了——那会把一次不完整的采集报成全量。
                        report.stopped_reason = "站点声明还有下一页，但没有给出继续翻页的游标"
                        break
                    queue.append((current, page.cursor))

            # 达到条数上限后，详情页里的"相关岗位"不是用户选中的岗位，不再继续追；
            # 列表页的目标已经在裁剪阶段只留下了当前预算内的岗位详情。
            next_targets = page.next_targets if current.depth == 0 or not job_limit_reached else []
            for next_target in next_targets:
                if next_target.depth > MAX_FETCH_DEPTH:
                    # 站点结构比预期的深：**跳过这一个链接，继续采其余的**。
                    #
                    # 这里曾经写成 ``report.stopped_reason = ...``，而那个字段的语义是"整次采集
                    # 就此中止"——于是一个详情页里的"相关岗位"链接就足以让采集停在第一页，
                    # 而报告只会说"层级超过上限"，看起来像是站点的问题。深度上限要防的是
                    # **无限递归**（自身链接成环），防它的办法是不跟进，不是不采了。
                    report.deep_links_skipped += 1
                    continue
                key = self._target_key(next_target)
                if key in visited:
                    continue
                visited.add(key)
                queue.append((next_target, ""))

        usable_expected = self._usable_expectations(expected_urls, report)
        report.reconcile_input = ReconcileInput(
            total_hint=report.total_hint,
            collected=report.collected,
            stored=report.stored,
            skipped=report.skipped,
            blocks=tuple(report.blocks),
            reached_page_limit=report.reached_page_limit,
            job_limit=report.hit_job_limit or 0,
            last_has_more=report.last_has_more,
            page_counts=tuple(report.page_counts),
            cancelled=report.stopped_reason == "已停止",
            paginates=feed.paginates or report.pagination_seen,
            job_filter=report.job_filter,
            stop_detail=report.stopped_reason if not report.collected else "",
            # 站点地图给的"可枚举全集"由调用方取回并筛好（那是它的职责：只有它知道
            # 站点的 robots 结论与主机名）。这里只把它与实际抓到的地址**做差**，
            # 因为集合对账要的只是差额本身。
            enumerated_total=len(usable_expected),
            candidates=_diff(usable_expected, report.collected_urls),
        )
        report.reconcile = reconcile(report.reconcile_input)
        if report.llm_calls:
            report.extraction_notes.append(
                f"本次共调用大模型 {report.llm_calls} 次"
            )
        return report

    def _trim_to_job_budget(
        self,
        page: FeedPage,
        current: FeedTarget,
        report: OfficialCollectReport,
        seen: set[str],
    ) -> FeedPage:
        """在列表页裁剪岗位与详情目标，保证条数上限只限制入账岗位。

        详情页不能裁：列表页已经选中的岗位正需要靠它补正文。接口型适配器和通用网页
        适配器都在第 0 层给出列表，所以只在这里处理；``max_jobs=None`` 完全沿用旧路径。
        """
        if self._max_jobs is None or current.depth != 0:
            return page
        # 这一页已经覆盖站点声明的全部岗位时，不能为了满足一个较小的用户上限而把硬证据
        # 截掉：``collected == total_hint`` 仍然代表确实抓全了。真正的长列表（例如腾讯的
        # 906 条、单页 50 条）不会命中这里，仍按用户上限裁剪。
        if page.total_hint is not None and page.total_hint == len(page.jobs) and not page.has_more:
            return page
        remaining = self._max_jobs - report.collected
        if remaining <= 0:
            return replace(page, jobs=[], next_targets=[])
        if not page.jobs:
            # 纯列表页形状：岗位要到详情页才出现，先把待取详情数限制住。
            pagination_targets = [
                target for target in page.next_targets if target.target_kind == "pagination"
            ]
            detail_targets = [
                target for target in page.next_targets if target.target_kind != "pagination"
            ]
            return replace(
                page,
                next_targets=detail_targets[:remaining] + pagination_targets,
            )

        selected: list[FeedJob] = []
        reserved: set[str] = set()
        for job in page.jobs:
            key = StagedIndex.key_for(job)
            is_new = key not in seen and key not in reserved
            if is_new:
                if len(reserved) >= remaining:
                    continue
                reserved.add(key)
            # 已见过的岗位仍可保留，用来合并本页更完整的字段；它不消耗新的岗位预算。
            selected.append(job)
        return replace(
            page,
            jobs=selected,
            next_targets=(
                _targets_for_jobs(
                    [target for target in page.next_targets if target.target_kind != "pagination"],
                    selected,
                )
                + [target for target in page.next_targets if target.target_kind == "pagination"]
            ),
        )

    @staticmethod
    def _filter_page_jobs(page: FeedPage, current: FeedTarget, job_filter: str) -> FeedPage:
        """按本次临时关键词筛选岗位，但保留分页目标继续向后走。"""
        terms = _job_filter_terms(job_filter)
        if not terms or not page.jobs:
            return page
        selected = [job for job in page.jobs if _job_matches_terms(job, terms)]
        detail_targets = [
            target for target in page.next_targets if target.target_kind != "pagination"
        ]
        pagination_targets = [
            target for target in page.next_targets if target.target_kind == "pagination"
        ]
        # 详情页不匹配时不能把它的正文回填到旧候选；列表页没有自身归属的岗位，正文保留无害。
        body = page.body if current.depth == 0 or selected else ""
        body_requirements = page.body_requirements if current.depth == 0 or selected else ""
        return replace(
            page,
            jobs=selected,
            next_targets=_targets_for_jobs(detail_targets, selected) + pagination_targets,
            body=body,
            body_requirements=body_requirements,
        )

    @staticmethod
    def _restrict_generic_detail_jobs(
        page: FeedPage, current: FeedTarget, feed: JobFeed
    ) -> FeedPage:
        """详情页只允许回传与当前地址对应的岗位，避免把相关链接当成新岗位。

        通用网页路径会在详情页上再次看到导航、上一篇/下一篇和相关职位链接；列表页已经决定
        了本次要采哪一条，详情页的作用是补正文，不是重新发现一批岗位。接口型适配器不走这
        条规则，因为它们的详情 endpoint 与岗位 URL 可能本来就不同（例如腾讯）。
        """
        if current.depth <= 0 or not feed.supports_recipes or not page.jobs:
            return page
        target_url = _normalize_url(current.endpoint)
        jobs = [
            job
            for job in page.jobs
            if job.url and _normalize_url(job.url) == target_url
        ]
        return replace(page, jobs=jobs, next_targets=[])

    def _usable_expectations(
        self, expected_urls: frozenset[str], report: OfficialCollectReport
    ) -> frozenset[str]:
        """站点地图给的"可枚举全集"这次能不能用来对账。不能用时返回空集，并把原因记下来。

        **站点地图按"站点自己的主机"取，而岗位地址常常在另一个主机上**（招聘系统托管）：
        用户填 ``acme.com/careers``、探测识别出托管在某招聘系统的职位板，抓到的地址全在
        ``boards.…`` 上。这时两个集合**永远不相交**，差额会等于**整张地图**——报告写
        "N 个岗位页没抓到，需要核实"，核实完还会升级成"已确认不全：核实到 N 个仍在招聘"，
        而实际一条都没漏。

        两个地址空间对不上时，集合对账这一层**没有可比对的依据**，如实说明比硬比强。
        """
        if not expected_urls or not report.collected_urls:
            # 一条都没抓到时不判：那时"地图里的都没抓到"可能正是事实。
            return expected_urls
        expected_hosts = {_host_of(url) for url in expected_urls}
        collected_hosts = {_host_of(url) for url in report.collected_urls}
        if expected_hosts & collected_hosts:
            return expected_urls
        report.sitemap_note = (
            "站点地图覆盖的是 "
            f"{'、'.join(sorted(expected_hosts))}，而这次抓到的岗位地址在 "
            f"{'、'.join(sorted(collected_hosts))}——两者不在同一主机，没法比对，"
            "这一层这次不参与对账"
        )
        return frozenset()

    async def _fill_from_listing(
        self,
        page: FeedPage,
        current: FeedTarget,
        *,
        site: OfficialSiteLike,
        feed: JobFeed,
        report: OfficialCollectReport,
        extractor: Any,
        still_running: Callable[[], bool],
    ) -> FeedPage:
        """适配器读不出岗位时，试配方与模型两级。返回（可能被补上岗位的）这一页。

        **只在两种页面上试**：入口页，以及这一页自己派发出了岗位链接的页面。详情页读不出东西
        是个死胡同，不是"我们没读懂列表页"——不加这条区分，五十个详情页就会各问一次模型。
        """
        if not feed.supports_recipes or page.jobs or not page.raw:
            return page
        if current.depth != 0 and not page.next_targets:
            return page
        if not still_running():
            return page
        if report.llm_calls >= MAX_LLM_CALLS_PER_RUN:
            # 成本上限踩到了：如实记下来，而不是悄悄继续花用户的钱。
            report.extraction_notes.append(
                f"已达本次采集的模型调用上限（{MAX_LLM_CALLS_PER_RUN} 次），不再尝试读更多页面"
            )
            return page

        assert report.memory is not None  # feed.supports_recipes 为真时它一定已建好
        result = await extract_listing(
            page.raw,
            current.endpoint,
            memory=report.memory,
            extractor=extractor,
            # 剩余额度：单页自己最多花 4 块 × 2 次重试，只在页与页之间检查上限的话，
            # 一次采集实际能花到上限的近两倍——而那笔钱是用户自己出的。
            call_budget=MAX_LLM_CALLS_PER_RUN - report.llm_calls,
        )
        report.llm_calls += result.calls
        if result.learned:
            report.recipes_learned += 1
        label = METHOD_LABELS.get(result.method, result.method)
        note = f"{current.endpoint}：{label}"
        if result.detail:
            note = f"{note}（{result.detail}）"
        if page.detail:
            # 传输层的说明（渲染被截断、浏览器取回失败…）**不能丢**：它常常才是"为什么读不出来"
            # 的答案，而上面那句只说明抽取层没读出东西。丢掉它的后果不是少一句话，是**报告在
            # 说一句关于页面的假话**——"这一页没有可辨认的站内链接"，而真相是内容在取回时被截掉了。
            note = f"{note}（{page.detail}）"
        report.extraction_notes.append(note)

        if not result.jobs:
            return page

        # **不清空 ``next_targets``**：这两级给出的是条目名与少量字段、**不含正文**，详情页
        # 仍可能带着完整的职位描述。合并由 ``StagedIndex`` 负责，所以不会变成两条。
        return replace(
            page,
            jobs=[
                FeedJob(
                    title=job.title,
                    location=job.location,
                    url=job.url,
                    posted_at=job.posted_at,
                )
                for job in result.jobs
            ],
        )

    @staticmethod
    def _target_key(target: FeedTarget) -> str:
        """一个地址的判重键。**不含 depth**：同一个地址无论在第几层都是同一个页面。"""
        return f"{target.endpoint}|{sorted(target.params.items())}"

    @staticmethod
    def _interval(site: OfficialSiteLike, crawl_delay_seconds: float | None) -> float:
        """站点声明的 crawl-delay 与本地画像取**较大者**。

        取较大者而不是较小者：crawl-delay 是站点自己划的底线，我们的默认值只在站点没声明时
        才作数。反过来（取较小者）等于用本地默认值去覆盖站点的明确要求。
        """
        declared = max(float(crawl_delay_seconds or 0.0), 0.0)
        return max(float(site.min_interval_seconds or 0), declared)

    @staticmethod
    async def _throttle(
        last_request_at: float | None,
        interval: float,
        clock: Callable[[], float],
        sleeper: Callable[[float], Any],
    ) -> float:
        """必要时等待，返回本次请求发生的时刻。"""
        now = clock()
        if last_request_at is not None and interval > 0:
            wait = interval - (now - last_request_at)
            if wait > 0:
                await sleeper(wait)
                now = clock()
        return now

    def _ingest(
        self,
        session: Session,
        report: OfficialCollectReport,
        jobs: list[FeedJob],
        staged: StagedIndex,
        seen: set[str],
        still_running: Callable[[], bool],
        *,
        task_id: int | None = None,
    ) -> None:
        """把一页岗位去重、落暂存区并记账。

        ``staged`` 是本轮已经落库的记录，用来把同一个岗位的两次取回合并：列表页给得出条目名与
        地址、给不出正文，详情页给得出正文——说的是同一条岗位，该合成一条，而不是留两条或者
        丢掉更全的那一份。``seen`` 是**计数**用的本轮去重（见 ``StagedIndex.key_for``）。
        """
        for job in jobs:
            if not still_running():
                # 用户停止了：这一页里还没处理的不再暂存。已暂存的那部分账目仍然有效。
                return
            # **两个判断各自独立**，因为它们回答的是两个问题：
            # ``find`` 问"这是不是我本轮落下过的那条"（用于合并字段），``key`` 问"这一轮数过它
            # 没有"（用于计数）。合一就会出错——两条判据的等价关系并不相同：一条没有地址的记录
            # 能凭标题认出一条有地址的记录，但两者的计数键不一样。
            existing = staged.find(job)
            key = StagedIndex.key_for(job)
            already_seen = key in seen
            if existing is not None or already_seen:
                report.skipped += 1
                seen.add(key)
                if existing is not None:
                    # 同一条岗位的第二次取回：把上一次空着的字段补上（详情页带来的正文）。
                    self._fill_blank(report, existing, job)
                elif already_seen:
                    # 这条岗位上一页已经命中过库，所以没有进 staged；当前页可能是它的详情页，
                    # 仍要把正文补回既有候选。
                    self._fill_known_candidate(session, report, job)
                continue
            seen.add(key)
            # 计数在这里 +1：**只要这一轮没见过它就算抓到了**，不管它是否已在库里。
            report.collected += 1
            if job.url:
                report.collected_urls.add(job.url)

            known = self._already_known(session, job)
            known_candidate = (
                find_staged_candidate(
                    session, title=job.title, company=job.company, source_url=job.url
                )
                if known
                else None
            )
            snapshot = {
                "candidate_id": known_candidate.id if known_candidate is not None else None,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "source_url": job.url,
                "job_id": None,
            }
            report.collected_jobs.append(snapshot)
            if known:
                report.skipped += 1
                if known == "trashed":
                    report.skipped_trashed += 1
                else:
                    # 旧候选不在本轮 detail_missing 账上，回填时不能改动本轮缺正文计数。
                    self._fill_known_candidate(session, report, job)
                continue

            candidate = stage_candidate_job(
                session,
                title=job.title,
                company=job.company,
                location=job.location,
                salary=job.salary,
                source_url=job.url,
                description=job.description,
                requirements=job.requirements,
                source=RECOGNITION_SOURCE_OFFICIAL,
                task_id=task_id,
                job_type=job.job_type,
            )
            staged.add(job, candidate)
            snapshot["candidate_id"] = candidate.id
            report.stored += 1
            # 与既有采集链路同一个口径：**正文为空才计数**，缺它不算漂移。
            if not job.description.strip():
                report.detail_missing += 1

    @staticmethod
    def _fill_blank(
        report: OfficialCollectReport,
        existing: Any,
        job: FeedJob,
        *,
        adjust_detail_missing: bool = True,
    ) -> None:
        """把这次取回里、上一条记录**空着**的字段补上。

        **只补空，不覆盖**：同一个岗位被两次取回时，先到的那次往往是列表页（有条目名、没正文），
        后到的是详情页（有正文）。覆盖会把已经拿到的内容换成空的，而不补则等于白取了详情页。

        补上正文时 ``detail_missing`` 要减回去——它在列表页那一次被记过一笔，不退的话报告里
        会一直说"有 N 条没有正文"，而它们其实已经有了。

        **参数里没有 ``session``**：它只改内存里的记录对象，落库由调用方负责。原先收一个却
        从不用（第一句就是 ``del session``），于是页面正文那条路要调用它时只能编一个 ``None``
        塞进来——一个没人用的参数会逼出这种假参数。
        """
        # ``posted_at`` 也在内：列表页与详情页谁先到不确定，能补就补。
        fillable = ("location", "salary", "description", "requirements", "job_type", "posted_at")
        filled_description = False
        for name in fillable:
            if not hasattr(existing, name):
                continue
            incoming = str(getattr(job, name, "") or "").strip()
            if not incoming or str(getattr(existing, name, "") or "").strip():
                continue
            setattr(existing, name, incoming)
            filled_description = filled_description or name == "description"
        if filled_description and adjust_detail_missing and report.detail_missing > 0:
            report.detail_missing -= 1

    @staticmethod
    def _fill_known_candidate(
        session: Session, report: OfficialCollectReport, job: FeedJob
    ) -> None:
        """补齐上一轮已存在的候选，但不改本轮新增候选的缺正文账目。"""
        candidate = find_staged_candidate(
            session, title=job.title, company=job.company, source_url=job.url
        )
        if candidate is None:
            return
        OfficialCollector._fill_blank(
            report, candidate, job, adjust_detail_missing=False
        )

    @staticmethod
    def _fill_page_body(
        report: OfficialCollectReport,
        page_url: str,
        page: FeedPage,
        staged: StagedIndex,
        session: Session,
    ) -> None:
        """把**这一页自身**的正文补到"地址就是这一页"的那条岗位上。

        详情页取回来时，适配器读到的是页面上的链接（往往是侧栏的「相关职位」），而这一页真正
        的内容——职位描述——不属于其中任何一条。所以它单独走这一条路：按地址找到那条岗位，
        把空着的正文补上。

        **只补空、不新建记录**。这一条是刻意的：造一条新记录意味着给它编一个标题，而标题是
        去重身份的一部分——编错就是给用户的备选岗位塞一行重复。按地址回填则只可能命中已有记录，
        找不到就什么也不做（那一页不是任何岗位的页，比如列表页、招聘栏目页）。

        **两条来路都要找**：本轮新落的（``staged``）与**上一轮就已经在库里的**。只认前者的话，
        这个功能就只在"第一次采这家公司"时有用——而重新采一家早就采过的公司恰恰是最常见的用法
        （第一次往往没配好、采了一半、或者当时还没有这一级），那时用户会看到"采是采了，
        正文一条都没有"，而每一页的正文其实都已经取回来了。
        """
        if not (page.body or page.body_requirements):
            return
        record = staged.find_by_url(page_url)
        if record is None:
            record = _staged_record_by_url(session, page_url)
        if record is None:
            return
        # 复用 ``_fill_blank``——它是全项目唯一一处"补齐空字段 + 把 detail_missing 退回去"的实现，
        # 另写一份必然与它漂移（那个退回逻辑漏掉的话，报告会一直说"有 N 条没有正文"）。
        #
        # 这里合成的 ``FeedJob`` 只当**字段袋**：``title`` 与 ``url`` 刻意留空——``_fill_blank``
        # 从不读它们（它只按字段名取那六个可补字段）。它也**只喂给 ``_fill_blank``，绝不进
        # ``_ingest`` 的循环**：在那边它的空标题会被当成一条新岗位，凭空多记一笔 skipped
        # 甚至多落一条没有标题的候选。
        OfficialCollector._fill_blank(
            report,
            record,
            FeedJob(title="", description=page.body, requirements=page.body_requirements),
        )

    @staticmethod
    def _already_known(session: Session, job: FeedJob) -> str:
        """这个岗位是否已经有"正式岗位"或"待处理的候选"，以及**在不在回收站里**。

        返回 ``""``（没采过）/ ``"existing"``（库里已有）/ ``"trashed"``（在回收站里）。

        **两张表都要查**，少查一边都会出问题：只查岗位广场，暂存区里会堆出同一岗位的多条
        候选（用户勾一次就重复导入一次）；只查暂存区，则会把已经在岗位广场里的岗位重新捞回来。
        去重判据走 ``find_by_job_identity``——**与候选导入是同一份实现**，且刻意不过滤软删除
        （正因如此才能顺便看出它是被删过的）。

        区分"在回收站里"是因为两种跳过对用户的含义完全不同：一种是"早就在库里了"，另一种是
        "你之前删过它"——后者不说清楚，用户会以为删除没生效。
        """
        identity = {"title": job.title, "company": job.company, "source_url": job.url}
        found = find_job_by_identity(session, **identity) or find_staged_candidate(
            session, **identity
        )
        if found is None:
            return ""
        return "trashed" if trash.is_deleted(found) else "existing"


__all__ = [
    "MAX_COLLECT_PAGES",
    "MAX_FETCH_DEPTH",
    "CollectCancelled",
    "OfficialCollectReport",
    "OfficialCollector",
    "OfficialSiteLike",
    "StagedIndex",
]
