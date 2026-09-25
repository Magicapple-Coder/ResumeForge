"""官网采集（读路径）的契约。

**为什么不复用 ``sites/base.py`` 的 ``SiteAdapter``**：那个契约是"驱动浏览器完成投递"，子类
必须实现 ``open_apply`` / ``fill_and_submit``。官网采集是纯读，且大部分走 HTTP 而非浏览器；
把两者塞进一个抽象，结果是每个采集适配器都要实现一个永远用不到的投递方法，或者基类里堆满
``NotImplementedError``。因此这里定义独立的 ``JobFeed``，两者**共享数据结构**（``CollectQuery``
/ ``RiskProfile``）但各自定义行为接口。

**为什么传输层做成注入的 ABC**：适配器拿到的是 ``FeedHttp`` 而不是 ``httpx.AsyncClient``，
于是它**没有办法绕开 SSRF 防护**——那只在 ``http.py`` 的唯一实现里。适配器也因此在测试里
完全离线（注入假传输即可），不必真连网。

失败一律**收敛成返回值**而不是抛异常：``FetchResult.block`` 与 ``FeedPage.block`` 就是失败
本身，而且它是对账的输入。抛异常会让调用方在 ``except`` 里丢掉分类，把"被限流"和"网络抖动"
糊成一类——那正是对账最不能容忍的事。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ....models.official import BLOCK_NONE

# 通用网页的交互式翻页控制不会总有 href（React/Ant Design 分页器通常只响应 click）。
# 这些保留参数只在浏览器升级层解释，不能直接发给站点；集中定义避免 generic 与浏览器传输层
# 各写一份字符串后悄悄漂移。
BROWSER_ACTION_PARAM = "__resumeforge_browser_action"
BROWSER_PAGE_PARAM = "__resumeforge_browser_page"

# ===== 探测置信度 =====
#
# 界面要如实告诉用户"这条线索有多可信"。三档的差别是**证据来源**，不是程度：
# 用户直接给的招聘页地址里读出来的（高）> 从官网首页/站点地图里读出来的（中）
# > 由公司域名猜出来的（低，必须实际请求验证过才算命中）。

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

CONFIDENCE_LABELS = {
    CONFIDENCE_HIGH: "来自用户提供的招聘页地址",
    CONFIDENCE_MEDIUM: "来自官网首页线索",
    CONFIDENCE_LOW: "按公司域名推测",
}


@dataclass(frozen=True)
class ProbeContext:
    """探测的输入：一个公司的已知线索。

    ``homepage_html`` 由调用方**先行取回**后传进来，而不是让适配器自己去抓：取首页要走
    SSRF 防护与阻断分类，那两件事只该有一份实现；而且这样探测的推导部分是纯函数，能离线测。
    """

    company: str = ""
    # 归一化后的主域名（例如 ``acme.com``），不含 scheme 与路径。
    domain: str = ""
    homepage_url: str = ""
    # 用户直接给的招聘页地址；为空表示用户只给了公司名或官网。
    careers_url: str = ""
    # 官网首页 HTML（可能为空串，表示没取到或不需要）。
    homepage_html: str = ""


@dataclass(frozen=True)
class FeedTarget:
    """一次取回的目标。

    探测的产物与采集的输入是同一个东西——避免"探测结果"和"采集参数"两份结构互相转换时
    丢字段。

    ``depth`` 是"这份地址离入口有多远"。**由适配器在派发新目标时自增**，因为只有它知道
    自己的站点结构：接口型适配器永远停在 0（一个端点返回全部），而"列表页 → 详情页"型的
    适配器派发详情页时置为 1。编排层据此设上限，防止一个自身链接成环的站点把采集带进
    无限递归。
    """

    feed_key: str
    endpoint: str
    params: dict[str, str] = field(default_factory=dict)
    depth: int = 0
    # page=普通页面/详情页，pagination=列表页的下一页。通用网页路径需要这个内部标记，
    # 才能让页数上限只限制列表页而不会被几十个详情页挤占。
    target_kind: str = "page"


@dataclass(frozen=True)
class ProbeHit:
    """一次成功的探测：这家公司确实在用这套招聘系统。"""

    target: FeedTarget
    confidence: str = CONFIDENCE_MEDIUM
    # 面向用户的证据说明（"招聘页地址里含有 boards/xxx"），报告里直接展示。
    evidence: str = ""


@dataclass
class FeedJob:
    """一条规范化后的岗位。

    ``extra`` 沿用 ``sites/base.SearchResult.extra`` 的约定：接口多带出来、而 ``Job`` 模型
    暂无对应列的结构化字段放这里，**不在适配器层丢掉**。
    """

    title: str
    company: str = ""
    location: str = ""
    salary: str = ""
    url: str = ""
    description: str = ""
    requirements: str = ""
    job_type: str = ""
    # 发布时间的**原始文本**，保持语义不加工（与 ``Job.posted_at`` 的既有约定一致）；
    # 识别不出就留空，不用本地时间替代。
    posted_at: str = ""
    # 站点内的岗位标识，用于跨次采集识别"同一条岗位"，比 URL 更稳（URL 可能带跟踪参数）。
    external_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class FeedPage:
    """一次取回结果。

    两种爬取形状共用这一个结构，**靠 ``cursor`` 与 ``next_targets`` 区分**：

    - **接口型**（一个端点返回全部）：填 ``jobs``，翻页用 ``cursor``；
    - **列表页型**（列表页 → 一堆详情页）：列表页这次不带岗位，改用 ``next_targets`` 派发
      详情页的地址，详情页那几次再带 ``jobs``。

    合成一个结构而不是两套编排，是为了让去重、落库、限速、对账这四件事**只存在一份实现**。
    """

    jobs: list[FeedJob] = field(default_factory=list)
    # 接口给出的总数锚点。``None`` = 该站点没有这个契约，对账只能退到集合/列表对账。
    total_hint: int | None = None
    # 内容侧说"还有下一页"。**为 False 才是确认到底**，且仅当 block 为正常时可信。
    has_more: bool = False
    # 下一页游标（空串表示该站点用页码或没有游标）。不透明，由适配器自己解释。
    cursor: str = ""
    # 这一页指出的**下一步要取的地址**（列表页 → 详情页）。由编排层排队、去重、限深。
    next_targets: list[FeedTarget] = field(default_factory=list)
    # 本页**自己声称**的条数（列表页会写"共 N 个岗位"）。与 ``len(jobs)`` 不等即为漂移信号。
    # 只对**带岗位的那一次取回**有意义：派发地址的那一次没有条数可比。
    claimed_count: int | None = None
    block: str = BLOCK_NONE
    # 面向用户的诊断，阻断时写清楚"哪个地址、什么表现、下一步怎么办"。
    detail: str = ""
    status_code: int = 0
    # 取回的**原文**，交给上层做配方与模型兜底（那两级要拿到页面本身才能工作）。
    #
    # 只有声明了 ``supports_recipes`` 的适配器才填它：接口型适配器返回的是 JSON，对上层没有
    # 意义，填了只是白占内存。为空表示"这一页不适用于上层抽取"。
    raw: str = ""
    # **这一页自身**作为一条岗位时的正文与任职要求（见 ``generic/body.py``）。
    #
    # 它是**页面级**的、不是某一条 ``jobs`` 的：这一页的正文属于"地址等于这一页"的那条岗位，
    # 而"哪条岗位的地址等于这一页"只有编排层判得了（它手里才有本轮已落的记录）。所以这里
    # 只负责把页面自己说的东西交出去，归属由 ``OfficialCollector._fill_page_body`` 定。
    #
    # 只有通用路径会填：接口型适配器的正文来自 JSON 字段，本来就不缺。
    body: str = ""
    body_requirements: str = ""


class FeedHttp(ABC):
    """受限的取回层。**唯一实现里带 SSRF 防护**，适配器拿到的是本抽象。

    只暴露 ``request``：不给适配器 ``client`` 或裸 socket，就没有"绕过防护"这条路径可选。
    """

    @abstractmethod
    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        max_bytes: int | None = None,
    ) -> FetchResult:
        """发一次请求。**任何失败都返回带分类的 ``FetchResult``，不抛异常。**

        ``max_bytes`` 让适配器覆盖默认的响应体上限：不同接口的响应体量级差得很远（有的接口
        一次返回整个职位板，解压后能到几十 MB），而"多大算过大"只有适配器知道。传 ``None``
        用实现的默认值。
        """

    async def aclose(self) -> None:
        """释放底层连接；默认什么都不做（假传输没有可释放的东西）。

        有了它，调用方就能写 ``try/finally`` 而不必要求实现支持 ``async with``：
        ``HttpxFeedHttp`` 持有一个连接池（跨一次采集的多次请求复用），必须被关掉。
        """
        return None


@dataclass
class FetchResult:
    """一次取回的原始结果 + 分类。"""

    block: str = BLOCK_NONE
    status_code: int = 0
    text: str = ""
    detail: str = ""
    # 响应头（小写键）。只用于读 ``Retry-After`` 与 ``Content-Type``，不参与业务判定。
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.block == BLOCK_NONE

    def json(self) -> Any | None:
        """尽力解析 JSON；解析不了返回 ``None``（由调用方转成软封禁分类）。"""
        import json

        try:
            return json.loads(self.text)
        except (ValueError, TypeError):
            return None


class JobFeed(ABC):
    """一套招聘系统的采集适配器。

    子类只实现"这套系统特有的事"：怎么从线索推出端点、怎么把响应解析成 ``FeedJob``。
    翻页节奏、去重、限速、对账都在编排层，与本层无关。
    """

    # 系统标识，与 ``official_site.source_kind`` 落库值一致。
    key: str = ""
    display_name: str = ""
    # 该系统的接口主机。用于：探测时判断"这个地址是不是本系统"，以及测试夹具命名。
    hosts: tuple[str, ...] = ()
    # 该系统的招聘页主机（用户可能直接给这种地址）。
    board_hosts: tuple[str, ...] = ()
    # 该系统是否提供总数契约。**声明为 True 的适配器必须真的在 FeedPage 里填 total_hint**，
    # 否则对账会退化成"软结论"却对外宣称"硬结论"——这比不声明更糟。
    provides_total: bool = False

    # 用户给的地址**本身**是否足以证明这个源有效（哪怕一次读到 0 条岗位）。
    #
    # 接口型适配器为 ``True``：用户给的 ``boards.greenhouse.io/acme`` 本身就证明了这家公司
    # 在这套系统上，此时"0 个岗位"是真实答案（可能刚招满），不认它就等于把一个能用的源
    # 判成识别失败。
    #
    # 通用路径也为 ``True``（**只在用户直接给出招聘页地址时生效**，见 ``probe.py`` 里那条
    # ``confidence == CONFIDENCE_HIGH``）：用户说"这是它的招聘页"，而我们确实能取到这一页，
    # 那就是个可用的源——只是**这一级**没从里面读出岗位，而它后面还有配方与模型两级没试。
    # 判"未识别"等于把"我们没试"说成了"这里没有"。
    #
    # 这条判据曾经是 ``False``，理由是"认了它会让对账报出 0 条已确认为全量"。那个理由在通用
    # 路径上不成立：**通用路径不提供总数契约**，一条都没抓到时对账只会给「无法确认」
    # （见 ``test_an_empty_collection_never_claims_completeness``），而且它从不设
    # ``claimed_count``，"列表页条数对得上"那一支根本不会触发。代价则是硬伤——**岗位地址长得
    # 不像岗位页、又没有结构化数据的站点连采集按钮都点不动**，而那正是模型兜底唯一能救回来的
    # 一类页面。
    #
    # （有总数契约的适配器是另一回事：那里 ``total_hint == 0`` 时"0 条"确实是一条硬结论，
    # 因为接口本身就在回答"这个板子上有几条"。）
    empty_entry_is_conclusive: bool = False

    # 这一级有没有"翻页"这回事——具体说：站点会不会用明确的信号（游标 / has_more）
    # 告诉我们"还有下一页"。
    #
    # 接口型适配器为 ``True``（游标接续）。**通用路径为 ``False``**：它读的是网页，翻页靠的是
    # 页面里有没有可跟进的链接，站点从来没告诉过我们"这是第几页、还有没有下一页"。此时
    # "队列走空"只说明**我们已经跟进完所有认得出来的链接**，而报告里的「翻页终止」如果照抄
    # "已翻到列表最后一页"，用户会据此以为这个列表就是全部——那是我们并不知道的事。
    paginates: bool = True

    # 这一级读不出岗位时，是否值得让上层用**配方与模型**再试一次。
    #
    # 由通用路径声明：它读的是网页，而网页的结构千差万别，配方与模型正是为它准备的兜底。
    # 接口型适配器为 ``False``——它们读的是契约，读不出就是真读不出，上层拿到的原文是 JSON，
    # 再喂给配方只会得出"这页没有岗位"这种无用结论，还白占内存。
    supports_recipes: bool = False

    @abstractmethod
    def probe_candidates(self, ctx: ProbeContext) -> list[ProbeHit]:
        """从线索推导出**可能的**系统命中（含置信度与证据）。

        **纯函数，不发请求**：探测的推导与验证分开，前者能离线穷举测试，后者才连网。
        返回空列表 = 这套系统不可能匹配该线索。

        返回 ``ProbeHit`` 而不是裸 ``FeedTarget``：候选本身就是一个**待验证的假设**，
        而置信度与证据是假设自带的属性。验证通过后它就是真的命中——同一个类型，不用转换。
        """

    def probe_rejection_reason(
        self, ctx: ProbeContext, candidate: ProbeHit, page: FeedPage
    ) -> str:
        """Return a reason when a successful response does not belong to the context.

        Most feeds have an unambiguous endpoint, so a normal response is enough to accept the
        candidate. Feeds that guess a board identifier from a company domain may override this
        hook to reject a real but unrelated public board. It must not make network requests.
        """
        del ctx, candidate, page
        return ""

    @abstractmethod
    async def fetch_page(
        self, http: FeedHttp, target: FeedTarget, *, cursor: str = ""
    ) -> FeedPage:
        """取一页岗位。**失败收敛进 ``FeedPage.block``，不抛异常。**"""


__all__ = [
    "BROWSER_ACTION_PARAM",
    "BROWSER_PAGE_PARAM",
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
