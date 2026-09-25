"""官网采集的领域常量。

放在 ``models/`` 而不是服务层，理由与 ``models/apply.py`` 的失败分类相同：这些取值会**落库**
（写进采集记录）并**展示给用户**，读写两端必须共用同一份字面量。各写一份的结果是"库里存的是
一个值、界面上比对的是另一个值"，而且这种漂移不会报错，只会让某类阻断静默地从报告里消失。

本模块**不含站点知识**：哪家公司在用哪套招聘系统属于适配器层（``services/sites/official/feeds``），
这里只描述"一次取回的结果可以被归成哪几类"。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .profile import utcnow

# ===== 取回结果的分类（official_collect_run 的 block 列 / 对账报告的输入）=====

# 没有发生阻断：请求成功（**不管是拿到了岗位还是拿到了空列表**）。
BLOCK_NONE = ""

# 站点限流（HTTP 429、或无状态码但响应体明示频率限制）。
BLOCK_RATE_LIMIT = "rate_limit"

# 拒绝访问：HTTP 403、robots.txt 明确 disallow、或 WAF 拦截页。
BLOCK_FORBIDDEN = "forbidden"

# 人机校验：验证码 / 滑块 / "请稍后再试"的安全验证页。
# **不尝试绕过**——检出后如实上报并交还用户处理，与投递链路既有决策一致。
BLOCK_CAPTCHA = "captcha"

# 登录墙：内容需要登录态才可见，而当前会话没有。
BLOCK_LOGIN = "login"

# 软封禁：HTTP 200，但页面是个空壳（无内容、无挂载数据），或接口返回了异常结构。
# **这是最危险的一类**：状态码看起来是成功的，不专门识别就会把"被拦了"读成"这里没有岗位"。
BLOCK_SOFT = "soft_block"

BLOCK_TIMEOUT = "timeout"

# 连接层失败：DNS 解析不了、TLS 握手失败、连接被重置。
BLOCK_NETWORK = "network"

# 端点不存在（HTTP 404）。**它不属于"被阻断"**：对探测而言这是一个干净的否定答案
#（"这家公司不是用这套系统"），但出现在**翻页途中**时语义是模糊的——可能是"没有下一页了"，
# 也可能是"接口改了"，因此终止判定对它单独处理，不当作"抓到底了"的证据。
BLOCK_NOT_FOUND = "not_found"

BLOCK_UNKNOWN = "unknown"

BLOCK_LABELS = {
    BLOCK_NONE: "正常",
    BLOCK_RATE_LIMIT: "站点限流",
    BLOCK_FORBIDDEN: "拒绝访问",
    BLOCK_CAPTCHA: "需要人机校验",
    BLOCK_LOGIN: "需要登录",
    BLOCK_SOFT: "疑似软封禁（返回空壳页）",
    BLOCK_TIMEOUT: "网络超时",
    BLOCK_NETWORK: "连接失败",
    BLOCK_NOT_FOUND: "接口不存在",
    BLOCK_UNKNOWN: "未知异常",
}

# 「传输侧失败」：这些结果的含义是**我们并不知道那边有什么**，因此绝不能当作
# "已经抓到底了"。对账的终止判定（E 层）靠这个集合分流：
# 只有全部取回都是 BLOCK_NONE 时，"没有下一页"才是可信的结论。
TRANSPORT_FAILURES = frozenset(
    {
        BLOCK_RATE_LIMIT,
        BLOCK_FORBIDDEN,
        BLOCK_CAPTCHA,
        BLOCK_LOGIN,
        BLOCK_SOFT,
        BLOCK_TIMEOUT,
        BLOCK_NETWORK,
        BLOCK_UNKNOWN,
    }
)


def is_transport_failure(block: str) -> bool:
    """该取回结果是否属于"不知道那边有什么"（即不能用它下"抓完了"的结论）。"""
    return block in TRANSPORT_FAILURES


# ===== 对账结论（official_collect_run 的 reconcile_verdict 列）=====
#
# 只有三态，**不出百分比分数**：与「投递进度不显示百分比」「匹配度分析不显示百分比」
# 同一取向——百分比会给出虚假的精确感，而这三态各自都有可核对的依据。

# 已确认为全量：存在总数契约且账目相符，或存在可枚举全集且差集为空。
VERDICT_COMPLETE = "complete"

# 已确认不全：差多少条是明确的，且能给出差额明细。
VERDICT_INCOMPLETE = "incomplete"

# 无法确认：没有总数契约、或本次采集被阻断、或分页信号自相矛盾。
# **它不等于"抓全了"，也不等于"没抓全"**——如实说"不知道"是这一层的职责。
VERDICT_UNKNOWN = "unknown"

VERDICTS = (VERDICT_COMPLETE, VERDICT_INCOMPLETE, VERDICT_UNKNOWN)

VERDICT_LABELS = {
    VERDICT_COMPLETE: "已确认为全量",
    VERDICT_INCOMPLETE: "已确认不全",
    VERDICT_UNKNOWN: "无法确认",
}

# ===== 采集运行状态 =====
RUN_RUNNING = "running"
RUN_DONE = "done"
RUN_STOPPED = "stopped"
RUN_FAILED = "failed"
RUN_STATUSES = (RUN_RUNNING, RUN_DONE, RUN_STOPPED, RUN_FAILED)

RUN_STATUS_LABELS = {
    RUN_RUNNING: "采集中",
    RUN_DONE: "已完成",
    RUN_STOPPED: "已停止",
    RUN_FAILED: "失败",
}

# ===== 数据模型 =====


class OfficialSite(Base):
    """一个公司官网源：识别结果 + 采集所需的一切设定。

    探测**一次**、复用多次：``source_kind`` 与 ``endpoint`` 是探测的产物，之后每次采集直接
    按它走契约，不再重新猜。站点改版导致契约失效时，重新探测覆盖这几列即可。

    与岗位一样**不软删除**：它是配置类记录而非用户内容，删掉就是不再采集这家公司。它的采集
    历史随 ``ondelete="CASCADE"`` 一并清掉——留着孤立的运行记录既没有意义，也让"这份报告属
    于哪家公司"无法回答。
    """

    __tablename__ = "official_site"

    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str] = mapped_column(String(128), default="", server_default="")
    homepage_url: Mapped[str] = mapped_column(String(512), default="", server_default="")
    # 用户直接提供的招聘页地址（可能就是它让我们识别出了系统）。
    careers_url: Mapped[str] = mapped_column(String(512), default="", server_default="")
    # 识别出的招聘系统标识；空串 = 未识别出已知系统，走通用抽取路径。
    source_kind: Mapped[str] = mapped_column(String(64), default="", server_default="")
    endpoint: Mapped[str] = mapped_column(String(1024), default="", server_default="")
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    # 探测置信度与证据（直接展示给用户："为什么认为这家公司用的是这套系统"）。
    confidence: Mapped[str] = mapped_column(String(16), default="", server_default="")
    probe_evidence: Mapped[str] = mapped_column(String(500), default="", server_default="")
    # 通用路径的选择器配方（阶段 2）。带版本号：站点改版后换新版本，旧版本留痕以便对比。
    recipe: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    recipe_version: Mapped[str] = mapped_column(String(32), default="", server_default="")
    # robots 结论。**落库而不是每次重取**：用户有权在源列表上直接看到"这家站点允不允许采集"，
    # 而不是等到采集失败才知道。``None`` 表示还没查过。
    robots_allowed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    robots_detail: Mapped[str] = mapped_column(String(500), default="", server_default="")
    crawl_delay_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 限速画像：沿用写路径 ``RiskProfile`` 的形状（最小间隔 + 每小时上限）。
    min_interval_seconds: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    max_per_hour: Mapped[int] = mapped_column(Integer, default=120, server_default="120")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    last_probed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class OfficialCollectRun(Base):
    """一次采集的账目 + 对账结论。

    这张表的存在意义是**留下凭据**：对账报告不是当场算完就丢的中间量，用户几天后回看
    "上次那家公司抓到多少、为什么说没抓全"要能查到原文。
    """

    __tablename__ = "official_collect_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("official_site.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(16), default=RUN_RUNNING, server_default=RUN_RUNNING, index=True
    )
    # ===== 账目 =====
    pages: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # **去重后的取回条数**。对总数要跟它比，不是跟 ``stored``——已存在的岗位会被跳过，
    # 但它们确实被抓到了（见 ``reconcile`` 的模块说明）。
    collected: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    stored: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    skipped: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # 暂存了、但正文为空的条数：站点漂移唯一留下的痕迹，与既有采集链路同名同义。
    detail_missing: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_hint: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 每次取回的阻断分类，按发生顺序；供报告页逐条展开。
    blocks: Mapped[list[Any]] = mapped_column(JSON, default=list, server_default="[]")
    # ===== 对账结论 =====
    verdict: Mapped[str] = mapped_column(String(16), default="", server_default="")
    evidence: Mapped[str] = mapped_column(String(16), default="", server_default="")
    headline: Mapped[str] = mapped_column(String(500), default="", server_default="")
    missing: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # 逐层明细与终止状态的原文，报告页据此渲染，不再二次推导。
    reconcile_detail: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    # ===== 模型成本（用户自付 key，必须可查）=====
    llm_calls: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    llm_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str] = mapped_column(String(500), default="", server_default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OfficialDiscoverySearch(Base):
    """一次「按岗位找公司」搜索的可回看快照。

    **待删除（2026-09-25）**：这个功能已经移除（服务、接口、前端组件与测试都删了，见提交
    `6691a9e`），只剩这张表和这个模型类。**不要为它单独发一个迁移**——每加一次迁移，数据库的
    版本号就前进一次且不可逆（旧版本代码打开升级过的库会打不开）。下次**本来就要加迁移**时，
    把它并进那一次一起做，清单见 `AGENTS.md` 的「待办：下次加迁移时，顺手带上
    official_discovery_search」一节。

    搜索结果不是稳定的外部资源：搜索引擎排序、页面内容和过滤结果都会变化。因此历史记录
    同时保存查询条件与当时的候选快照，回看时不会因为重新搜索而悄悄换成另一批公司。
    """

    __tablename__ = "official_discovery_search"

    id: Mapped[int] = mapped_column(primary_key=True)
    keywords: Mapped[str] = mapped_column(String(200), default="", server_default="")
    city: Mapped[str] = mapped_column(String(64), default="", server_default="")
    queries: Mapped[list[Any]] = mapped_column(JSON, default=list, server_default="[]")
    candidates: Mapped[list[Any]] = mapped_column(JSON, default=list, server_default="[]")
    detail: Mapped[str] = mapped_column(String(500), default="", server_default="")
    candidate_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


__all__ = [
    "BLOCK_CAPTCHA",
    "BLOCK_FORBIDDEN",
    "BLOCK_LABELS",
    "BLOCK_LOGIN",
    "BLOCK_NETWORK",
    "BLOCK_NONE",
    "BLOCK_NOT_FOUND",
    "BLOCK_RATE_LIMIT",
    "BLOCK_SOFT",
    "BLOCK_TIMEOUT",
    "BLOCK_UNKNOWN",
    "RUN_DONE",
    "RUN_FAILED",
    "RUN_RUNNING",
    "RUN_STATUSES",
    "RUN_STATUS_LABELS",
    "RUN_STOPPED",
    "TRANSPORT_FAILURES",
    "OfficialCollectRun",
    "OfficialDiscoverySearch",
    "OfficialSite",
    "VERDICT_COMPLETE",
    "VERDICT_INCOMPLETE",
    "VERDICT_LABELS",
    "VERDICT_UNKNOWN",
    "VERDICTS",
    "is_transport_failure",
]
