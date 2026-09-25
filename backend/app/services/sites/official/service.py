"""官网源的增删查、探测与采集：业务层唯一入口。

分三层是有意的——``probe`` 只回答"这家公司用哪套系统"，``collector`` 只回答"这一次抓到了什么"，
本模块把它们串起来并**落库**（源、每次运行的账目、计数趋势）。API 层只调这里，
不直接碰适配器或传输层。

两条在这里被执行、而不是留给调用方自觉的规则：

- **采集前必须先过 robots**。放在这一层是因为它是唯一能拦住"绕过检查直接采集"的位置；
- **被 robots 拒绝不是错误，是一条结论**。它照样落一条运行记录并说明原因，用户回看时能
  知道"这家站点不允许采集"，而不是面对一个空的错误提示。
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from .... import database

from ....models.official import (
    BLOCK_FORBIDDEN,
    RUN_DONE,
    RUN_FAILED,
    RUN_RUNNING,
    RUN_STOPPED,
    VERDICT_UNKNOWN,
    OfficialCollectRun,
    OfficialSite,
)
from ....models.profile import utcnow
from ...browser.cdp_client import CdpClient
from ... import settings_service
from ...llm import create_provider
from .base import FeedHttp, ProbeContext
from .browser_http import BrowserUpgradeHttp
from .collector import OfficialCollectReport, OfficialCollector
from .generic.llm_extract import ListingExtractor
from .generic.recipe import RECIPE_SCHEMA
from .probe import PROBE_HIT, ProbeOutcome, probe_site
from .reconcile import input_from_dict, input_to_dict, reconcile
from .http import HttpxFeedHttp
from .registry import FeedRegistry, get_feed_registry
from .runner import OfficialRunner, get_official_runner
from .robots import RobotsAwareHttp, RobotsDecision
from .sitemap import fetch_sitemap_urls
from .trend import TrendSignal, compare_trend, is_measurement, measured_counts
from .urls import looks_like_job_url
from .verify import (
    VERIFIED_GONE,
    VERIFIED_LIVE,
    VERIFY_STATE_LABELS,
    verify_all,
)

logger = logging.getLogger(__name__)

# 首页取回上限：只为了在里面找招聘页链接，不需要整页。
HOMEPAGE_HTML_LIMIT = 400_000


class OfficialError(Exception):
    """对外的可展示错误（中文 message）。"""


class OfficialNotFound(OfficialError):
    """目标记录不存在。

    单独一类是为了让接口层能给出 **404** 而不是 400：两者对前端和用户的含义不同
    （"这个东西没了" vs "你这次请求本身有问题"）。
    """


def default_http_factory(db: Session) -> FeedHttp:
    """传输实现的工厂——**所有构造传输的地方都走它**（同步的接口路径与后台任务）。

    **做成模块级默认值，是为了可替换**：后台任务自己构造传输对象，没有调用方能注入的位置，
    而测试必须能把它换掉。换不掉的后果不是"测试难看"，而是**用例会真的去请求外部站点**：
    在能联网的开发机上"碰巧通过"、在 CI 上超时，是最难定位的一类测试问题。项目里站点筛选
    清单的 ``default_fetcher`` 是同一个模式、同一个理由。

    **返回的是组合好的传输**：HTTP 取回在外、渲染升级在外层包一层。组合放这里而不是放调用方，
    是为了让"哪些能力开着"只有一个答案——否则接口路径与后台任务迟早会拿到不同的组合。

    顺序上还有个硬要求：调用方拿到它之后**必须再套一层 ``RobotsAwareHttp``**（``probe_and_store``
    与 ``collect_site`` 都是这么做的）。若反过来（闸门在内），浏览器取回就会绕过 robots 检查——
    **换一个传输不该换掉规则**。
    """
    return BrowserUpgradeHttp(HttpxFeedHttp(), lambda: default_browser_client(db))


def default_listing_extractor(db: Session) -> ListingExtractor | None:
    """配方与模型那一级的执行者——**与传输工厂同一个模式、同一个理由**：模块级默认值才换得掉。

    **没配模型时返回 ``None``**，而不是抛错：没配模型不是故障，只是这一级用不了。上层据此
    如实说明"没有配置可用的大模型"——"读不出来"与"没试"对用户是两件事。

    模型配置直接用用户当前的那份（与助手、简历生成共用），不另立一套：用户在哪里配过，
    这里就用哪一个，不需要他再配一遍。
    """
    config = settings_service.get_llm_config(db)
    # **判据与全项目一致：有 base_url 与 model 就算配了**（``text_extraction.llm_is_configured``）。
    # 这里曾经额外要求 ``api_key`` 非空，于是本地模型（Ollama / LM Studio 那类预设，本来就不需要
    # key）会被判成"没配模型"：整级静默跳过，而报告里还写着"没有配置可用的大模型"——一句假话。
    if not config.base_url.strip() or not config.model.strip():
        return None
    try:
        resolved = settings_service.resolve_llm_config_api_key(db, config)
    except Exception:  # noqa: BLE001 - 配置损坏不该让整次采集失败，退到"没有模型"即可
        logger.warning("读取大模型配置失败，本次采集不做模型兜底", exc_info=True)
        return None
    return ListingExtractor(create_provider(resolved))


def default_browser_client(db: Session) -> CdpClient | None:
    """取投递专用浏览器的 CDP 客户端；**浏览器没在跑时返回 ``None``**。

    复用投递台那个浏览器，而不是另起一个：它是应用唯一驱动的浏览器实例，用户可能已经在里面
    登录过站点；另起一个既多占内存，也要求用户再登录一次。

    延迟导入是**有意的**：本模块属于采集（读）域，而浏览器管理器归投递（写）域，
    模块级导入会把两者在导入期绑死，而它们的生命周期本来就不同（投递台可能根本没被用过）。

    **导入本身也在 ``try`` 里面**。它曾经在外面，于是这条路径第一次在真实站点上跑到时，
    一个写错的模块路径把整次采集炸成了 500——而渲染升级是个**可选**能力，它出任何问题都
    只该让这次采集少一种读法。这条路径只在"页面确认要渲染"时才走到，所以写错的话，
    离线测试里一次都不会暴露（实测：两千多个用例全绿，真实采集一按就崩）。
    """
    try:
        from ...apply import get_browser_manager

        manager = get_browser_manager(db)
        if not manager.is_running():
            return None
        return manager.client()
    except Exception:  # noqa: BLE001 - 拿不到浏览器只是"这次不做渲染升级"
        logger.warning("取浏览器客户端失败，本次不做渲染升级", exc_info=True)
        return None


def domain_of(url: str) -> str:
    """取归一化后的主机名，作为"按域名猜 token"的输入。"""
    try:
        return (urlsplit(url).hostname or "").strip().casefold()
    except ValueError:
        return ""


def _target_url(site: OfficialSite) -> str:
    """探测/检查 robots 时用的代表地址：优先招聘页，其次首页。"""
    return site.careers_url or site.homepage_url


@dataclass
class SiteProbeResult:
    site: OfficialSite
    outcome: ProbeOutcome
    robots: RobotsDecision | None = None

    @property
    def usable(self) -> bool:
        return self.outcome.state == PROBE_HIT


async def probe_and_store(
    db: Session,
    site: OfficialSite,
    *,
    http: FeedHttp,
    registry: FeedRegistry | None = None,
) -> SiteProbeResult:
    """探测一家公司的招聘系统，并把结论写回源记录。

    **先过 robots 再取首页**：首页取回也是一次自动请求，不受 robots 约束的请求不存在。
    被拒绝时照样返回结果（``outcome`` 是"被阻断"），由调用方决定怎么展示——
    "不允许采集"和"没识别出来"是两件事，不能糊成一条错误。
    """
    registry = registry or get_feed_registry()
    target = _target_url(site)
    if not target:
        raise OfficialError("请至少填写官网地址或招聘页地址")

    # 所有取回（robots 自身除外）都从这道闸门走：robots 按主机生效，而探测会碰到用户给的
    # 域名之外的接口域名，只查前者等于对真正被打的那个主机一无所知。
    gate = RobotsAwareHttp.wrap(http)
    robots = await gate.decision_for(target)
    _store_robots(site, robots)

    # 首页取回不额外判一次 robots：闸门已经拦了。少一条分支就少一处会写错的地方。
    homepage_html = await _fetch_homepage(gate, site.homepage_url)

    ctx = ProbeContext(
        company=site.company,
        domain=domain_of(site.homepage_url or site.careers_url),
        homepage_url=site.homepage_url,
        careers_url=site.careers_url,
        homepage_html=homepage_html,
    )
    outcome = await probe_site(gate, ctx, registry=registry)

    if outcome.hit is not None:
        site.source_kind = outcome.hit.target.feed_key
        site.endpoint = outcome.hit.target.endpoint
        site.params = dict(outcome.hit.target.params)
        site.confidence = outcome.hit.confidence
        site.probe_evidence = outcome.hit.evidence
    else:
        # 识别不出来时**清空**上一次的结论：留着旧端点会让下一次采集打到一个已经不对的地址，
        # 而报告里还写着"已识别的系统：X"。
        site.source_kind = ""
        site.endpoint = ""
        site.params = {}
        site.confidence = ""
        site.probe_evidence = outcome.detail
    site.last_probed_at = utcnow()
    db.commit()
    return SiteProbeResult(site=site, outcome=outcome, robots=robots)


def _store_robots(site: OfficialSite, robots: RobotsDecision) -> None:
    site.robots_allowed = robots.allowed
    site.robots_detail = robots.detail
    site.crawl_delay_seconds = robots.crawl_delay


async def _fetch_homepage(http: FeedHttp, homepage_url: str) -> str:
    """取首页 HTML（只为了找招聘页链接）。取不到就返回空串，探测继续用其它线索。"""
    if not homepage_url:
        return ""
    result = await http.request("GET", homepage_url, max_bytes=HOMEPAGE_HTML_LIMIT)
    return result.text if result.ok else ""


async def collect_site(
    db: Session,
    site: OfficialSite,
    *,
    http: FeedHttp,
    registry: FeedRegistry | None = None,
    collector: OfficialCollector | None = None,
    run: OfficialCollectRun | None = None,
    max_jobs: int | None = None,
    job_keywords: str | None = None,
    checkpoint: Callable[[], None] | None = None,
    on_progress: Callable[[OfficialCollectReport], None] | None = None,
) -> OfficialCollectRun:
    """按已识别的系统采集一家公司，落一条运行记录并返回它。

    ``CollectCancelled`` 会转成"已停止"的运行记录后**正常返回**——用户主动停止不是失败，
    报告里仍然要有这一次的账目。

    ``run`` 允许调用方**预先建好**运行记录：后台执行时接口要立刻返回一个 id，而记录必须在
    任务启动之前就存在（否则前端拿不到可轮询的东西）。传 ``None`` 就沿用旧行为自己建。
    """
    registry = registry or get_feed_registry()
    feed = registry.resolve(site.source_kind)
    if feed is None:
        raise OfficialError(
            f"这家公司还没识别出可采集的招聘系统，请先重新探测（当前支持：{registry.supported_names()}）"
        )

    target = _target_url(site)
    gate = RobotsAwareHttp.wrap(http)
    robots = await gate.decision_for(target)
    _store_robots(site, robots)
    if not robots.allowed:
        if run is None:
            return _record_refused_run(db, site, robots, target)
        # 后台执行时记录已经建好了，就地把它收尾成"被拒绝"，不另开一条。
        _finish_as_refused(db, run, robots, target)
        return run

    if run is None:
        run = OfficialCollectRun(site_id=site.id, status=RUN_RUNNING, started_at=utcnow())
        db.add(run)
        db.commit()

    # 站点地图在采集**之前**取：它给的是"可枚举全集"，本来就要与实际抓到的做差集；
    # 放在后面取并不会让差额更准，反而多一次"采集跑完才知道要等多久"的等待。
    expected_urls, sitemap_detail = await _sitemap_expectations(gate, robots, target)

    collector = collector or OfficialCollector(max_jobs=max_jobs)
    try:
        report = await collector.run(
            session=db,
            site=site,
            feed=feed,
            http=gate,
            crawl_delay_seconds=site.crawl_delay_seconds,
            checkpoint=checkpoint or _noop_checkpoint,
            expected_urls=expected_urls,
            on_progress=on_progress,
            job_keywords=job_keywords,
            task_id=run.id,
            # 配方与模型那一级只对通用路径有意义（适配器自己声明），这里照常传——
            # 没配模型时是 None，那一级会如实说明"没有配置可用的大模型"。
            extractor=default_listing_extractor(db),
        )
    except Exception as exc:  # noqa: BLE001 - 任何异常都要落成一条可读的运行记录
        logger.exception("官网采集失败：site_id=%s", site.id)
        run.status = RUN_FAILED
        run.error = f"{type(exc).__name__}: {exc}"[:500]
        run.finished_at = utcnow()
        db.commit()
        return run

    _store_memory(site, report)
    # 采集器发现"站点地图与实抓地址不在同一地址空间"时会给出自己的说明，那一份更准确
    # （它知道抓到了哪些地址），优先用它。
    _apply_report(run, report, sitemap_detail=report.sitemap_note or sitemap_detail)
    run.status = RUN_STOPPED if report.stopped_reason == "已停止" else RUN_DONE
    run.finished_at = utcnow()
    db.commit()
    return run


# ===== 后台执行 =====


def start_collection(
    db: Session,
    site: OfficialSite,
    *,
    max_jobs: int | None = None,
    job_keywords: str | None = None,
) -> OfficialCollectRun:
    """建一条运行记录并把实际采集排到后台，**立刻返回**。

    同步走完会把 HTTP 请求挂住：多页站点是几十次请求加限速等待，界面只能干等，用户也没法
    中途停下。所以记录先建（前端才有东西可轮询），活儿交给运行器。

    ``max_jobs`` 是**用户这次**设的条数上限（``None`` = 没设）。它只管这一次，不存进站点——
    它回答的是"这回我只要看前几十条"，而不是"这家公司永远只采这么多"。站点的规模是站点自己的
    属性，暂时还不需要一个记住的配置项（真需要时再加，那时才该动模型与迁移）。
    """
    registry = get_feed_registry()
    if registry.resolve(site.source_kind) is None:
        raise OfficialError(
            f"这家公司还没识别出可采集的招聘系统，请先重新探测（当前支持：{registry.supported_names()}）"
        )

    runner = get_official_runner()
    active = (
        db.query(OfficialCollectRun.id)
        .filter(
            OfficialCollectRun.site_id == site.id,
            OfficialCollectRun.status == RUN_RUNNING,
        )
        .all()
    )
    # **两层都要看**：数据库里"进行中"可能只是上次崩溃留下的幽灵记录（启动时会被清理），
    # 而运行器知道此刻真正在跑的是哪些。
    if any(runner.is_running(row[0]) for row in active):
        raise OfficialError("这家公司已经有一次采集在进行中，请等它结束或先停止它")

    run = OfficialCollectRun(site_id=site.id, status=RUN_RUNNING, started_at=utcnow())
    db.add(run)
    db.commit()
    db.refresh(run)

    runner.start(
        run.id,
        _collect_in_background(
            site.id,
            run.id,
            runner,
            max_jobs=max_jobs,
            job_keywords=job_keywords,
        ),
    )
    return run


def request_stop(db: Session, run_id: int) -> OfficialCollectRun:
    """请求停止一次采集。**不是强杀**：采集器在下一个检查点自己停下来。"""
    run = get_run(db, run_id)
    if not get_official_runner().request_stop(run_id):
        raise OfficialError("这次采集已经结束了")
    return run


async def _collect_in_background(
    site_id: int,
    run_id: int,
    runner: OfficialRunner,
    *,
    max_jobs: int | None = None,
    job_keywords: str | None = None,
) -> None:
    """后台协程：自己开会话、自己结束，异常一律不逃逸出任务。

    **必须自己开会话**：请求级的会话在响应返回时就关了，拿它写库等于写到空气里。
    **必须按属性访问 ``database.SessionLocal``**：数据集切换用的是原地改绑，
    按值导入的模块会静默继续写旧库（项目里为这件事踩过一次）。
    """
    with database.SessionLocal() as session:
        site = session.get(OfficialSite, site_id)
        run = session.get(OfficialCollectRun, run_id)
        if site is None or run is None:
            logger.warning("采集任务的站点或记录已不存在：site_id=%s run_id=%s", site_id, run_id)
            return
        try:
            http = default_http_factory(session)
            try:
                await collect_site(
                    session,
                    site,
                    http=http,
                    run=run,
                    max_jobs=max_jobs,
                    job_keywords=job_keywords,
                    checkpoint=runner.checkpoint_for(run_id),
                    on_progress=_progress_writer(session, run),
                )
            finally:
                await http.aclose()
        except asyncio.CancelledError:
            # 关闭时被取消：**运行记录不能停在"采集中"**，否则用户下次打开看到的是幽灵进度。
            _finish_as_stopped(session, run)
            raise
        except Exception:  # noqa: BLE001 - 后台任务不能让异常逃逸到事件循环
            logger.exception("官网采集后台任务失败：run_id=%s", run_id)
            _finish_as_failed(session, run)


def _progress_writer(
    db: Session, run: OfficialCollectRun
) -> Callable[[OfficialCollectReport], None]:
    """把进度写回运行记录。

    **刻意每页提交一次**：不提交的话前端在整个采集期间只能看到"采集中"，而多页站点可能跑
    好几分钟——用户既不知道进展，也不知道它是不是卡住了。
    """

    def write(report: OfficialCollectReport) -> None:
        run.pages = report.pages
        run.collected = report.collected
        run.stored = report.stored
        run.skipped = report.skipped
        run.total_hint = report.total_hint
        db.commit()

    return write


def _finish_as_stopped(db: Session, run: OfficialCollectRun) -> None:
    run.status = RUN_STOPPED
    run.headline = run.headline or "采集被停止"
    run.finished_at = utcnow()
    db.commit()


def _finish_as_failed(db: Session, run: OfficialCollectRun) -> None:
    run.status = RUN_FAILED
    run.error = run.error or "采集过程中发生内部错误"
    run.finished_at = utcnow()
    db.commit()


def fail_orphaned_runs(db: Session) -> int:
    """应用重启后，把仍停留在"进行中"的采集标记为失败，避免出现幽灵进度。

    与投递台的同名清理是同一个理由：运行记录说"采集中"，而那个任务早就随进程消失了。
    """
    orphans = (
        db.query(OfficialCollectRun)
        .filter(OfficialCollectRun.status == RUN_RUNNING)
        .all()
    )
    for run in orphans:
        run.status = RUN_FAILED
        run.error = "应用重启，采集已中断，请重新开始"
        run.finished_at = utcnow()
    if orphans:
        db.commit()
        logger.warning("清理了 %s 条中断的官网采集记录", len(orphans))
    return len(orphans)


async def verify_run(
    db: Session,
    run_id: int,
    *,
    http: FeedHttp,
) -> OfficialCollectRun:
    """核实这次采集的待核实候选，并**用原来的账目重算结论**。

    这是把「待核实」变成硬结论的唯一途径：

    - 核实出**仍在招**的 → 确凿的漏抓，结论升级为"已确认不全"；
    - 差额**全部**核实为已下架 → 差额被完全解释掉，结论升级为"已确认为全量"；
    - 还有没核实的 → 结论停在"无法确认"。

    重算走的是同一个 ``reconcile``，输入取自运行记录里存下的那一份——**不在别处再写一遍
    判定逻辑**，否则两处必然漂移，而漂移的表现是"同一份账目，两次算出不同结论"。
    """
    run = get_run(db, run_id)
    detail = dict(run.reconcile_detail or {})
    candidates = [str(url) for url in (detail.get("candidates") or []) if str(url).strip()]
    if not candidates:
        raise OfficialError("这次采集没有待核实的地址")

    gate = RobotsAwareHttp.wrap(http)
    results = await verify_all(gate, candidates)

    verified_gone = frozenset(item.url for item in results if item.state == VERIFIED_GONE)
    verified_live = frozenset(item.url for item in results if item.state == VERIFIED_LIVE)

    data = input_from_dict(detail.get("input") or {})
    data.verified_gone = frozenset(data.verified_gone) | verified_gone
    data.verified_live = frozenset(data.verified_live) | verified_live
    report = reconcile(data)

    run.verdict = report.verdict
    run.evidence = report.evidence
    run.headline = report.headline
    run.missing = report.missing
    detail["layers"] = list(report.layers)
    detail["candidates"] = list(report.candidates)
    detail["input"] = input_to_dict(data)
    detail["verifications"] = [
        {"url": item.url, "state": item.state, "label": VERIFY_STATE_LABELS[item.state],
         "detail": item.detail}
        for item in results
    ]
    run.reconcile_detail = detail
    db.commit()
    return run


def _noop_checkpoint() -> None:
    """阶段 0 的采集不可中断。真正的暂停/停止随前端一起接入（见实施路线阶段 1）。"""


async def _sitemap_expectations(
    http: FeedHttp, robots: RobotsDecision, target: str
) -> tuple[frozenset[str], str]:
    """取站点地图并筛出"可能是岗位详情页"的地址，作为集合对账的可枚举全集。

    筛选用**站点自身的主机**：站点地图列的是该站点自己的页面。不能用适配器声明的接口域名
    （``boards-api.greenhouse.io``）——那是另一个域名，拿它当基准一个都筛不出来。

    **适可而止**：声明了站点地图却取不到、或被截断时返回空集合并把原因带回去。空集合会让
    集合对账整层不参与，这是对的：拿一份不完整的全集去比对，差额会凭空多出一堆，
    比对不了更糟。
    """
    if not robots.sitemaps:
        return frozenset(), ""

    result = await fetch_sitemap_urls(http, robots.sitemaps)
    if not result.usable:
        return frozenset(), result.detail

    host = domain_of(target)
    if not host:
        return frozenset(), result.detail

    matched = frozenset(
        url for url in result.urls if looks_like_job_url(url, page_host=host)
    )
    return matched, f"{result.detail}，其中 {len(matched)} 个像是岗位页"


def _record_refused_run(
    db: Session, site: OfficialSite, robots: RobotsDecision, target: str
) -> OfficialCollectRun:
    """robots 拒绝时也落一条记录：这是结论，不是错误。"""
    run = OfficialCollectRun(site_id=site.id, status=RUN_DONE, started_at=utcnow())
    db.add(run)
    _finish_as_refused(db, run, robots, target)
    return run


def _finish_as_refused(
    db: Session, run: OfficialCollectRun, robots: RobotsDecision, target: str
) -> None:
    """把一条运行记录收尾成"被 robots 拒绝"。

    **点名是哪个主机拒绝的**：用户据此才知道下一步该做什么（换一个招聘页地址重试），
    而"站点不允许采集"这种不带主机的说法只会让人无从下手。
    """
    host = domain_of(target) or target
    run.status = RUN_DONE
    run.finished_at = utcnow()
    # 一条都没抓到，所以结论只能是"无法确认"——用 0 条去宣称"已确认为全量"会是最坏的结果。
    run.verdict = VERDICT_UNKNOWN
    run.headline = f"未采集：{host} 的 robots.txt 不允许采集（{robots.detail}）"
    # 记成"拒绝访问"而不是留空：报告页要能一眼看出这次没抓的原因是站点不允许。
    run.blocks = [BLOCK_FORBIDDEN]
    run.reconcile_detail = {"robots": {"allowed": robots.allowed, "detail": robots.detail}}
    db.commit()


def _store_memory(site: OfficialSite, report: OfficialCollectReport) -> None:
    """把这一站攒下的抽取知识写回源记录。**只在真的改了时才写**，免得每次采集都写一遍。

    配方版本号跟着走：站点改版后归纳出的新配方会换一个版本，旧版本在运行记录里留痕，
    排查"为什么突然读不出来了"时能对上是哪一次改的。
    """
    memory = report.memory
    if memory is None or not memory.changed:
        return
    site.recipe = memory.to_blob()
    # 版本号取自**配方**自己的 schema（不是外面那层记忆格式的）：站点改版后重新归纳出的配方
    # 会在这一级换版本，排查"为什么突然读不出来了"时能对上是哪一次改的。
    site.recipe_version = f"v{RECIPE_SCHEMA}"


def _apply_report(
    run: OfficialCollectRun, report: OfficialCollectReport, *, sitemap_detail: str = ""
) -> None:
    """把采集账目与对账结论写进运行记录。"""
    run.pages = report.pages
    run.collected = report.collected
    run.stored = report.stored
    run.skipped = report.skipped
    run.detail_missing = report.detail_missing
    run.total_hint = report.total_hint
    run.blocks = list(report.blocks)
    # 模型用量。**用户自付 key，这一项必须落库**——不然他只能去翻服务商的账单。
    run.llm_calls = report.llm_calls
    if report.reconcile is not None:
        reconcile = report.reconcile
        run.verdict = reconcile.verdict
        run.evidence = reconcile.evidence
        run.headline = reconcile.headline
        run.missing = reconcile.missing
        layers = list(reconcile.layers)
        if sitemap_detail:
            # 站点地图这一层的取回结果要留痕：没参与对账时，用户得知道是"站点没声明"、
            # "取不到"还是"被截断"，否则报告里会缺一层而没有解释。
            layers.append({"layer": "sitemap", "label": "站点地图", "detail": sitemap_detail})
        run.reconcile_detail = {
            "basis": reconcile.basis,
            "layers": layers,
            "candidates": list(reconcile.candidates),
            # 对账**用的输入**原样存下来：存活校验之后要重算结论，而重算必须用原来的账目。
            # 从运行记录反推（"终止状态是 limit，所以 reached_page_limit 应该是 True"）
            # 既脆弱又会悄悄偏离原值——而偏差会让同一份账目算出两个不同结论。
            "input": input_to_dict(report.reconcile_input) if report.reconcile_input else {},
            "termination": (
                {"state": reconcile.termination.state, "detail": reconcile.termination.detail}
                if reconcile.termination
                else None
            ),
            "stopped_reason": report.stopped_reason,
            "job_filter": report.job_filter,
            "collected_jobs": list(report.collected_jobs),
        }
    # 「这一页是怎么读出来的」逐页留痕。**不放在上面的对账分支里**：对账结论可能没有
    # （被 robots 拒绝、或采集在算账之前就失败了），而"这次花了多少次模型调用"与对账毫无关系
    # ——用户自付 key，他有权知道钱花在哪、为什么没省下来（配方没归纳成功之类）。
    detail = dict(run.reconcile_detail or {})
    # robots 拒绝或异常没有 reconcile 分支，也要保留这次采集的筛选条件与岗位快照字段。
    detail.setdefault("job_filter", report.job_filter)
    detail.setdefault("collected_jobs", list(report.collected_jobs))
    detail["extraction"] = {
        "methods": list(report.extraction_notes),
        "llm_calls": report.llm_calls,
        "recipes_learned": report.recipes_learned,
        # 跳过了多少个更深的地址。它**不改结论**（次级导航不是岗位），但报告里要能回答
        # "为什么这次只翻了这么几页"——否则用户只能猜。
        "deep_links_skipped": report.deep_links_skipped,
    }
    run.reconcile_detail = detail
    if report.stopped_reason:
        run.error = report.stopped_reason[:500]


# ===== 源的增删查 =====


def create_site(
    db: Session,
    *,
    company: str,
    homepage_url: str = "",
    careers_url: str = "",
) -> OfficialSite:
    """建一条源记录（**不探测**）。探测是异步的，由调用方拿到 id 后再发起。"""
    name = (company or "").strip()
    if not name:
        raise OfficialError("请填写公司名称")
    if not (homepage_url.strip() or careers_url.strip()):
        raise OfficialError("请至少填写官网地址或招聘页地址")
    if db.query(OfficialSite).filter(OfficialSite.company == name).first() is not None:
        raise OfficialError(f"「{name}」已经在列表里了")

    site = OfficialSite(
        company=name[:128],
        homepage_url=homepage_url.strip()[:512],
        careers_url=careers_url.strip()[:512],
    )
    db.add(site)
    db.commit()
    db.refresh(site)
    return site


def update_site(
    db: Session,
    site_id: int,
    *,
    company: str,
    homepage_url: str = "",
    careers_url: str = "",
) -> OfficialSite:
    """修改源的用户输入；地址变化时清掉旧探测结果，避免沿用旧端点。"""
    site = get_site(db, site_id)
    name = (company or "").strip()
    homepage = (homepage_url or "").strip()
    careers = (careers_url or "").strip()
    if not name:
        raise OfficialError("请填写公司名称")
    if not (homepage or careers):
        raise OfficialError("请至少填写官网地址或招聘页地址")
    duplicate = (
        db.query(OfficialSite)
        .filter(OfficialSite.company == name, OfficialSite.id != site.id)
        .first()
    )
    if duplicate is not None:
        raise OfficialError(f"「{name}」已经在列表里了")

    urls_changed = site.homepage_url != homepage or site.careers_url != careers
    site.company = name[:128]
    site.homepage_url = homepage[:512]
    site.careers_url = careers[:512]
    if urls_changed:
        # 探测结果绑定的是旧地址；不清掉会让用户在重新探测前仍能点到旧端点。
        site.source_kind = ""
        site.endpoint = ""
        site.params = {}
        site.confidence = ""
        site.probe_evidence = ""
        site.robots_allowed = None
        site.robots_detail = ""
        site.crawl_delay_seconds = None
        site.last_probed_at = None
        site.recipe_version = ""
        site.recipe = {}
    db.commit()
    db.refresh(site)
    return site


def list_sites(db: Session, *, enabled_only: bool = False) -> list[OfficialSite]:
    query = db.query(OfficialSite)
    if enabled_only:
        query = query.filter(OfficialSite.enabled.is_(True))
    return query.order_by(OfficialSite.created_at.desc()).all()


def get_site(db: Session, site_id: int) -> OfficialSite:
    site = db.get(OfficialSite, site_id)
    if site is None:
        raise OfficialNotFound("这家公司不在列表里")
    return site


def set_enabled(db: Session, site: OfficialSite, enabled: bool) -> OfficialSite:
    site.enabled = bool(enabled)
    db.commit()
    return site


def delete_site(db: Session, site_id: int) -> None:
    """删除源，连带它的采集记录与计数趋势（外键 CASCADE）。"""
    site = get_site(db, site_id)
    db.delete(site)
    db.commit()


# ===== 运行记录的读取 =====


def list_runs(db: Session, *, site_id: int | None = None, limit: int = 50) -> list[OfficialCollectRun]:
    """最近的运行记录在前。

    **次键是 ``id``**，不是可有可无的：Windows 上 ``datetime.now`` 的分辨率约 15 毫秒，
    同一瞬间建的两条记录会拿到**完全相同**的 ``started_at``，只按时间排的话顺序由数据库
    自行决定——表现是"偶尔两次的顺序反过来"（本仓库的一条用例因此偶发失败）。
    产品侧同样受影响：同一秒内的两次采集在列表里会乱序。
    """
    query = db.query(OfficialCollectRun)
    if site_id is not None:
        query = query.filter(OfficialCollectRun.site_id == site_id)
    return (
        query.order_by(OfficialCollectRun.started_at.desc(), OfficialCollectRun.id.desc())
        .limit(limit)
        .all()
    )


def get_run(db: Session, run_id: int) -> OfficialCollectRun:
    run = db.get(OfficialCollectRun, run_id)
    if run is None:
        raise OfficialNotFound("找不到这次采集记录")
    return run


def trend_for(db: Session, site_id: int, *, limit: int = 30) -> list[int]:
    """该源最近若干次的岗位计数（由旧到新）。

    **只包含"有效测量"**：被阻断、被 robots 拒绝、停止、失败的那些不算——它们的 0 是
    "我们没拿到"，不是"这家公司没有岗位"。把它们混进基线会把基线越拉越低，最终掩盖掉一次
    真实的掉量，而那正是趋势离群要发现的东西。
    """
    rows = (
        db.query(OfficialCollectRun)
        .filter(OfficialCollectRun.site_id == site_id)
        .order_by(OfficialCollectRun.id.desc())
        .limit(limit)
        .all()
    )
    return measured_counts(list(reversed(rows)))


def trend_signal_for(db: Session, run: OfficialCollectRun, *, history: int = 30) -> TrendSignal:
    """这次采集相对**这家公司此前**的基线，算不算异常。

    历史取 ``id`` 小于本次的那些（行是按创建顺序自增的，而 ``start_collection`` 先建行再起
    任务，所以 id 顺序就是开始顺序）。用 ``started_at`` 反而会在同一秒内的两次采集上并列，
    让"此前"变得不确定。

    **不改写任何结论**：它只是一条提醒，不参与 ``reconcile``——条数下降既可能是我们漏抓，
    也可能是公司真的在缩减招聘，只看条数分不出来（见 ``trend`` 的模块说明）。
    """
    prior = (
        db.query(OfficialCollectRun)
        .filter(OfficialCollectRun.site_id == run.site_id)
        .filter(OfficialCollectRun.id < run.id)
        .order_by(OfficialCollectRun.id.desc())
        .limit(history)
        .all()
    )
    return compare_trend(
        measured_counts(list(reversed(prior))),
        run.collected,
        measured=is_measurement(run),
    )


__all__ = [
    "HOMEPAGE_HTML_LIMIT",
    "OfficialError",
    "OfficialNotFound",
    "SiteProbeResult",
    "collect_site",
    "create_site",
    "delete_site",
    "default_browser_client",
    "default_http_factory",
    "domain_of",
    "fail_orphaned_runs",
    "get_run",
    "get_site",
    "list_runs",
    "list_sites",
    "probe_and_store",
    "request_stop",
    "set_enabled",
    "start_collection",
    "trend_for",
    "trend_signal_for",
    "verify_run",
]
