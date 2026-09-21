"""岗位采集编排：翻页、去重、限速、可暂停，把结果**暂存**进备选岗位。

**采集不直接写岗位广场**：采集条件（关键词 + 城市）本来就宽，噪声是常态；直接入库的后果是
用户只能去岗位广场一条条删。所以采到的东西先落进「备选岗位」暂存区，由用户在投递台里
勾选后才导入。这条链路复用既有 ``candidate_job``，不新建概念。

为什么单独成模块：采集是"几步 CDP 调用 + 落库"的**站点无关流程**，站点特有的选择器
都在适配器里；这里只负责"翻页节奏、去重、别把自己搞崩"。

三条与任务运行器共享的纪律：
- 每一个 CDP 步骤前都调用 ``checkpoint()``（用户点停止要真的停得下来，暂停要真的等）；
- 去重判据**与候选导入共用同一份实现**（``job_service.find_by_job_identity``），两处各写
  一份必然漂移——症状是"采集说没采过、导入说重复"；
- 采集条件里**无法映射到站点查询参数**的部分（薪资/经验/学历…）要如实记录，
  供界面显示「未生效」，绝不静默忽略。
"""
from __future__ import annotations

import logging
import random
import time
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from sqlalchemy.orm import Session

from ...models.apply import FAILURE_CAPTCHA_REQUIRED, FAILURE_LOGIN_REQUIRED
from ...models.job import Job
from ...models.profile import utcnow
from ...schemas.apply import CollectConfigIn
from ...schemas.job import RECOGNITION_SOURCE_COLLECT
from .. import trash
from ..candidate_jobs import find_staged_candidate, stage_candidate_job
from ..job_service import find_job_by_identity, refresh_job_keywords
from ..sites.base import CollectQuery, FilterResolution, SearchResult, SiteAdapter, SiteFailure
from .collect_filters import FilterTally, evaluate_filters

logger = logging.getLogger(__name__)

# 采集来源标注。字面量定义在 ``schemas/job.py``（与读取白名单同一处），这里只是沿用旧名字，
# 避免"两个模块各写一遍字符串、改一处漏一处"——那个坑已经以 500 的形式发作过一次。
COLLECT_RECOGNITION_SOURCE = RECOGNITION_SOURCE_COLLECT
MAX_COLLECT_PAGES = 30


@dataclass
class CollectReport:
    """一次采集的统计结果。

    ``collected`` 是**已暂存**的候选数（不是"已进入岗位广场"）；``skipped`` 是重复数
    （岗位广场里已有，或暂存区里已有）。
    """

    collected: int = 0
    skipped: int = 0
    pages: int = 0
    # 按用户填的学历 / 经验 / 薪资**明确筛掉**的条数（判断不了的不算，它们被保留了）。
    filtered: int = 0
    # 其中"跳过"里有几条是因为岗位广场的**回收站**里已经有一条（用户之前删过）。
    skipped_trashed: int = 0
    # 搜索采集里"暂存了、但正文（JD）为空"的条数。这是**站点漂移唯一留下的痕迹**：能翻到
    # 列表却读不出详情时，任务本身仍然是"成功"的，不计这个数就完全看不见——历史上"8 条岗位
    # JD 全空"的事故就是这么发生的。补详情模式有自己的账目（backfilled / backfill_skipped），
    # 两者刻意不混用，否则会把"用户点名去补"的语义算进"正常采集"的漂移里。
    detail_missing: int = 0
    # 「补齐详情」模式：成功补到的条数，以及因为"已经有描述 / 在回收站里 / 没有链接"跳过的条数。
    backfilled: int = 0
    backfill_skipped: int = 0
    unmapped_conditions: list[str] = field(default_factory=list)


