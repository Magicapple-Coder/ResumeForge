"""站点适配器的抽象与公共数据结构。

分工：**通用表单理解引擎**（``services/apply/form_engine.py``）是站点无关的，负责
"看懂陌生表单"；**站点适配器**只负责"这个站点特有的事"——搜索列表采集、岗位详情抓取、
投递入口定位、招呼语输入、投递成功/失败判定、该站点的风控参数。

加一个站点 = 加一个类 + 注册一行，不动业务层。站点改版时只改该适配器的选择器常量。

失败一律用 ``SiteFailure`` 抛出，且携带**一等的失败分类**与**可操作诊断**——诊断会直接
展示给用户，用户再反馈给我们修，所以要写清楚（当前 URL / 页面标题 / 匹配控件数 / 期望）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..browser.cdp_client import CdpClient


class SiteFailure(Exception):
    """一次站点操作的失败：``category`` 是分类，``detail`` 是可直接展示的中文诊断。"""

    def __init__(
        self,
        category: str,
        detail: str,
        *,
        url: str = "",
        title: str = "",
    ) -> None:
        super().__init__(detail)
        self.category = category
        self.detail = detail
        self.url = url
        self.title = title


# 筛选项清单的来源标记。**定义在站点无关的基类里**，因为"这份清单可信度如何"是通用的概念，
# 而业务层（投递台服务）要拿它判断"要不要提示用户只是公共清单"，不该为此认识某一个站点模块。
SOURCE_SESSION = "session"
SOURCE_PUBLIC = "public"
SOURCE_SNAPSHOT = "snapshot"
SOURCE_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class RiskProfile:
    """站点的风控参数：决定岗位之间的最小间隔与每小时上限。"""

    key: str
    min_interval_seconds: int = 25
    max_per_hour: int = 60
    needs_login: bool = True
    notes: str = ""


@dataclass
class CollectQuery:
    """一次采集的条件。首期确定生效的是关键词 + 城市 + 翻页。"""

    keywords: list[str] = field(default_factory=list)
    city: str = ""
    salary_min: int | None = None
    experience: str = ""
    education: str = ""
    # 岗位类型（校招/实习/社招）；空串 = 不限。能映射到站点官方参数的（BOSS：实习/社招）
    # 由适配器放进搜索 URL 做站点侧过滤；没有官方参数的（校招）+ 所有类型的兜底判定走
    # 采集后本地筛选（``collect_filters``，按接口返回的岗位类型编码判定）。采集器无论哪条
    # 路都会把它随结果入库标注。
    job_type: str = ""
    # **站点侧筛选项**：``{站点参数名: 编码}``，由适配器在采集开始前解析并校验好
    # （见 ``SiteAdapter.prepare_collect_filters``）。适配器不认识这里的键名——它只负责把
    # 它们拼进搜索 URL。**编码必须是当次校验过的**：站点改版后旧编码照样"合法"，
    # 发出去会静默筛错，那比不筛更糟。
    filters: dict[str, str] = field(default_factory=dict)
    page: int = 1


@dataclass
class FilterResolution:
    """站点侧筛选的解析结果：真正生效的参数，以及**没能执行**的那几项。

    ``unapplied`` 不为空时必须展示给用户——它意味着"你选了这个条件，但它这次没生效"。
    静默丢掉是最坏的：用户以为筛过了，拿到的是没筛的结果。
    """

    params: dict[str, str] = field(default_factory=dict)
    # 人话写法的"已生效"清单（如 ``["学历要求：本科"]``），直接给界面用。
    applied: list[str] = field(default_factory=list)
    # 没能生效的条件名（如 ``["公司规模"]``）。
    unapplied: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "params": dict(self.params),
            "applied": list(self.applied),
            "unapplied": list(self.unapplied),
        }


@dataclass
class SearchResult:
    title: str
    company: str = ""
    location: str = ""
    salary: str = ""
    url: str = ""
    source: str = ""
    # 适配器多带出来的结构化字段（经验 / 学历 / 技能标签 / HR 活跃时间…）。接口这条路
    # 才读得到，DOM 里没有。**当前 `Job` 模型没有对应的列，所以采集器还不消费它**——
    # 放这里是为了"接口给到的信息不在适配器层丢掉"，而不是假装已经有下游在用。
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchPage:
    results: list[SearchResult] = field(default_factory=list)
    page: int = 1
    has_next: bool = False
    # 采集条件里无法映射到站点查询参数的部分（薪资/经验/学历…），由界面显示「未生效」。
    unmapped_conditions: list[str] = field(default_factory=list)


@dataclass
class ApplyOutcome:
    """一次投递的成功结果；失败请抛 ``SiteFailure``。"""

    success: bool
    greeting_sent: str = ""
    detail: str = ""


class SiteAdapter(ABC):
    """站点适配器基类。子类只需实现站点特有的那些步骤。"""

    # 站点标识（用于注册表与 job.source 的匹配）。
    key: str = ""
    display_name: str = ""
    # 站点主机名（用于从 URL 反查适配器）。
    hosts: tuple[str, ...] = ()
    # 入口地址：启动投递专用浏览器时先打开这一页，用户才有一个能扫码登录的落脚点。
    # 不填的话窗口只会停在 about:blank，用户既不知道该去哪也无从登录。
    entry_url: str = ""
    # 能力声明：并非每个站点都同时支持"采集"与"自动投递"（例如只读的聚合站只能采集）。
    # 界面据此如实标注，避免用户对着一个不支持的能力反复尝试。默认两者都支持。
    supports_collect: bool = True
    supports_apply: bool = True
    # 是否必须先生成/选择一份岗位版简历才能投递。纯在线沟通型站点可声明为 False。
    requires_resume: bool = True
    # 这些采集条件**不映射到查询参数**，而是采集后按**接口返回的岗位字段**本地筛选
    # （见 ``services/apply/collect_filters.py``）。
    #
    # 由适配器声明，是因为"能不能筛"取决于该站点的列表接口是否返回这些字段——BOSS 的
    # `jobDegree` / `jobExperience` / 薪资数字都来自列表接口，所以它能筛。声明了却拿不到
    # 字段时，采集器会把条件如实计入"未能判断"，**不会假装筛过了**；完全不声明的适配器
    # 则继续走 `unmapped_conditions` 那条"未生效"的如实汇报。
    post_filter_conditions: tuple[str, ...] = ()

    # "保存抓到的站点原文"要保存哪些接口。由适配器声明一组 ``(标签, 路径片段...)``
    # （例如 ``("search", ("joblist",))``），标签用于样例文件名。**站点知识只属于适配器层**：
    # 录制装饰器本身不认识任何站点，它拿到的就是这里声明的东西。默认空 = 该站点不支持保存原文
    # （装饰器不会安装，一个文件都不写）。
    sample_markers: tuple[tuple[str, tuple[str, ...]], ...] = ()

    # ===== 站点侧筛选项（可选能力）=====
    #
    # 与 ``post_filter_conditions``（"采完之后按岗位字段本地筛"）是两件事，**不要混**：
    # 那一条筛的是"我的条件 vs 岗位要求"（例如"我的学历是本科"），这一条是**站点自己的筛选栏**
    # （例如"岗位要求本科"），筛得更准、也不用翻那么多页。两者可以同时用。
    #
    # 默认不支持：对多数站点，返回空列表就是"该站点没有这个能力"，界面据此不显示筛选区。

    def fetch_filter_options(self, client: CdpClient | None = None) -> tuple[Any, ...]:
        """本站点筛选栏的可选项（供界面渲染下拉框）。

        ``client`` 是**可选的**：能给就给，站点可以借此读到"当前登录账号可见"的那份清单；
        给不了（浏览器没启动）要能退回匿名可得的公共清单，而不是直接失败。
        """
        return ()

    def prepare_collect_filters(
        self, selected: Mapping[str, str] | None, client: CdpClient | None = None
    ) -> FilterResolution:
        """把用户在界面上选的 ``{分组: 编码}`` 解析成可以拼进搜索 URL 的查询参数。

        **在采集开始前调用一次**（不是每次翻页调一次）：校验编码要读一次站点清单，
        逐页重复读没有意义。返回的 ``unapplied`` 必须如实上报给用户。
        """
        return FilterResolution()

    def matches(self, url_or_source: str) -> bool:
        """给定的 URL 或来源文本是否属于本站点。"""
        target = (url_or_source or "").casefold()
        if not target:
            return False
        if self.display_name and self.display_name.casefold() in target:
            return True
        return any(host and host.casefold() in target for host in self.hosts)

    @abstractmethod
    def risk_profile(self) -> RiskProfile:
        """本站点的风控参数。"""

    @abstractmethod
    def collect_search(
        self, client: CdpClient, query: CollectQuery, page: int
    ) -> SearchPage:
        """采集一页搜索结果。"""

    @abstractmethod
    def open_apply(self, client: CdpClient, job: Any) -> None:
        """打开某个岗位的投递页并确认投递入口就绪。"""

    @abstractmethod
    def fill_and_submit(
        self, client: CdpClient, data: dict[str, Any], greeting: str
    ) -> ApplyOutcome:
        """理解表单、填写、写入招呼语并提交，返回结果；失败抛 ``SiteFailure``。"""


__all__ = [
    "SOURCE_PUBLIC",
    "SOURCE_SESSION",
    "SOURCE_SNAPSHOT",
    "SOURCE_UNAVAILABLE",
    "ApplyOutcome",
    "CollectQuery",
    "FilterResolution",
    "RiskProfile",
    "SearchPage",
    "SearchResult",
    "SiteAdapter",
    "SiteFailure",
]
