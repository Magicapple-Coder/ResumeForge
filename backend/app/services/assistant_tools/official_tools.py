"""助手对「官网采集」与「投递台」的只读工具。

**为什么补这两个**：官网采集是 0.12.0 新上的功能区，投递台一直是核心链路，但助手此前
对这两块**一无所知**——用户问"我给哪几家公司配了采集""上次那家抓到多少""投递队列里
还有什么"，助手只能答"没有这个信息"。而这两个地方恰恰是"用户没法一眼看全"的地方
（采集报告要点开抽屉、队列在另一个页面）。

**刻意只读**：
- 触发采集会主动访问外部站点，产品边界要求"必须用户显式点击"才发起（见 AGENTS.md 与
  `services/sites/official`的说明）——助手**不提供**触发采集的工具。
- 投递同理：真正点下"投递"是用户在投递台上做的动作，助手只负责如实报告队列状态。
- 删除一律不提供（本仓库助手一贯不给删除类工具）。
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ...models.official import OfficialCollectRun, OfficialSite
from ._types import ToolResult

# 与其它列表工具同一档上限，避免把一整页报告塞进上下文。
DEFAULT_LIMIT = 20
MAX_LIMIT = 50
# 证据原文可能很长，报告里只带前若干字符——助手要能引用，不该把上下文吃满。
MAX_EVIDENCE_CHARS = 1200


def _site_brief(site: OfficialSite, latest: OfficialCollectRun | None) -> dict:
    brief: dict = {
        "id": site.id,
        "company": site.company,
        "homepage_url": site.homepage_url,
        "careers_url": site.careers_url,
        "source_kind": site.source_kind or "通用网页抽取",
        "confidence": site.confidence,
        "enabled": site.enabled,
        "robots_allowed": site.robots_allowed,
        "last_probed_at": site.last_probed_at.isoformat() if site.last_probed_at else None,
    }
    if latest is not None:
        # 结论与它的依据一起给：只给"已确认为全量"而不给依据，助手就没法解释为什么。
        brief["最近一次采集"] = {
            "run_id": latest.id,
            "status": latest.status,
            "verdict": latest.verdict,
            "headline": latest.headline,
            "pages": latest.pages,
            "collected": latest.collected,
            "total_hint": latest.total_hint,
            "finished_at": latest.finished_at.isoformat() if latest.finished_at else None,
        }
    return brief


def _latest_runs(db: Session, site_ids: list[int]) -> dict[int, OfficialCollectRun]:
    """每个站点最近一次采集（一次查询取回，避免按公司逐个查库）。"""
    if not site_ids:
        return {}
    rows = (
        db.query(OfficialCollectRun)
        .filter(OfficialCollectRun.site_id.in_(site_ids))
        .order_by(OfficialCollectRun.id.desc())
        .all()
    )
    latest: dict[int, OfficialCollectRun] = {}
    for row in rows:
        latest.setdefault(row.site_id, row)
    return latest


def _tool_list_official_sites(db: Session, arguments: dict) -> ToolResult:
    limit = min(int(arguments.get("limit") or DEFAULT_LIMIT), MAX_LIMIT)
    keyword = str(arguments.get("keyword") or "").strip()
    query = db.query(OfficialSite)
    if keyword:
        query = query.filter(OfficialSite.company.contains(keyword))
    sites = query.order_by(OfficialSite.id.asc()).limit(limit).all()
    latest = _latest_runs(db, [site.id for site in sites])
    payload = {
        "总数": db.query(OfficialSite).count(),
        "返回": len(sites),
        "公司": [_site_brief(site, latest.get(site.id)) for site in sites],
        "说明": (
            "verdict 只有三态：confirmed_full（已确认为全量）/ confirmed_partial（已确认不全）"
            "/ unverified（无法确认）。无法确认≠这家公司没有岗位。"
        ),
    }
    return ToolResult(
        text=json.dumps(payload, ensure_ascii=False),
        summary=f"查看了 {len(sites)} 家采集源",
        link="/official",
    )


def _tool_get_official_run(db: Session, arguments: dict) -> ToolResult:
    run_id = int(arguments.get("run_id") or 0)
    run = db.get(OfficialCollectRun, run_id)
    if run is None:
        return ToolResult(
            text=json.dumps({"错误": f"没有 id={run_id} 的采集记录"}, ensure_ascii=False),
            summary="采集记录不存在",
            link="/official",
        )
    site = db.get(OfficialSite, run.site_id)
    payload = {
        "run_id": run.id,
        "company": site.company if site else "",
        "status": run.status,
        "verdict": run.verdict,
        "headline": run.headline,
        "pages": run.pages,
        "collected": run.collected,
        "stored": run.stored,
        "skipped": run.skipped,
        "detail_missing": run.detail_missing,
        "total_hint": run.total_hint,
        "missing": run.missing,
        "blocks": run.blocks,
        "evidence": (run.evidence or "")[:MAX_EVIDENCE_CHARS],
        "error": run.error,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }
    return ToolResult(
        text=json.dumps(payload, ensure_ascii=False),
        summary=f"查看了采集报告 #{run.id}",
        link="/official",
    )


def _tool_list_apply_queue(db: Session, arguments: dict) -> ToolResult:
    """投递台的队列（待投递/已投递/失败），只读。"""
    from ..apply import apply_service  # 局部导入：这个模块依赖较重，避免拖慢助手启动

    limit = min(int(arguments.get("limit") or DEFAULT_LIMIT), MAX_LIMIT)
    items = apply_service.list_queue(db)
    rows = [
        {
            "id": item.id,
            "company": item.company,
            "job_title": item.job_title,
            "status": item.status,
            "resume_title": item.resume_title,
            "apply_supported": item.apply_supported,
            "admission": item.admission,
        }
        for item in items[:limit]
    ]
    payload = {
        "总数": len(items),
        "返回": len(rows),
        "队列": rows,
        "说明": "这是「投递台」的队列状态快照。助手不代为发起投递——那一步必须在投递台上由用户点击。",
    }
    return ToolResult(
        text=json.dumps(payload, ensure_ascii=False),
        summary=f"查看了投递队列（{len(items)} 条）",
        link="/apply",
    )


__all__ = [
    "_tool_get_official_run",
    "_tool_list_apply_queue",
    "_tool_list_official_sites",
]