class Collector:
    """采集编排器（翻页 + 去重 + 限速 + 可暂停）。"""

    def __init__(self, *, max_pages: int = MAX_COLLECT_PAGES) -> None:
        self._max_pages = max_pages

    def run(
        self,
        *,
        session: Session,
        task: Any,
        client: Any,
        adapter: SiteAdapter,
        config: CollectConfigIn,
        checkpoint: Callable[[], None],
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        backfill_job_ids: Sequence[int] | None = None,
    ) -> CollectReport:
        """一次采集。``backfill_job_ids`` 非空时改成**只给这些岗位补抓详情**。

        两种模式共用同一套浏览器会话、详情抓取、限速与进度上报，区别只在"这一批岗位从哪儿来"：
        搜索模式从关键词翻页来，补详情模式由用户点名（用于修"当年采集时详情没抓到、JD 为空"的
        历史数据）。这样暂停/停止、进度显示、失败语义全都不用重写一遍。
        """
        report = CollectReport()
        limit = config.per_task_limit
        # 站点侧筛选：**整个批次只解析一次**——校验编码要读一次站点清单，逐页重复读没有意义。
        # 解析不出来（站点改版 / 清单读不到）时按"这次没筛"如实记账，绝不发未经校验的编码：
        # 旧编码在站点看来同样"合法"，发出去会静默筛错，比不筛更糟。
        site_filters = FilterResolution()
        if not backfill_job_ids:
            # **补详情模式不解析站点筛选**：它是按用户点名的岗位逐个打开详情，不走搜索，
            # 筛选条件在这里没有任何作用；照解析一遍就可能为它白开一次搜索页。
            try:
                site_filters = adapter.prepare_collect_filters(config.filters, client)
            except Exception:  # noqa: BLE001 - 读清单失败不该让整次采集失败
                logger.warning("解析站点筛选条件失败，本次不按站点条件筛选", exc_info=True)
                site_filters = FilterResolution(unapplied=list(config.filters or {}))
        query = CollectQuery(
            keywords=list(config.keywords),
            city=config.city,
            salary_min=config.salary_min,
            experience=config.experience,
            education=config.education,
            job_type=config.job_type,
            filters=dict(site_filters.params),
        )
        unmapped: set[str] = set()
        tally = FilterTally()
        # 本地筛选只对**适配器声明过**的条件生效。这份声明是有约束力的：没声明就说明该站点的
        # 接口不保证返回对应字段，硬筛会变成"凭缺失的字段做判断"——那正是要避免的误杀。
        declared = set(adapter.post_filter_conditions)

        if backfill_job_ids:
            self._backfill(
                session=session,
                task=task,
                client=client,
                adapter=adapter,
                config=config,
                checkpoint=checkpoint,
                sleeper=sleeper,
                clock=clock,
                job_ids=list(backfill_job_ids),
                report=report,
            )

        keywords = list(config.keywords) or [""]
        seen_results: set[tuple[str, str, str]] = set()
        for keyword_index, keyword in enumerate(keywords):
            if backfill_job_ids or report.collected >= limit:
                break
            page = 1
            while report.collected < limit and page <= self._max_pages:
                checkpoint()
                # 一次站点搜索只带一个关键词。这样适配器无须猜列表里的多个词应当如何组合，
                # 同时让每个用户配置的关键词都真正执行；只填城市时用一个空关键词跑一次。
                page_query = replace(query, keywords=[keyword], page=page)
                page_result = adapter.collect_search(client, page_query, page)
                report.pages += 1
                unmapped.update(page_result.unmapped_conditions)

                for result in page_result.results:
                    if report.collected >= limit:
                        break
                    checkpoint()
                    if not result.url:
                        continue
                    identity = (
                        result.url.strip(),
                        result.title.strip().casefold(),
                        result.company.strip().casefold(),
                    )
                    if identity in seen_results:
                        report.skipped += 1
                        continue
                    seen_results.add(identity)
                    known = self._already_known(session, result)
                    if known:
                        report.skipped += 1
                        if known == "trashed":
                            # 单独计数：这是"你之前删过它"，不是"早就在库里了"。
                            report.skipped_trashed += 1
                        continue
                    # 条件筛选放在抓详情**之前**：按列表字段就能判定的不符合项，没必要再为它
                    # 打开一次详情页（那是整个采集里最慢的一步）。
                    decision = evaluate_filters(
                        salary_min=query.salary_min if "薪资" in declared else None,
                        experience=query.experience if "经验" in declared else "",
                        education=query.education if "学历" in declared else "",
                        job_type=query.job_type if "岗位类型" in declared else "",
                        extra=result.extra,
                    )
                    tally.unapplied.update(decision.unapplied)
                    if not decision.keep:
                        report.filtered += 1
                        tally.filtered += 1
                        tally.reasons.update(decision.rejected_by)
                        continue
                    if decision.undecided:
                        # 岗位没给这个字段 → **保留**（判断不了就不误杀），但要记账。
                        tally.undecided.update(decision.undecided)
                        tally.undecided_count += 1
                    detail = self._fetch_detail(adapter, client, result.url)
                    if not str(detail.get("description") or "").strip():
                        # "应该是详情的地方没拿到详情"：详情正文（description）去空白后为空即计一条。
                        # 这是站点漂移的早期信号——列表字段还在、正文却读不出来了。
                        report.detail_missing += 1
                    self._stage_candidate(
                        session, adapter, result, detail, getattr(task, "id", None),
                        job_type=config.job_type,
                    )
                    report.collected += 1
                    self._update_task_progress(session, task, report)
                    self._pace(
                        config.interval_seconds,
                        config.interval_jitter_seconds,
                        checkpoint,
                        sleeper,
                        clock,
                    )

                if not page_result.has_next:
                    break
                page += 1
                self._pace(
                    config.interval_seconds, config.interval_jitter_seconds, checkpoint, sleeper, clock
                )
            if keyword_index < len(keywords) - 1 and report.collected < limit:
                self._pace(
                    config.interval_seconds, config.interval_jitter_seconds, checkpoint, sleeper, clock
                )

        report.unmapped_conditions = sorted(unmapped)
        # 筛选的账目写进 ``task.config``（不新增数据库列，与 ``unmapped_conditions`` 同一套做法）：
        # 「筛掉几条、按哪条筛的、有几条因为岗位没给字段而没能判断」都要给用户看到——
        # 只留一个"已暂存 N 个"会让人以为筛选生效了，而不知道实际筛掉了多少、漏了多少。
        summary: dict[str, Any] = {}
        if report.unmapped_conditions:
            summary["unmapped_conditions"] = report.unmapped_conditions
        if report.skipped_trashed:
            summary["skipped_trashed"] = report.skipped_trashed
        if report.backfilled or report.backfill_skipped:
            # 补详情的账目：补到几条、跳过几条（跳过包括"已经有描述"和"仍然抓不到"）。
            # 不给这两个数，用户看到"任务完成"却不知道到底补上没有。
            summary["backfilled"] = report.backfilled
            summary["backfill_skipped"] = report.backfill_skipped
        if not backfill_job_ids:
            # 只有**搜索采集**才写"详情缺失"这条账目：它是站点漂移的早期信号，站点健康度靠它
            # 识别"能采到列表却抓不到 JD"。补详情模式不写这个键（它走 backfilled/backfill_skipped），
            # 两套口径不混一起——否则用户一次"点名补详情"会把漂移计数搅乱。
            summary["detail_missing"] = report.detail_missing
        configured_filters = {
            "薪资": query.salary_min is not None,
            "经验": bool(query.experience),
            "学历": bool(query.education),
            "岗位类型": bool(query.job_type),
        }
        applied_filters = [
            condition
            for condition in adapter.post_filter_conditions
            if configured_filters.get(condition, False)
        ]
        if applied_filters:
            # 保留适配器声明的顺序（与界面上的字段顺序一致），不排序——排序会把
            # "薪资 / 经验 / 学历"变成按码位排的"学历 / 经验 / 薪资"，读起来别扭。
            summary["filter_applied"] = applied_filters
            summary["filtered_out"] = report.filtered
            summary["filter_reasons"] = sorted(tally.reasons)
            summary["filter_undecided"] = sorted(tally.undecided)
            summary["filter_undecided_count"] = tally.undecided_count
            summary["filter_unapplied"] = sorted(tally.unapplied)
        if site_filters.applied or site_filters.unapplied:
            # 站点侧筛选的账目：**生效了哪几条**（站点在接口侧就筛掉了，用户能少翻很多页）、
            # **哪几条没能生效**。后者必须说出来——用户选了「公司规模：1000人以上」却拿到
            # 各种规模的岗位，唯一能解释这件事的就是这句话。
            summary["site_filter_applied"] = list(site_filters.applied)
            summary["site_filter_unapplied"] = list(site_filters.unapplied)
        if summary:
            task.config = {**(task.config or {}), **summary}
        # 进度口径只能有一处实现（搜索算 collected、补详情算 backfilled）。此前收尾又按搜索口径
        # 写了一遍 processed/succeeded/skipped，补详情模式下会把 _update_task_progress 刚写入的
        # 值覆盖回 0——界面于是显示「已处理 0/N」。收尾统一走同一个方法（它自带 commit）。
        self._update_task_progress(session, task, report)
        return report

    # ===== 内部步骤 =====

    def _already_known(self, session: Session, result: SearchResult) -> str:
        """这个岗位是否已经有"正式岗位"或"待处理的候选"，以及**在不在回收站里**。

        返回 ``""``（没采过）/ ``"existing"``（库里已有）/ ``"trashed"``（在回收站里）。

        **两张表都要查**，少查一边都会出问题：只查岗位广场，暂存区里会堆出同一岗位的多条
        候选（用户勾一次就重复导入一次）；只查暂存区，则会把已经在岗位广场里的岗位重新捞回来，
        让用户以为采到了新东西。去重判据本身走 ``find_by_job_identity``——与后续"勾选导入"
        的重复判定是同一份实现，且**刻意不过滤软删除**。

        区分"在回收站里"是因为这两种"跳过"对用户的含义完全不同：一种是"早就在库里了"，
        另一种是"你之前删过它"——后者得说清楚，否则用户会以为删除没生效（或者以为工具坏了）。
        """
        identity = {"title": result.title, "company": result.company, "source_url": result.url}
        job = find_job_by_identity(session, **identity)
        if job is not None:
            return "trashed" if trash.is_deleted(job) else "existing"
        candidate = find_staged_candidate(session, **identity)
        if candidate is not None:
            # 候选岗位（暂存区）不在回收站范围内，is_deleted 恒为 False——这里照样走一遍，
            # 以后它进了回收站范围也不需要回来改。
            return "trashed" if trash.is_deleted(candidate) else "existing"
        return ""

    @staticmethod
    def _stage_candidate(
        session: Session,
        adapter: SiteAdapter,
        result: SearchResult,
        detail: dict[str, Any],
        task_id: int | None,
        job_type: str = "",
    ) -> None:
        """把一条采集结果放进暂存区（**不 commit**，由 ``run`` 统一提交）。

        详情抓失败时 ``detail`` 是空字典，这时仍然要暂存：标题 / 公司 / 城市 / 薪资 / 链接
        都已经拿到了，缺的只是 JD——把整条丢掉等于"因为拿不到详情就连岗位都不要了"。
        """
        stage_candidate_job(
            session,
            title=result.title or str(detail.get("job_title", "")),
            company=result.company or str(detail.get("company", "")),
            location=result.location,
            salary=result.salary,
            source_url=result.url,
            description=str(detail.get("description", "")),
            requirements=str(detail.get("requirements", "")),
            # 福利待遇 / 公司介绍这类第三段：不带上就会一路丢到导入之后，
            # 「其他招聘信息」永远是空的。
            additional_info=str(detail.get("additional_info", "")),
            source=result.source or adapter.display_name,
            task_id=task_id,
            job_type=job_type,
        )

    def _backfill(
        self,
        *,
        session: Session,
        task: Any,
        client: Any,
        adapter: SiteAdapter,
        config: CollectConfigIn,
        checkpoint: Callable[[], None],
        sleeper: Callable[[float], None],
        clock: Callable[[], float],
        job_ids: list[int],
        report: CollectReport,
    ) -> None:
        """给点名的岗位**只补抓详情**（修"当年采集时详情没抓到、JD 为空"的历史数据）。

        走的是与搜索流程同一套详情抓取与限速，所以暂停/停止语义完全一致。三条纪律：

        - **只补空**：已经有描述的岗位直接跳过。用户可能自己改过，补齐不该覆盖他的劳动成果；
        - **跳过回收站里的**（P5 的纪律：已删除的内容不该被后台动作碰到）；
        - **跳过没有链接的**：补详情的唯一入口就是那个地址。
        """
        for job_id in job_ids:
            checkpoint()
            job = trash.get_live(session, Job, job_id)
            if job is None or (job.description or "").strip() or not (job.source_url or "").strip():
                report.backfill_skipped += 1
                continue
            # 复用同一套详情抓取：只需要一个 URL。
            detail = self._fetch_detail(adapter, client, job.source_url)
            description = str(detail.get("description") or "").strip()
            if not description:
                # 仍然抓不到（页面改版 / 需要登录 / 岗位已下线）→ 如实算作"没补上"，
                # 不要把它计成成功、也不要写一个空值上去。
                report.backfill_skipped += 1
            else:
                job.description = description
                requirements = str(detail.get("requirements") or "").strip()
                if requirements:
                    job.requirements = requirements
                additional = str(detail.get("additional_info") or "").strip()
                if additional:
                    job.additional_info = additional
                # 技能标签是从 JD 解析出来的，补到正文后必须重算，否则搜索/匹配仍按空标签走。
                refresh_job_keywords(job)
                job.updated_at = utcnow()
                report.backfilled += 1
            self._update_task_progress(session, task, report)
            self._pace(
                config.interval_seconds, config.interval_jitter_seconds, checkpoint, sleeper, clock
            )

    def _fetch_detail(self, adapter: SiteAdapter, client: Any, url: str) -> dict[str, Any]:
        """按 URL 尽力抓取岗位详情；失败不影响主流程（列表信息已经够用）。

        为什么收 URL 字符串而不是 ``SearchResult``：搜索路径手里有完整的 ``SearchResult``，补详情
        路径只有一条 ``source_url``。以前为了复用签名，补详情那边临时拼了个 ``SearchResult(url=...)``
        ——而它的 ``title`` 是**无默认值的必填第一个字段**，于是补详情主路径每次必抛 ``TypeError``
        （会被运行器当成内部错误、整批置失败）。这里只用到 URL，就只收 URL：既不再依赖那个假对象，
        将来给 ``SearchResult`` 加必填字段也不会再波及这里。
        """
        fetch = getattr(adapter, "fetch_job_detail", None)
        if fetch is None:
            return {}
        try:
            return fetch(client, url) or {}
        except SiteFailure as exc:
            if exc.category in {FAILURE_LOGIN_REQUIRED, FAILURE_CAPTCHA_REQUIRED}:
                raise
            logger.warning("采集岗位详情失败（不影响主流程）：%s", exc.detail)
            return {}

    @staticmethod
    def _update_task_progress(session: Session, task: Any, report: CollectReport) -> None:
        # "干成了几件"在两种模式下是不同的字段：搜索采集算 collected，补详情算 backfilled。
        # 界面上统一显示成「已处理 N/M」，所以这里合成一个口径——否则补详情时进度会一直停在 0。
        done = report.collected + report.backfilled
        task.processed = done
        task.succeeded = done
        task.skipped = report.skipped + report.backfill_skipped
        session.commit()

    @staticmethod
    def _pace(
        interval: int,
        jitter: int,
        checkpoint: Callable[[], None],
        sleeper: Callable[[float], None],
        clock: Callable[[], float],
    ) -> None:
        total = max(0, interval)
        if jitter:
            total += random.uniform(0, jitter)
        end = clock() + total
        while True:
            checkpoint()
            remaining = end - clock()
            if remaining <= 0:
                return
            sleeper(min(0.2, remaining))


__all__ = ["COLLECT_RECOGNITION_SOURCE", "MAX_COLLECT_PAGES", "CollectReport", "Collector"]
