"""站点健康度：把"采集悄悄抓不到东西"的静默失败变成用户看得见的告警。

招聘网站改版时，采集会开始"悄悄抓不到东西"——任务可能仍然显示"采集完成"，用户却拿不到有用
的岗位，只会以为自己不会用。这个模块从**最近几次该站点的采集记录**里识别这种漂移，给出
``degraded``（疑似改版）标记与可操作的中文原因。

拆成"纯判断 + 读库"两块：

- ``evaluate_site_health``：只吃"摘要列表"，方便离线穷举各种组合（哪种失败算、哪种不算）；
- ``recent_collect_summaries`` / ``site_health_overview``：负责取最近 N 次任务、映射成摘要。

判据的关键是**区分两类问题**（混在一起会天天误报，用户很快就忽略这个标记）：

- **算作"站点可能改版"**：``selector_invalid``（页面结构变化 / 选择器失效）；以及**采集正常
  结束、但详情普遍为空**（补到详情缺失的比例超过一半）——后者正是"能采到列表却抓不到 JD"。
- **明确不算**：需要登录、需要验证码 / 安全验证、网络超时、以及"真的没搜到结果"。这些是
  **环境或用户侧**问题，把它们算成"站点改版"只会制造噪声。
- **样本不足时不报警**：宁可不报，也不要制造噪声。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ..models.apply import (
    FAILURE_SELECTOR_INVALID,
    TASK_KIND_COLLECT,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    ApplyTask,
)
from ..schemas.apply import CollectRunSummaryOut, SiteHealthOut
from .sites.registry import get_registry

# ===== 阈值（具名常量 + 理由）=====

# 只看最近这么多次采集。取 5 是因为：单次失败可能只是网络抖动，看"最近几次"才有趋势意义；
# 而样本太多会让"上周改版、这周已经修好"的旧证据长期压着标记不放，用户会以为一直没好。
RECENT_COLLECT_WINDOW = 5

# 少于这么多次就不报警。**这是唯一的噪声闸门**：只有 1 次记录时无法判断是偶发还是趋势，
# 宁可不报，也不能让用户因为一次偶发失败就看到"站点可能改版"。
MIN_SAMPLES_FOR_DEGRADED = 2

# "采集正常结束、但详情普遍为空"的判据：详情缺失比例**超过**这个值才算漂移。
# 单条详情偶发抓不到是正常的（岗位下线 / 页面加载慢），**过半**才说明是系统性读不到详情。
DETAIL_MISSING_RATIO_THRESHOLD = 0.5

# 只有"得出结论"的采集才纳入健康度：``completed``（正常结束）与 ``failed``（失败）。
# 用户主动停止（``stopped``）或尚未结束（``pending``/``running``/``paused``）的任务只反映
# 用户行为与中间态，纳入会把"用户提前停掉、只处理了 1 条且详情为空"误判成站点漂移。
HEALTH_SAMPLE_STATUSES = (TASK_STATUS_COMPLETED, TASK_STATUS_FAILED)

# 站点归属靠 ``task.config['site_key']`` 过滤，用 Python 侧判断而非 SQL 的 JSON 路径：
# 本地单用户数据量很小，这样跨数据库方言都可移植，也避免 JSON 路径查询的兼容坑。
# 为覆盖"中间夹着一堆别站点任务"的情况，先按时间取一段再过滤。
_RECENT_SCAN_LIMIT = 200

STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"


@dataclass(frozen=True)
class SiteHealth:
    """纯判断的结论：状态 + 可操作原因 + 统计明细。"""

    status: str = STATUS_OK
    reasons: list[str] = field(default_factory=list)
    sampled: int = 0
    selector_failures: int = 0
    detail_drift_runs: int = 0


def _as_int(value: Any) -> int:
    """把可能来自 JSON / 历史数据的值宽松地归一成 int；坏了当作 0，绝不让它抛异常。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _as_dict(value: Any) -> dict[str, Any]:
    """把可能来自 JSON / 历史数据的值归一成 dict；脏值当作空 dict，绝不让它抛异常。

    ``task.config`` 是 JSON 列、**没有类型约束**：历史数据或外部写坏时可能是列表 / 字符串 /
    数字。若直接 ``config.get(...)`` 会抛 ``AttributeError``，把"看不见漂移"升级成整个接口 500。
    脏值当空 dict 处理，等于"读不出站点归属"——该行自然被跳过，其余记录照常统计。
    """
    return value if isinstance(value, dict) else {}


def _detail_is_mostly_missing(succeeded: int, missing: int) -> bool:
    """详情缺失是否"普遍"：比例严格**超过**阈值才为真（恰好等于不算，避免边界误报）。"""
    if succeeded <= 0:
        return False
    return missing > succeeded * DETAIL_MISSING_RATIO_THRESHOLD


