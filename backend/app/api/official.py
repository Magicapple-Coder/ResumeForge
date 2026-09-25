"""官网岗位采集接口。

三层分工：本模块只做 HTTP 形状（路由、状态码、序列化），编排与落库在
``services/sites/official/service.py``，取回与解析在适配器层。

**采集是后台跑的**：``POST /sites/{id}/collect`` 只建一条运行记录再起任务，**立刻返回**；
前端轮询 ``GET /runs/{id}`` 看进展，``POST /runs/{id}/stop`` 请求停止。多页站点是几十次
请求加限速等待，同步走完会把 HTTP 请求挂住——界面只能干等，用户也没法中途停下。

传输实现一律走 ``service.default_http_factory()``：注入点只有那一处，接口路径与后台任务
必须拿到同一个实现，否则"哪条路径被替换了"会变成一个要靠运气的问题。
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.official import (
    BLOCK_LABELS,
    RUN_STATUS_LABELS,
    VERDICT_LABELS,
    OfficialCollectRun,
    OfficialSite,
)
from ..schemas.official import (
    CollectRequest,
    OfficialCandidateOut,
    OfficialExtractionOut,
    OfficialDiscoverQuery,
    OfficialDiscoveryHistoryOut,
    OfficialDiscoveryOut,
    OfficialProbeOut,
    OfficialRunDetailOut,
    OfficialRunOut,
    OfficialSiteCreate,
    OfficialSiteOut,
    OfficialSiteUpdate,
    OfficialTrendOut,
)
from ..services.settings_service import get_search_config
from ..services.sites.official import history, service
from ..services.sites.official.base import CONFIDENCE_LABELS, FeedHttp
from ..services.sites.official.discovery import discover_companies
from ..services.sites.official.probe import PROBE_STATE_LABELS
from ..services.sites.official.registry import get_feed_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/official", tags=["official"])


@asynccontextmanager
async def _open_http(db: Session) -> AsyncIterator[FeedHttp]:
    """开一个传输连接，用完关掉。

    **走 ``service.default_http_factory(db)`` 而不是直接构造具体实现**：注入点只有那一处，
    否则测试替换了工厂、接口这条路径却仍用真实现去联网——而后台任务与接口必须拿到同一个
    实现，不然"哪条路径被替换了"会变成一个要靠运气的问题。传 ``db`` 是因为渲染升级需要它
    去读投递台配置（用哪个浏览器）。
    """
    http = service.default_http_factory(db)
    try:
        yield http
    finally:
        await http.aclose()


def _raise(error: service.OfficialError) -> NoReturn:
    """服务层错误 → 合适的 HTTP 状态码。

    "找不到"与"请求本身有问题"分开：前者是 404，后者是 400。糊成同一个码会让前端没法
    区分"该刷新列表了"和"该改输入"。

    标注 ``NoReturn`` 不是为了好看：它在 ``except`` 分支里调用，而调用方在 ``try`` 里赋值、
    在 ``except`` 之后继续使用那些变量。写成 ``-> None`` 时静态检查会合理地怀疑"变量可能未
    绑定"，而实际语义是这一支**必定抛出**。
    """
    status = 404 if isinstance(error, service.OfficialNotFound) else 400
    raise HTTPException(status_code=status, detail=str(error)) from error


def _site_out(db: Session, site: OfficialSite, *, latest: OfficialCollectRun | None = None) -> OfficialSiteOut:
    """把一个源序列化成接口模型。"""
    registry = get_feed_registry()
    feed = registry.resolve(site.source_kind)

    if latest is None:
        latest = (
            db.query(OfficialCollectRun)
            .filter(OfficialCollectRun.site_id == site.id)
            .order_by(OfficialCollectRun.started_at.desc())
            .first()
        )

    return OfficialSiteOut(
        id=site.id,
        company=site.company,
        homepage_url=site.homepage_url,
        careers_url=site.careers_url,
        source_kind=site.source_kind,
        source_label=feed.display_name if feed else "",
        endpoint=site.endpoint,
        confidence=site.confidence,
        confidence_label=CONFIDENCE_LABELS.get(site.confidence, ""),
        probe_evidence=site.probe_evidence,
        robots_allowed=site.robots_allowed,
        robots_detail=site.robots_detail,
        crawl_delay_seconds=site.crawl_delay_seconds,
        min_interval_seconds=site.min_interval_seconds,
        enabled=site.enabled,
        last_probed_at=site.last_probed_at,
        created_at=site.created_at,
        latest_verdict=latest.verdict if latest else "",
        latest_verdict_label=VERDICT_LABELS.get(latest.verdict, "") if latest else "",
        latest_headline=latest.headline if latest else "",
        latest_run_id=latest.id if latest else None,
        latest_status=latest.status if latest else "",
        latest_status_label=RUN_STATUS_LABELS.get(latest.status, "") if latest else "",
        # 能不能采集由服务端判定，前端只读。
        can_collect=feed is not None and site.robots_allowed is not False,
    )


def _run_out(run: OfficialCollectRun, *, company: str = "") -> OfficialRunOut:
    return OfficialRunOut(
        id=run.id,
        site_id=run.site_id,
        site_company=company,
        status=run.status,
        status_label=RUN_STATUS_LABELS.get(run.status, run.status),
        pages=run.pages,
        collected=run.collected,
        stored=run.stored,
        skipped=run.skipped,
        detail_missing=run.detail_missing,
        total_hint=run.total_hint,
        verdict=run.verdict,
        verdict_label=VERDICT_LABELS.get(run.verdict, ""),
        evidence=run.evidence,
        headline=run.headline,
        missing=run.missing,
        blocks=list(run.blocks or []),
        # 分类的**中文**一并给前端：让界面自己维护一份枚举映射，就是两处定义开始漂移的时刻。
        block_labels=[BLOCK_LABELS.get(block, block) for block in (run.blocks or [])],
        started_at=run.started_at,
        finished_at=run.finished_at,
        error=run.error,
        llm_calls=run.llm_calls,
    )


def _run_detail_out(db: Session, run: OfficialCollectRun) -> OfficialRunDetailOut:
    """报告页的完整出口：账目 + 逐层依据 + 趋势提醒。

    **只留这一个出口**：``get_run`` 与 ``verify_run`` 都要返回它，各写一遍迟早会漏字段
    （而漏掉的字段在前端表现为"这个功能没做"，没人会想到是序列化漏了）。
    """
    site = db.get(OfficialSite, run.site_id)
    base = _run_out(run, company=site.company if site else "")
    signal = service.trend_signal_for(db, run)
    # 抽取方式单独成字段而不是塞进 ``reconcile_detail``：它**不是对账依据**，混进"依据"那一栏
    # 会让用户以为"用了模型"与"抓全了没有"有关系。
    raw_extraction = dict(run.reconcile_detail or {}).get("extraction") or {}
    extraction = OfficialExtractionOut(
        methods=[str(item) for item in raw_extraction.get("methods") or []],
        llm_calls=int(raw_extraction.get("llm_calls") or 0),
        recipes_learned=int(raw_extraction.get("recipes_learned") or 0),
        deep_links_skipped=int(raw_extraction.get("deep_links_skipped") or 0),
    )
    return OfficialRunDetailOut(
        **base.model_dump(),
        reconcile_detail=dict(run.reconcile_detail or {}),
        extraction=extraction,
        trend=OfficialTrendOut(
            state=signal.state,
            label=signal.label,
            detail=signal.detail,
            baseline=signal.baseline,
            latest=signal.latest,
        ),
    )


@router.get("/sites", response_model=list[OfficialSiteOut])
def list_sites(
    enabled_only: bool = Query(default=False), db: Session = Depends(get_db)
) -> list[OfficialSiteOut]:
    return [_site_out(db, site) for site in service.list_sites(db, enabled_only=enabled_only)]


@router.post("/discover", response_model=OfficialDiscoveryOut)
async def discover(payload: OfficialDiscoverQuery, db: Session = Depends(get_db)) -> OfficialDiscoveryOut:
    """按岗位需求搜出一份**候选公司线索**，供用户勾选后再逐个新增。

    它和新增源分成两步是有意的：发现只发搜索请求、不碰候选站点，用户看到清单后可以改公司名、
    剔掉不想要的，再让每个真正进入探测。合成一步会让用户为搜索的每一条结果都付一次探测成本，
    而他可能一条都不想要。

    搜索设置走 ``settings_service.get_search_config(db)``——与「联网搜索设置」页共用同一份
    配置，用户在那儿关掉的搜索源，这里也不会偷偷用。
    """
    result = await discover_companies(
        payload.keywords, payload.city, config=get_search_config(db)
    )
    candidates = [
        OfficialCandidateOut(
            company=candidate.company,
            url=candidate.url,
            host=candidate.host,
            evidence=candidate.evidence,
            is_careers_page=candidate.is_careers_page,
            target_field=candidate.target_field,
        )
        for candidate in result.candidates
    ]
    record = history.save_discovery_search(
        db,
        keywords=payload.keywords,
        city=payload.city,
        queries=result.queries,
        detail=result.detail,
        candidates=[candidate.model_dump() for candidate in candidates],
    )
    return OfficialDiscoveryOut(
        history_id=record.id,
        candidates=candidates,
        queries=result.queries,
        detail=result.detail,
    )


@router.get("/discover/history", response_model=list[OfficialDiscoveryHistoryOut])
def list_discovery_history(
    limit: int = Query(default=history.DEFAULT_HISTORY_LIMIT, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[OfficialDiscoveryHistoryOut]:
    """列出最近的岗位找公司记录，并返回当时保存的候选快照。"""
    output: list[OfficialDiscoveryHistoryOut] = []
    for record in history.list_discovery_searches(db, limit=limit):
        candidates = [
            OfficialCandidateOut.model_validate(candidate)
            for candidate in (record.candidates or [])
            if isinstance(candidate, dict)
        ]
        output.append(
            OfficialDiscoveryHistoryOut(
                id=record.id,
                keywords=record.keywords,
                city=record.city,
                candidates=candidates,
                queries=[str(query) for query in (record.queries or [])],
                detail=record.detail,
                candidate_count=record.candidate_count,
                created_at=record.created_at,
            )
        )
    return output


@router.post("/sites", response_model=OfficialProbeOut, status_code=201)
async def create_site(
    payload: OfficialSiteCreate, db: Session = Depends(get_db)
) -> OfficialProbeOut:
    """新建一个源并**立刻探测**。

    加源与探测合成一步：用户填完就应当马上知道"这家公司能不能采、用哪套系统"，
    让他在看到结果前再多点一次按钮没有意义。
    """
    try:
        site = service.create_site(
            db,
            company=payload.company,
            homepage_url=payload.homepage_url,
            careers_url=payload.careers_url,
        )
    except service.OfficialError as error:
        _raise(error)

    async with _open_http(db) as http:
        result = await service.probe_and_store(db, site, http=http)
    return _probe_out(db, result)


@router.put("/sites/{site_id}", response_model=OfficialProbeOut)
async def update_site(
    site_id: int, payload: OfficialSiteUpdate, db: Session = Depends(get_db)
) -> OfficialProbeOut:
    """修改公司名称或地址，并用新信息重新探测。"""
    try:
        site = service.update_site(
            db,
            site_id,
            company=payload.company,
            homepage_url=payload.homepage_url,
            careers_url=payload.careers_url,
        )
        async with _open_http(db) as http:
            result = await service.probe_and_store(db, site, http=http)
    except service.OfficialError as error:
        _raise(error)
    return _probe_out(db, result)


@router.post("/sites/{site_id}/probe", response_model=OfficialProbeOut)
async def reprobe_site(site_id: int, db: Session = Depends(get_db)) -> OfficialProbeOut:
    """重新探测。站点改版、或用户补填了更准确的招聘页地址之后用。"""
    try:
        site = service.get_site(db, site_id)
        async with _open_http(db) as http:
            result = await service.probe_and_store(db, site, http=http)
    except service.OfficialError as error:
        _raise(error)
    return _probe_out(db, result)


def _probe_out(db: Session, result: service.SiteProbeResult) -> OfficialProbeOut:
    return OfficialProbeOut(
        state=result.outcome.state,
        state_label=PROBE_STATE_LABELS.get(result.outcome.state, result.outcome.state),
        site=_site_out(db, result.site),
        job_count=result.outcome.job_count,
        evidence=result.outcome.detail,
        attempts=[
            {
                "feed_key": attempt.feed_key,
                "endpoint": attempt.endpoint,
                "block": attempt.block,
                "block_label": BLOCK_LABELS.get(attempt.block, attempt.block),
                "job_count": attempt.job_count,
                "detail": attempt.detail,
            }
            for attempt in result.outcome.attempts
        ],
    )


@router.delete("/sites/{site_id}", status_code=204)
def delete_site(site_id: int, db: Session = Depends(get_db)) -> None:
    try:
        service.delete_site(db, site_id)
    except service.OfficialError as error:
        _raise(error)


@router.post("/sites/{site_id}/collect", response_model=OfficialRunOut)
async def collect_site(
    site_id: int,
    payload: CollectRequest | None = None,
    db: Session = Depends(get_db),
) -> OfficialRunOut:
    """开始采一次。**立刻返回**，实际采集在后台跑；轮询 ``GET /runs/{id}`` 看进展。

    必须是 ``async def``：后台任务要挂在**当前运行的事件循环**上，而同步端点由 FastAPI
    放进线程池执行，那里没有事件循环（``create_task`` 会直接抛 ``RuntimeError``）。
    本函数自身不阻塞——只写一条运行记录再起任务。

    多页站点是几十次请求加限速等待，同步走完会把 HTTP 请求挂住——界面只能干等，
    用户也没法中途停下。

    robots 拒绝、被站点阻断、用户停止都**不是** HTTP 错误——它们各自是一条运行记录，
    带着可读的结论返回 200。用 4xx/5xx 表达它们会让前端只能弹一句"请求失败"，
    而这恰恰是这个功能最不该给出的反馈。

    ``max_jobs`` 是**这一次**的条数上限（不填 = 不设）。``job_keywords`` 是**这一次**的岗位
    关键词筛选，同样不写回公司配置。它只影响这一趟：岗位上万条的站点
    一次翻不完，而用户多半只想先看前几十条——不设的话他只能坐在那儿等十分钟再手动点停止，
    拿到的还是一份「已停止」的报告。
    """
    try:
        site = service.get_site(db, site_id)
        run = service.start_collection(
            db,
            site,
            max_jobs=payload.max_jobs if payload else None,
            job_keywords=payload.job_keywords if payload else None,
        )
    except service.OfficialError as error:
        _raise(error)
    return _run_out(run, company=site.company)


@router.post("/runs/{run_id}/stop", response_model=OfficialRunOut)
def stop_run(run_id: int, db: Session = Depends(get_db)) -> OfficialRunOut:
    """请求停止一次采集。

    **不是强杀**：采集器在下一个检查点（每条岗位之间）自己停下来，因此已抓到的岗位与账目
    都是完整的，照常给出对账结论。强杀会让记录停在半成品状态。
    """
    try:
        run = service.request_stop(db, run_id)
    except service.OfficialError as error:
        _raise(error)
    site = db.get(OfficialSite, run.site_id)
    return _run_out(run, company=site.company if site else "")


@router.get("/runs", response_model=list[OfficialRunOut])
def list_runs(
    site_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[OfficialRunOut]:
    runs = service.list_runs(db, site_id=site_id, limit=limit)
    names = {
        site.id: site.company for site in service.list_sites(db)
    }
    return [_run_out(run, company=names.get(run.site_id, "")) for run in runs]


@router.post("/runs/{run_id}/verify", response_model=OfficialRunDetailOut)
async def verify_run(run_id: int, db: Session = Depends(get_db)) -> OfficialRunDetailOut:
    """核实这次采集的待核实地址，并据此重算结论。

    **它是把「无法确认」变成硬结论的唯一途径**：待核实地址里既有真漏掉的，也有早就招满、
    链接还留在地图里的——逐个访问才能分清。核实"仍在招"→ 确凿漏抓；全部核实为已下架 →
    差额被完全解释掉，结论升级为"已确认为全量"。

    一次最多核实 20 个：这是**对站点的礼貌约束**，不是性能考虑——待核实地址可能上千条，
    逐条访问等于对站点发起一次扫描。核实是抽查，不是补抓。
    """
    try:
        async with _open_http(db) as http:
            run = await service.verify_run(db, run_id, http=http)
    except service.OfficialError as error:
        _raise(error)
    return _run_detail_out(db, run)


@router.get("/runs/{run_id}", response_model=OfficialRunDetailOut)
def get_run(run_id: int, db: Session = Depends(get_db)) -> OfficialRunDetailOut:
    try:
        run = service.get_run(db, run_id)
    except service.OfficialError as error:
        _raise(error)
    return _run_detail_out(db, run)
