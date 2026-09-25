"""官网采集接口的请求与响应模型。

**只描述形状，不做业务判断**：能不能采集、结论是什么，都由服务层定好之后填进来。
接口层再算一遍是"前后端阈值漂移"的起点——本项目在投递准入上已经吃过一次，那里靠
``admission_of`` 单源收口，这里同理。

标签字段（``*_label``）与枚举值一起返回，前端直接用中文渲染，不自己维护一份映射表。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class OfficialSiteCreate(BaseModel):
    company: str = Field(default="", max_length=128)
    homepage_url: str = Field(default="", max_length=512)
    careers_url: str = Field(default="", max_length=512)


class OfficialSiteUpdate(OfficialSiteCreate):
    """修改已保存的公司源；保存后由接口重新探测招聘系统。"""


class CollectRequest(BaseModel):
    """开始一次采集时的可选参数。**整个请求体都是可选的**（不带体 = 按默认来）。

    ``max_jobs`` 是**这一次**的条数上限：岗位上万条的站点一次翻不完，而用户多半只想先看前
    几十条。上限落在服务端、随这次运行走，不存进站点——它回答的是"这回我只要看这么多"。
    """

    # 上限给一个天花板：它就是防手滑的（多打一个零变成抓十万条，界面会显示成"要跑几小时"，
    # 但那时已经点下去了）。真正的规模上限仍是采集器自己那个页数纪律。
    max_jobs: int | None = Field(default=None, ge=1, le=2000)
    # 这次临时筛选的岗位关键词；不写回公司配置。多个关键词可用顿号、逗号、分号或换行分隔。
    job_keywords: str | None = Field(default=None, max_length=200)


class OfficialSiteOut(BaseModel):
    id: int
    company: str
    homepage_url: str
    careers_url: str
    # 识别结果。
    source_kind: str
    # 系统展示名；未识别时为空串（前端据此显示"未识别"而不是显示一个内部标识）。
    source_label: str = ""
    endpoint: str = ""
    confidence: str = ""
    confidence_label: str = ""
    probe_evidence: str = ""
    # robots 结论。``None`` 表示还没查过。
    robots_allowed: bool | None = None
    robots_detail: str = ""
    crawl_delay_seconds: float | None = None
    min_interval_seconds: int = 0
    enabled: bool = True
    last_probed_at: datetime | None = None
    created_at: datetime
    # 列表页要显示的东西，由服务层算好。
    latest_verdict: str = ""
    latest_verdict_label: str = ""
    latest_headline: str = ""
    # 最近一次运行的**状态**。列表页要靠它显示"采集中"——只看 ``latest_verdict`` 是不够的：
    # 采集进行中时结论还是空的，界面会显示成"还没采过"，而用户明明刚点了开始。
    latest_run_id: int | None = None
    latest_status: str = ""
    latest_status_label: str = ""
    # 现在能不能采集：已识别出系统 **且** robots 允许。前端据此禁用按钮，
    # 但服务端在真正执行时仍会自己复核一遍，不信任前端传入的状态。
    can_collect: bool = False


class OfficialRunOut(BaseModel):
    id: int
    site_id: int
    site_company: str = ""
    status: str
    status_label: str = ""
    # ===== 账目 =====
    pages: int = 0
    # 去重后的取回条数；对总数比的是它，不是 stored。
    collected: int = 0
    stored: int = 0
    skipped: int = 0
    detail_missing: int = 0
    total_hint: int | None = None
    # ===== 对账结论 =====
    verdict: str = ""
    verdict_label: str = ""
    evidence: str = ""
    headline: str = ""
    missing: int = 0
    blocks: list[str] = Field(default_factory=list)
    block_labels: list[str] = Field(default_factory=list)
    started_at: datetime
    finished_at: datetime | None = None
    error: str = ""
    # 这次采集花掉的模型调用次数。**用户自付 key，这一项必须可见**——否则他只能去翻服务商的
    # 账单才知道这个功能用了他多少钱。
    llm_calls: int = 0


class OfficialTrendOut(BaseModel):
    """这次采集与这家公司近期基线的偏离。

    **它不是一条对账依据**，而是一个独立提醒：条数下降既可能是我们漏抓，也可能是这家公司真的
    关掉了那些岗位，只看条数是分不出来的。所以 ``detail`` 里要把这句话说清楚。
    """

    state: str
    label: str
    detail: str
    # 基线（历史中位数）与本次条数；历史不足时 baseline 为 null。
    baseline: int | None = None
    latest: int = 0


class OfficialExtractionOut(BaseModel):
    """这次采集**每一页是怎么读出来的**。

    它不是对账依据，而是花销与可复现性的说明：用户能看到哪几页动了模型、配方有没有归纳成功、
    下次还需不需要再花钱。``methods`` 是逐页的句子，由服务层写好，界面原样展示。
    """

    methods: list[str] = Field(default_factory=list)
    llm_calls: int = 0
    # 本次归纳并成功存下的配方数。存下来之后，同一站点的后续采集不再需要模型。
    recipes_learned: int = 0
    # 因为超过层级上限而没有跟进的地址数。**它不改变结论**（站点的次级导航不是岗位），
    # 但报告里要能回答"为什么这次只翻了这么几页"。
    deep_links_skipped: int = 0


class OfficialRunDetailOut(OfficialRunOut):
    """报告页用：带上逐层依据与趋势提醒。

    与列表分开，是因为明细里可能有很多层，列表页不需要它们。
    """

    reconcile_detail: dict[str, Any] = Field(default_factory=dict)
    trend: OfficialTrendOut | None = None
    extraction: OfficialExtractionOut = Field(default_factory=OfficialExtractionOut)


class OfficialProbeOut(BaseModel):
    """一次探测的结果。

    ``state`` 是三态（命中 / 未识别 / 被阻断），**不是布尔**：把"被阻断"混进"未识别"会让
    用户以为这家公司不用这套系统，而实际上我们只是没看到内容。
    """

    state: str
    state_label: str = ""
    site: OfficialSiteOut
    job_count: int = 0
    evidence: str = ""
    # 试过哪些端点、各自什么结果。探测失败时这是用户唯一能拿去反馈的东西。
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    # 注意"没试完"这件事是写在 ``evidence`` 里的（``probe.py`` 会把它挂到结论上），
    # 不再单独开一个字段：**同一句话只该有一处**，而 ``evidence`` 还会落进源的「判断依据」
    # 里长期展示——那里也必须看得到。



