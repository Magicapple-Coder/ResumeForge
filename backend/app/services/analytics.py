"""求职数据看板（R-14）的本地聚合，**不依赖 LLM，离线可用**。

口径的唯一来源是 ``models/tracker.py`` 的 ``STATUSES`` / ``STATUS_RANK`` /
``STATUS_LABELS``，这里不另写枚举：

- **投递总量** = 未软删除的 ``ApplicationTrack`` 行数。
- **有效投递数** = 投递总量减去「待确认」（``unknown``）——待确认尚未核实为真实投递，
  不进入转化率分母；「已结束」（``rejected``）仍是真实投递，计入分母。
- **面试数** = 阶段达到「面试」及以上的行数（``interview`` / ``offer``）。
- **面试率** = 面试数 / 有效投递数；**Offer 率** = Offer 数 / 有效投递数（同一分母）。
- **测评笔试数** = 阶段达到「测评/笔试」及以上的行数（``assessment`` / ``interview`` /
  ``offer``）。
- **测评笔试→面试转化数** = 面试数；**笔试通过率** = 面试数 / 测评笔试数。
- **Offer 数** = 阶段为 ``offer`` 的行数。
- **六阶段漏斗** = ``STATUSES`` 的完整计数（含「已结束」「待确认」两个分支），标签用
  ``STATUS_LABELS``。
- **进行中** = ``is_active(status)`` 的条数；其中**超过 7 天没有更新**的另计一条
  （``is_stalled``，阈值与判定都在 ``models/tracker.py``，与 `/api/stats` 同源）；
  **没有下一步** = 进行中且 ``next_action`` 为空的条数。
- **趋势** = 最近 ``trend_months`` 个自然月（默认 6，接口可传 1..24）的投递数量，
  按 ``applied_at`` 的前缀匹配（空日期不落入趋势）。
- **周内分布** = 按 ``applied_at`` 的星期分七桶；日期为空或解析不出的不入桶。
- **最近 7 / 30 天** = ``created_at`` 落在滚动窗口内的条数。用**滚动窗口**而不是
  "自然日/月"是刻意的：``created_at`` 是 naive UTC，按本地自然日分桶需要用户时区，
  而后端无从得知（服务器时区不等于用户时区），算出来会是一份错的实现。
- **投递最多的公司** = 按 ``company_key`` 归并（那才是合并键），超过 ``TOP_COMPANY_LIMIT``
  家时其余合成一个"其他"计数。
- **记录来源** = 按 ``source`` 分桶，标签取 ``SOURCE_LABELS``。**这是"这一行怎么进系统的"，
  不是"投递渠道"**——本库没有渠道字段（``referral`` 是另一张表），文案上不要混为一谈。
- **内推** = 直接复用 ``referral_service.referral_stats``（转化口径的唯一实现在那里）。
- **提醒** = 复用 ``reminder_service.reminder_urgency_counts``（四档阈值只在那里有一份）。
- **简历与台账健康度** = ``resume_health.resume_health``。
- **``applied_date_gap``** = 有 / 没有**可用投递日期**（``YYYY-MM-DD`` 且真实存在）的条数。
  它存在的唯一理由是**诚实**：趋势图与周内分布只统计有日期的记录，没有它，一张全零的图会让
  用户以为"这几个月真的一份没投"，而事实是那些记录**没填日期**。前端据此显示缺口说明而
  不是画零轴。口径与上面两张图共用 :func:`_applied_date`，三者不会互相矛盾。

**明确不提供的指标**（数据模型支撑不了，做出来就是编的，别再提）：

- **"投递→面试平均天数""各阶段耗时/流失率"**：只有**当前**状态 + 一个 ``status_date``，
  没有状态历史表，也没有"曾经到达过的最高阶段"，无法重建时间线。
- **"面试通过率"**：``stage_note``（"二面""HR 面"）是自由文本，从里面解析轮次得到的
  数字用户无从核对。
- **按行业分布**：全库没有行业字段。
- **按岗位类型（校招/实习）看转化、每份简历的表现**：``job_id`` / ``resume_id`` 目前
  在录入界面上**没有入口**（表单里没有这两个控件，导入路径也硬编码 ``resume_id=None``），
  所以不是"暂时没数据"而是**结构性为空**。本轮只下发 ``track_resume_linked_count``
  把关联覆盖率显示出来，让缺口可见。
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy.orm import Session

from . import trash
from .ratios import rate
from .reminder_service import reminder_urgency_counts
from .referral_service import referral_stats, referral_status_counts
from .resume_health import resume_health
from ..models.profile import utcnow
from ..models.tracker import (
    SOURCE_LABELS,
    SOURCES,
    STATUSES,
    STATUS_LABELS,
    STATUS_RANK,
    STATUS_ASSESSMENT,
    STATUS_INTERVIEW,
    STATUS_OFFER,
    STATUS_UNKNOWN,
    ApplicationTrack,
    is_active,
    is_stalled,
)

TREND_MONTHS = 6
# 「投递最多的公司」展示前几名；其余合成一个"其他"计数，避免长尾把图撑满。
TOP_COMPANY_LIMIT = 8
# 明显不是公司名的记录（纯数字 ID、单字垃圾、空）统一归并到这个中性占位，
# **宁可少显示真公司也不把垃圾当公司名展示**。历史脏数据不强制回填——这里是只读聚合，
# 每次看板都按同一规则重新兜底，存量的脏 company 字段不会被改写成假数据。
UNKNOWN_COMPANY_KEY = "__unknown_company__"
UNKNOWN_COMPANY_LABEL = "未填写公司"
# 公司名首尾可能出现的装饰符（括号、引号、标点等）；正文里的公司名主体不应被这些裹住。
_DECORATIVE_CHARS = "「」『』“”‘’（）()【】[]《》<>、，,。.：:；;！!？?·*#@&%=+\\/￡$€¥"


def clean_company_label(name: str) -> str | None:
    """把一条 ``company`` 原文清洗成可展示的公司名；明显非公司名返回 ``None``。

    历史数据里混进了纯数字（识别导入残留的 ID，如 ``2112`` ``23432``）和单字垃圾
    （如 ``它``）——这些不是公司名，原样展示会误导。规则：

    - 去首尾空白与装饰符，压缩内部空白；
    - 结果为空、整串纯数字、或只剩一个字，一律判为非公司名（返回 ``None``）；
    - 否则返回清洗后的主体。

    ``None`` 由调用方归并到 :data:`UNKNOWN_COMPANY_LABEL`，与"没填公司"走同一口径，
    既不假装知道公司、也不再显示脏数据。
    """
    text = (name or "").strip().strip(_DECORATIVE_CHARS)
    text = re.sub(r"\s+", "", text)
    if not text:
        return None
    if text.isdigit() or len(text) < 2:
        return None
    return text
# 滚动窗口：最近这么多天的"新增记录"（按 created_at，不是 applied_at）。
RECENT_DAYS = (7, 30)
_WEEKDAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _month_window(count: int) -> list[str]:
    """返回最近 ``count`` 个自然月的 ``YYYY-MM`` 列表（升序，含当月）。"""
    today = date.today()
    year, month = today.year, today.month
    months: list[str] = []
    for _ in range(count):
        months.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    months.reverse()
    return months


def _applied_date(track: ApplicationTrack) -> date | None:
    """把 ``applied_at`` 解析成日期；空串或写坏的值返回 ``None``。

    "这条记录有没有可用的投递日期"**只在这一处判定**：趋势、周内分布、缺口计数必须给出
    互相自洽的答案，否则会出现"缺口说有 3 条带日期、图里只落了 2 条"这种自相矛盾。

    要求严格的 ``YYYY-MM-DD`` 十字形状，而不是只看 ``fromisoformat`` 能不能过——
    Python 3.11+ 还接受 ``20260920`` 这种紧凑写法，而趋势用的是 ``[:7]`` 前缀匹配，
    两者对同一个值的判断会不一致。日期写坏的记录一律算"没有日期"，不猜。
    """
    raw = (track.applied_at or "").strip()
    if len(raw) != 10 or raw[4] != "-" or raw[7] != "-":
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _weekday_buckets(tracks: list[ApplicationTrack]) -> list[dict]:
    """按投递日期的星期分七桶（周一→周日，恒为 7 项，含计数为 0 的桶）。"""
    counts = [0] * 7
    for track in tracks:
        applied = _applied_date(track)
        if applied is not None:
            counts[applied.weekday()] += 1
    return [
        {"key": str(index), "label": label, "count": counts[index]}
        for index, label in enumerate(_WEEKDAY_LABELS)
    ]


def _company_ranking(tracks: list[ApplicationTrack]) -> tuple[list[dict], int]:
    """按 ``company_key`` 归并的公司排行，返回 ``(前 N 名, 其余家数)``。

    显示名取该组里**最新一条**记录的清洗后公司名（见 :func:`clean_company_label`）；
    改写过的旧名不覆盖新名。明显不是公司名的记录（纯数字 ID、单字垃圾、空）与"没填公司"
    统一归并到 :data:`UNKNOWN_COMPANY_LABEL`，**明确标注**而不是假装知道或显示脏数据。
    计数为 0 的分支不存在——没有记录就没有公司。
    """
    grouped: dict[str, dict] = {}
    for track in sorted(tracks, key=lambda item: item.id):
        key = track.company_key or ""
        label = clean_company_label(track.company)
        if not key or label is None:
            # 没有公司键、或公司名清洗后判为非公司名：归并到中性占位，绝不展示垃圾。
            key = UNKNOWN_COMPANY_KEY
            label = UNKNOWN_COMPANY_LABEL
        entry = grouped.get(key)
        if entry is None:
            grouped[key] = {"key": key, "label": label, "count": 1, "_id": track.id}
            continue
        entry["count"] += 1
        if track.id >= entry["_id"]:
            entry["label"], entry["_id"] = label, track.id
    ranked = sorted(grouped.values(), key=lambda item: (-item["count"], item["key"]))
    for entry in ranked:
        entry.pop("_id", None)
    return ranked[:TOP_COMPANY_LIMIT], max(0, len(ranked) - TOP_COMPANY_LIMIT)


def _source_counts(tracks: list[ApplicationTrack]) -> list[dict]:
    """按记录来源分桶（只认 ``SOURCES`` 里的取值，标签取 ``SOURCE_LABELS``）。"""
    counts = {source: 0 for source in SOURCES}
    for track in tracks:
        if track.source in counts:
            counts[track.source] += 1
    return [
        {"key": source, "label": SOURCE_LABELS.get(source, source), "count": counts[source]}
        for source in SOURCES
    ]


def build_dashboard(db: Session, trend_months: int = TREND_MONTHS) -> dict:
    """聚合看板所需的全部计数与序列，返回可被 ``DashboardOut`` 校验的字典。

    ``trend_months`` 只影响趋势序列的长度，其余指标口径不变。
    """
    tracks = db.query(ApplicationTrack).filter(trash.live_only(ApplicationTrack)).all()
    now = utcnow()

    counts: dict[str, int] = {status: 0 for status in STATUSES}
    valid_applications = 0
    interview_count = 0
    assessment_count = 0
    offer_count = 0
    active_count = 0
    stalled_count = 0
    no_next_action_count = 0
    dated = 0
    resume_linked = 0

    for track in tracks:
        counts[track.status] = counts.get(track.status, 0) + 1
        if track.status != STATUS_UNKNOWN:
            valid_applications += 1
        rank = STATUS_RANK.get(track.status, -1)
        if rank >= STATUS_RANK[STATUS_INTERVIEW]:
            interview_count += 1
        if rank >= STATUS_RANK[STATUS_ASSESSMENT]:
            assessment_count += 1
        if track.status == STATUS_OFFER:
            offer_count += 1
        if is_active(track.status):
            active_count += 1
            if not (track.next_action or "").strip():
                no_next_action_count += 1
        if is_stalled(track.status, track.updated_at, now):
            stalled_count += 1
        if _applied_date(track) is not None:
            dated += 1
        if track.resume_id is not None:
            resume_linked += 1

    funnel = [
        {"status": status, "label": STATUS_LABELS.get(status, status), "count": counts[status]}
        for status in STATUSES
    ]

    months = _month_window(trend_months)
    month_counts: dict[str, int] = {month: 0 for month in months}
    for track in tracks:
        prefix = (track.applied_at or "")[:7]
        if prefix in month_counts:
            month_counts[prefix] += 1
    trend = [
        {"month": month, "label": f"{int(month[5:7])}月", "count": month_counts[month]}
        for month in months
    ]

    top_companies, other_company_count = _company_ranking(tracks)

    recent = {
        f"recent_{days}d_count": sum(
            1 for track in tracks if track.created_at and track.created_at >= now - timedelta(days=days)
        )
        for days in RECENT_DAYS
    }

    payload = {
        "total_applications": len(tracks),
        "valid_applications": valid_applications,
        "interview_count": interview_count,
        "interview_rate": rate(interview_count, valid_applications),
        "assessment_count": assessment_count,
        "assessment_to_interview_count": interview_count,
        "assessment_pass_rate": rate(interview_count, assessment_count),
        "offer_count": offer_count,
        "offer_rate": rate(offer_count, valid_applications),
        "funnel": funnel,
        "trend": trend,
        # ===== 转化与卡点 =====
        "active_count": active_count,
        "stalled_count": stalled_count,
        "no_next_action_count": no_next_action_count,
        # ===== 时间与节奏 =====
        "weekday": _weekday_buckets(tracks),
        "applied_date_gap": {"dated": dated, "undated": len(tracks) - dated, "total": len(tracks)},
        # ===== 渠道与去向 =====
        "top_companies": top_companies,
        "other_company_count": other_company_count,
        "record_sources": _source_counts(tracks),
        "referral": referral_stats(db).model_dump(),
        "referral_status": referral_status_counts(db),
        "reminder_counts": reminder_urgency_counts(db, now),
        # ===== 简历与健康度 =====
        "track_resume_linked_count": resume_linked,
    }
    payload.update(recent)
    payload.update(resume_health(db))
    return payload


# 助手的 ``get_analytics_overview`` 只该看到"标量摘要"：整份看板里最长的几个数组
# （逐月趋势、周内七桶、招聘公司榜、内推状态）对模型没有用处，却会把上下文稀释掉。
# 这份投影**保留全部标量**，只裁数组——它是同一份口径的一个视图，不是第二份统计。
_BRIEF_DROP = ("trend", "weekday", "referral_status")
_BRIEF_COMPANY_LIMIT = 5


def dashboard_brief(dashboard: dict) -> dict:
    """把看板压成给助手用的摘要：保留全部标量，裁掉长数组。"""
    brief = {key: value for key, value in dashboard.items() if key not in _BRIEF_DROP}
    brief["top_companies"] = dashboard.get("top_companies", [])[:_BRIEF_COMPANY_LIMIT]
    return brief


__all__ = ["TREND_MONTHS", "build_dashboard", "dashboard_brief"]
