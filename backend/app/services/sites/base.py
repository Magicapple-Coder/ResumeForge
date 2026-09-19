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
    page: int = 1


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
    "ApplyOutcome",
    "CollectQuery",
    "RiskProfile",
    "SearchPage",
    "SearchResult",
    "SiteAdapter",
    "SiteFailure",
]