def evaluate_site_health(recent_tasks: list[dict[str, Any]]) -> SiteHealth:
    """从最近若干次采集摘要判断站点健康度（**纯函数**，只依赖入参）。

    每条摘要至少含 ``status`` / ``failure_category`` / ``succeeded`` / ``detail_missing``。
    返回 ``ok`` 或 ``degraded``，并附带人类可读的中文原因与统计明细。
    """
    samples = [sample for sample in recent_tasks if isinstance(sample, dict)]
    samples = samples[:RECENT_COLLECT_WINDOW]
    sampled = len(samples)

    selector_failures = 0
    detail_drift_runs = 0
    for sample in samples:
        # 结构失败（选择器失效）：这是"站点改版"最直接的证据，无需再看别的字段。
        if _as_text(sample.get("failure_category")) == FAILURE_SELECTOR_INVALID:
            selector_failures += 1
            continue
        # 详情漂移：只有"正常结束"的采集才算，避免把用户中途停止的残缺统计算进来。
        if _as_text(sample.get("status")) != TASK_STATUS_COMPLETED:
            continue
        if _detail_is_mostly_missing(_as_int(sample.get("succeeded")), _as_int(sample.get("detail_missing"))):
            detail_drift_runs += 1

    # 样本不足：结论不可靠，宁可不报。
    if sampled < MIN_SAMPLES_FOR_DEGRADED:
        return SiteHealth(
            status=STATUS_OK,
            reasons=[],
            sampled=sampled,
            selector_failures=selector_failures,
            detail_drift_runs=detail_drift_runs,
        )

    reasons: list[str] = []
    if selector_failures:
        reasons.append(
            f"最近 {sampled} 次采集里有 {selector_failures} 次读不出岗位页面"
            "（页面结构变化 / 选择器失效），站点可能改版了——先重试一次；"
            "如果一直这样，请到项目仓库反馈并附上「采集记录」里的这次批次。"
        )
    if detail_drift_runs:
        reasons.append(
            f"最近 {sampled} 次采集里有 {detail_drift_runs} 次能采到岗位列表、却读不出职位详情"
            "（JD 为空），站点可能改版了——先重试一次；"
            "如果一直这样，请到项目仓库反馈并附上「采集记录」里的这次批次。"
        )

    status = STATUS_DEGRADED if reasons else STATUS_OK
    return SiteHealth(
        status=status,
        reasons=reasons,
        sampled=sampled,
        selector_failures=selector_failures,
        detail_drift_runs=detail_drift_runs,
    )


def _summary_of(task: ApplyTask) -> dict[str, Any]:
    """把一条采集任务映射成纯函数需要的摘要（读不到的值一律归零 / 空串）。"""
    config = _as_dict(task.config)
    return {
        "status": _as_text(task.status),
        "failure_category": _as_text(config.get("failure_category")),
        "succeeded": _as_int(task.succeeded),
        "detail_missing": _as_int(config.get("detail_missing")),
        "created_at": task.created_at.isoformat() if task.created_at else "",
    }


def recent_collect_summaries(
    db: Session, site_key: str, *, limit: int = RECENT_COLLECT_WINDOW
) -> list[dict[str, Any]]:
    """取某站点最近 ``limit`` 次**已得出结论**的采集摘要（按时间倒序）。

    哪些算"该站点的采集"：
    - ``task.config['site_key']`` 必须等于 ``site_key``（由 ``task_runner`` 写入；旧任务没有
      这个键，天然被排除，不会被误算到任何站点）；
    - 排除「补齐详情」任务（``config`` 带 ``backfill_job_ids``）：它是用户点名的一次性修补，
      账目（``backfilled`` / ``backfill_skipped``）与正常采集不同，混进健康度会搅乱判据。
    """
    rows = (
        db.query(ApplyTask)
        .filter(ApplyTask.kind == TASK_KIND_COLLECT)
        .filter(ApplyTask.status.in_(HEALTH_SAMPLE_STATUSES))
        .order_by(ApplyTask.id.desc())
        .limit(_RECENT_SCAN_LIMIT)
        .all()
    )
    summaries: list[dict[str, Any]] = []
    for task in rows:
        config = _as_dict(task.config)
        if _as_text(config.get("site_key")) != site_key:
            continue
        if "backfill_job_ids" in config:
            continue
        summaries.append(_summary_of(task))
        if len(summaries) >= limit:
            break
    return summaries


def site_health_overview(db: Session, *, registry: Any = None) -> list[SiteHealthOut]:
    """每个已注册站点的健康度（供 API 直接返回）。

    站点清单来自注册表，与「当前招聘网站」用的是同一份，前端无需写死站点名。
    """
    reg = registry or get_registry()
    overview: list[SiteHealthOut] = []
    for adapter in reg.all():
        summaries = recent_collect_summaries(db, adapter.key)
        health = evaluate_site_health(summaries)
        overview.append(
            SiteHealthOut(
                site_key=adapter.key,
                display_name=adapter.display_name,
                status=health.status,
                reasons=list(health.reasons),
                sampled=health.sampled,
                selector_failures=health.selector_failures,
                detail_drift_runs=health.detail_drift_runs,
                recent=[CollectRunSummaryOut(**summary) for summary in summaries],
            )
        )
    return overview


__all__ = [
    "DETAIL_MISSING_RATIO_THRESHOLD",
    "HEALTH_SAMPLE_STATUSES",
    "MIN_SAMPLES_FOR_DEGRADED",
    "RECENT_COLLECT_WINDOW",
    "STATUS_DEGRADED",
    "STATUS_OK",
    "SiteHealth",
    "evaluate_site_health",
    "recent_collect_summaries",
    "site_health_overview",
]
