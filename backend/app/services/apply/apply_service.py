"""投递台业务逻辑：配置、队列、准入、简历/招呼语解析、回写与记录。

设计要点（决定它为什么长这样）：

- **准入闸门只认一处**：能不能自动投、要不要逐条确认，全部通过 ``models.apply``
  的 ``admission_of`` / ``requires_confirmation`` 判断，本模块**不再另写一份**映射。
- **队列去重是第一道闸**：同一岗位在队列里只能有一条（数据库唯一约束 + 这里的显式 409）。
- **记录只保存展示快照**，不含任何完整个人资料；招呼语按"记全文但截断到上限"处理。
"""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ...config import DEFAULT_BROWSER_PORT
from ...models.apply import (
    ADMISSION_BLOCK,
    ADMISSION_NEEDS_CONFIRM,
    ADMISSIONS,
    FAILURE_CATEGORY_LABELS,
    HARD_GATE_UNMET,
    HARD_GATES,
    QUEUE_STATUS_DONE,
    QUEUE_STATUS_PENDING,
    STOP_REASON_ERROR,
    TASK_KIND_APPLY,
    TASK_KIND_COLLECT,
    TASK_STATUS_BREAKER_PAUSED,
    TASK_STATUS_FAILED,
    TASK_STATUS_PAUSED,
    TASK_STATUS_PENDING,
    TASK_STATUS_RUNNING,
    ApplyQueueItem,
    ApplyTask,
    ApplyTaskItem,
    JobMatchAnalysis,
)
from ...models.job import JOB_STATUS_APPLIED, JOB_STATUS_OPEN, Job
from ...models.profile import utcnow
from ...models.resume import ResumeRecord
from .. import trash
from ...models.setting import AppSetting
from ...schemas.apply import (
    ApplyConfigIn,
    ApplyConfigOut,
    ApplyQueueItemOut,
    ApplyRecordOut,
    ApplyTaskCreate,
    BrowserStatusOut,
    CollectConfigIn,
    CollectConfigOut,
    GREETING_RECORD_MAX_CHARS,
    MAX_BACKFILL_JOBS,
    SiteListOut,
    SiteOptionOut,
)
from ...schemas.job_match import JobMatchResult
from ..browser.browser_manager import BrowserError, BrowserManager, BrowserStatus
from ..browser.cdp_client import CdpError
from ..job_match import match_requires_confirmation
from ..profile_service import get_profile_detail
from ..sites.base import SiteAdapter
from ..sites.registry import get_registry

logger = logging.getLogger(__name__)

APPLY_CONFIG_KEY = "apply_config"
COLLECT_CONFIG_KEY = "collect_config"

# 视为"任务仍在进行中"的状态集合（用于"当前任务"查询与启动前冲突判断）。
ACTIVE_TASK_STATUSES = (
    TASK_STATUS_PENDING,
    TASK_STATUS_RUNNING,
    TASK_STATUS_PAUSED,
    TASK_STATUS_BREAKER_PAUSED,
)


class ApplyServiceError(Exception):
    """业务层对外错误：``status_code`` 供路由层直接映射，``detail`` 为中文（可为结构化 dict）。"""

    def __init__(self, detail: str | dict[str, Any], status_code: int = 400) -> None:
        message = detail if isinstance(detail, str) else str(detail.get("message", "请求无法完成"))
        super().__init__(message)
        self.detail = detail
        self.status_code = status_code


class ApplyBadRequest(ApplyServiceError):
    def __init__(self, detail: str | dict[str, Any]) -> None:
        super().__init__(detail, 400)


class ApplyNotFound(ApplyServiceError):
    def __init__(self, detail: str | dict[str, Any]) -> None:
        super().__init__(detail, 404)


class ApplyConflict(ApplyServiceError):
    def __init__(self, detail: str | dict[str, Any]) -> None:
        super().__init__(detail, 409)


def _clip_greeting(value: str) -> str:
    """招呼语落库前截断到上限（记录用户写给 HR 的全文，但不让单条无限增长）。"""
    text = (value or "").strip()
    return text[:GREETING_RECORD_MAX_CHARS]


# ===== 配置存取（app_setting 键值，脏数据退回默认）=====


def get_apply_config(db: Session) -> ApplyConfigIn:
    row = db.get(AppSetting, APPLY_CONFIG_KEY)
    if row is None:
        return ApplyConfigIn()
    try:
        return ApplyConfigIn.model_validate(json.loads(row.value))
    except (json.JSONDecodeError, ValidationError):
        logger.warning("投递配置数据损坏，已重置为默认值")
        return ApplyConfigIn()


def save_apply_config(db: Session, config: ApplyConfigIn) -> ApplyConfigIn:
    _write_setting(db, APPLY_CONFIG_KEY, config.model_dump())
    return config


def get_collect_config(db: Session) -> CollectConfigIn:
    row = db.get(AppSetting, COLLECT_CONFIG_KEY)
    if row is None:
        return CollectConfigIn()
    try:
        return CollectConfigIn.model_validate(json.loads(row.value))
    except (json.JSONDecodeError, ValidationError):
        logger.warning("采集配置数据损坏，已重置为默认值")
        return CollectConfigIn()


def save_collect_config(db: Session, config: CollectConfigIn) -> CollectConfigIn:
    _write_setting(db, COLLECT_CONFIG_KEY, config.model_dump())
    return config


def _write_setting(db: Session, key: str, payload: dict[str, Any]) -> None:
    row = db.get(AppSetting, key)
    serialized = json.dumps(payload, ensure_ascii=False)
    if row is None:
        db.add(AppSetting(key=key, value=serialized))
    else:
        row.value = serialized
    db.commit()


def config_out(config: ApplyConfigIn) -> ApplyConfigOut:
    """当前生效值 + 出厂默认值回显（前端据此显示"当前生效/默认"）。"""
    return ApplyConfigOut(**config.model_dump(), defaults=ApplyConfigIn())


def collect_config_out(config: CollectConfigIn) -> CollectConfigOut:
    return CollectConfigOut(**config.model_dump(), defaults=CollectConfigIn())


# ===== 匹配结论读取与准入 =====


def latest_match(db: Session, job_id: int | None) -> JobMatchAnalysis | None:
    if job_id is None:
        return None
    return (
        db.query(JobMatchAnalysis)
        .filter(JobMatchAnalysis.job_id == job_id)
        .one_or_none()
    )


def _admission_of_match(match: JobMatchAnalysis) -> str | None:
    result = match.result if isinstance(match.result, dict) else {}
    admission = result.get("admission")
    if admission in ADMISSIONS:
        return admission
    # 结果里没有可用 admission 时，退回按硬门槛/需确认字段推断（保守）。
    if match.hard_gate == HARD_GATE_UNMET:
        return ADMISSION_BLOCK
    if match.requires_confirm:
        return ADMISSION_NEEDS_CONFIRM
    # 读不出可用结论（空结果 / 未知取值 / hard_gate=unknown 且无标记）时返回 None。
    # **不要在这里兜底成 ADMISSION_ALLOW**：准入是安全闸门，未知方向必须是"需确认"，
    # 由 `_match_requires_confirm` 统一按需确认处理，绝不默认放行。
    return None


def _match_requires_confirm(match: JobMatchAnalysis) -> bool:
    """该岗位的匹配结论是否要求用户逐条确认（队列与展示共用同一判定）。

    保守规则：只要准入结论是「需确认」，或行上标记了 ``requires_confirm``，**或根本读不出
    可用结论**（``_admission_of_match`` 返回 ``None``），都必须逐条确认。最后一条是纵深防御——
    正常链路 ``persist_match`` 经 ``finalize_match_result`` 必然写合法值，但准入是安全闸门，
    任何一次回归或历史脏数据出现空结论时都不应被当成 ALLOWED 放行自动投递。
    """
    admission = _admission_of_match(match)
    return (
        admission is None
        or admission == ADMISSION_NEEDS_CONFIRM
        or bool(match.requires_confirm)
    )


def _blocking_gaps(result: dict[str, Any]) -> list[str]:
    """列出命中"真实缺口"的条件标签，供二次确认时展示缺口项。"""
    gaps: list[str] = []
    for section in ("hard_conditions", "core_abilities", "bonus_items"):
        items = result.get(section) if isinstance(result, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and item.get("status") == "real_gap":
                label = str(item.get("label", "")).strip()
                if label:
                    gaps.append(label)
    return gaps


# ===== 队列 =====


def _resume_title(db: Session, resume_id: int | None) -> str:
    if resume_id is None:
        return ""
    resume = db.get(ResumeRecord, resume_id)
    return resume.title if resume is not None else ""


def _queue_out(db: Session, item: ApplyQueueItem) -> ApplyQueueItemOut:
    match = latest_match(db, item.job_id)
    admission = _admission_of_match(match) if match is not None else None
    hard_gate = match.hard_gate if match is not None and match.hard_gate in HARD_GATES else None
    return ApplyQueueItemOut(
        id=item.id,
        job_id=item.job_id,
        job_title=item.job_title,
        company=item.company,
        resume_id=item.resume_id,
        resume_title=_resume_title(db, item.resume_id),
        greeting=item.greeting,
        sort_order=item.sort_order,
        status=item.status,
        admission=admission,
        hard_gate=hard_gate,
        requires_confirm=_match_requires_confirm(match) if match is not None else False,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def list_queue(db: Session) -> list[ApplyQueueItemOut]:
    items = (
        db.query(ApplyQueueItem)
        .order_by(ApplyQueueItem.sort_order, ApplyQueueItem.id)
        .all()
    )
    return [_queue_out(db, item) for item in items]


def add_to_queue(db: Session, request: Any) -> list[ApplyQueueItemOut]:
    """加入队列；命中真实缺口 / 未分析 / 重复时抛 409 并回传原因。

    整批要么全部成功、要么全部回滚：任一岗位不满足准入就中断，避免"加了一半"。
    """
    config = get_apply_config(db)
    next_order = (
        db.query(func.coalesce(func.max(ApplyQueueItem.sort_order), 0)).scalar() or 0
    )
    created: list[ApplyQueueItem] = []
    try:
        for entry in request.items:
            job = db.get(Job, entry.job_id)
            if job is None:
                raise ApplyNotFound(f"岗位不存在或已被删除：{entry.job_id}")
            existing = (
                db.query(ApplyQueueItem)
                .filter(ApplyQueueItem.job_id == job.id)
                .one_or_none()
            )
            if existing is not None:
                raise ApplyConflict(
                    {"message": f"「{job.title or '该岗位'}」已在投递队列中", "job_id": job.id}
                )
            match = latest_match(db, job.id)
            if match is None:
                if not entry.confirm_unanalyzed:
                    raise ApplyConflict(
                        {
                            "message": f"「{job.title or '该岗位'}」尚未做过匹配分析，确认继续加入？",
                            "job_id": job.id,
                            "unanalyzed": True,
                        }
                    )
            else:
                admission = _admission_of_match(match)
                if admission == ADMISSION_BLOCK and not (
                    entry.confirm_real_gap or config.confirm_real_gap
                ):
                    raise ApplyConflict(
                        {
                            "message": f"「{job.title or '该岗位'}」存在真实缺口，需确认后再加入",
                            "job_id": job.id,
                            "gaps": _blocking_gaps(match.result),
                        }
                    )
                # 「需确认」（needs_confirm）与「读不出可用结论」（admission is None，即空结果 /
                # 未知取值 / hard_gate=unknown 且无标记）**同级处理**：都不阻断入队，但该条目被视为
                # 未获授权自动投递——`_match_requires_confirm` 会据此算出 requires_confirm=True，
                # 投递前仍要用户逐条确认。未知/空结论绝不默认放行。
            next_order += 1
            queue_item = ApplyQueueItem(
                job_id=job.id,
                job_title=job.title,
                company=job.company,
                resume_id=entry.resume_id,
                greeting=_clip_greeting(entry.greeting),
                sort_order=next_order,
                status=QUEUE_STATUS_PENDING,
            )
            db.add(queue_item)
            created.append(queue_item)
        db.commit()
    except ApplyServiceError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    return [_queue_out(db, item) for item in created]


def update_queue_item(db: Session, item_id: int, payload: Any) -> ApplyQueueItemOut:
    item = db.get(ApplyQueueItem, item_id)
    if item is None:
        raise ApplyNotFound("投递队列条目不存在或已被移除")
    if payload.greeting is not None:
        item.greeting = _clip_greeting(payload.greeting)
    if payload.resume_id is not None:
        resume = db.get(ResumeRecord, payload.resume_id)
        if resume is None:
            raise ApplyNotFound("指定的简历不存在")
        item.resume_id = resume.id
    item.updated_at = utcnow()
    db.commit()
    db.refresh(item)
    return _queue_out(db, item)


def remove_queue_item(db: Session, item_id: int) -> None:
    item = db.get(ApplyQueueItem, item_id)
    if item is None:
        raise ApplyNotFound("投递队列条目不存在或已被移除")
    db.delete(item)
    db.commit()


def reorder_queue(db: Session, order: list[int]) -> list[ApplyQueueItemOut]:
    for index, item_id in enumerate(order):
        item = db.get(ApplyQueueItem, item_id)
        if item is None:
            continue
        item.sort_order = index
        item.updated_at = utcnow()
    db.commit()
    return list_queue(db)


# ===== 简历与招呼语解析 =====


def resolve_resume(db: Session, job_id: int | None, resume_id: int | None) -> ResumeRecord | None:
    """确定本岗位用哪份简历：显式指定优先，否则取该岗位最近一份岗位版简历。"""
    if resume_id is not None:
        return db.get(ResumeRecord, resume_id)
    if job_id is None:
        return None
    return (
        db.query(ResumeRecord)
        .filter(trash.live_only(ResumeRecord), ResumeRecord.job_id == job_id)
        .order_by(ResumeRecord.created_at.desc(), ResumeRecord.id.desc())
        .first()
    )


def resolve_greeting(item: ApplyQueueItem | None, config: ApplyConfigIn) -> str:
    """本岗位招呼语：条目值优先，为空则退回默认招呼语。"""
    if item is not None and item.greeting.strip():
        return item.greeting.strip()
    return config.default_greeting.strip()


def build_apply_data(db: Session, resume: ResumeRecord | None) -> dict[str, Any]:
    """构造供通用表单引擎映射的字段数据（只取投递必需的展示字段，不含完整资料）。"""
    profile = get_profile_detail(db)
    data: dict[str, Any] = {
        "name": profile.name,
        "phone": profile.phone,
        "email": profile.email,
        "city": profile.target_city or profile.city,
        "job_intent": profile.job_intent,
        "summary": profile.summary,
    }
    if resume is not None and resume.title:
        data["job_intent"] = data.get("job_intent") or resume.job_title
    return {key: value for key, value in data.items() if value}


# ===== 回写与记录 =====


def write_back_job_status(db: Session, job_id: int | None) -> None:
    """投递成功 → 岗位状态置为「已投递」；只在岗位仍是「开放中」时回写，不覆盖用户手改。"""
    if job_id is None:
        return
    job = db.get(Job, job_id)
    if job is not None and job.status in (JOB_STATUS_OPEN, ""):
        job.status = JOB_STATUS_APPLIED
        job.updated_at = utcnow()


def mark_queue_done(db: Session, job_id: int | None) -> None:
    if job_id is None:
        return
    item = db.query(ApplyQueueItem).filter(ApplyQueueItem.job_id == job_id).one_or_none()
    if item is not None:
        item.status = QUEUE_STATUS_DONE
        item.updated_at = utcnow()


def daily_success_count(db: Session) -> int:
    """今天（UTC 自然日）已成功的投递数——每日上限**只计成功投递**。"""
    start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        db.query(func.count(ApplyTaskItem.id))
        .filter(ApplyTaskItem.status == "success", ApplyTaskItem.finished_at >= start)
        .scalar()
        or 0
    )


def _record_out(item: ApplyTaskItem) -> ApplyRecordOut:
    return ApplyRecordOut(
        id=item.id,
        task_id=item.task_id,
        job_id=item.job_id,
        job_title=item.job_title,
        company=item.company,
        resume_title=item.resume_title,
        greeting=item.greeting,
        status=item.status,
        failure_category=item.failure_category,
        failure_label=FAILURE_CATEGORY_LABELS.get(item.failure_category, ""),
        failure_detail=item.failure_detail,
        attempt=item.attempt,
        created_at=item.created_at,
        finished_at=item.finished_at,
    )


def list_records(
    db: Session,
    *,
    keyword: str = "",
    result: str = "",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[ApplyRecordOut], int]:
    query = (
        db.query(ApplyTaskItem)
        .join(ApplyTask, ApplyTaskItem.task_id == ApplyTask.id)
        .filter(ApplyTask.kind == TASK_KIND_APPLY)
    )
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(ApplyTaskItem.job_title.like(like), ApplyTaskItem.company.like(like))
        )
    if result:
        query = query.filter(ApplyTaskItem.status == result)
    total = query.count()
    rows = (
        query.order_by(ApplyTaskItem.created_at.desc(), ApplyTaskItem.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return [_record_out(row) for row in rows], total


# ===== 任务查询与批次创建 =====


def current_task(db: Session, *, kind: str | None = None) -> ApplyTask | None:
    query = db.query(ApplyTask).filter(ApplyTask.status.in_(ACTIVE_TASK_STATUSES))
    if kind is not None:
        query = query.filter(ApplyTask.kind == kind)
    return query.order_by(ApplyTask.id.desc()).first()


def get_task_detail(db: Session, task_id: int) -> ApplyTask:
    task = db.get(ApplyTask, task_id)
    if task is None:
        raise ApplyNotFound("投递任务不存在或已被删除")
    return task


def _resolve_targets(db: Session, payload: ApplyTaskCreate) -> list[tuple[Job, ApplyQueueItem | None]]:
    targets: list[tuple[Job, ApplyQueueItem | None]] = []
    if payload.job_ids:
        for job_id in payload.job_ids:
            job = db.get(Job, job_id)
            if job is None:
                raise ApplyNotFound(f"岗位不存在或已被删除：{job_id}")
            queue_item = (
                db.query(ApplyQueueItem)
                .filter(ApplyQueueItem.job_id == job_id)
                .one_or_none()
            )
            if queue_item is None:
                # 直接指定（未走队列）的岗位仍须过准入：真实缺口必须先确认。
                # 读不出结论（admission is None）在这里与 needs_confirm 同级——两者都不在此阻断，
                # 真正的"未知不得默认放行"闸门在入队侧（add_to_queue / _match_requires_confirm）。
                match = latest_match(db, job_id)
                if match is not None and _admission_of_match(match) == ADMISSION_BLOCK:
                    raise ApplyConflict(
                        {
                            "message": f"「{job.title or '该岗位'}」存在真实缺口，请先在投递台加入队列并确认",
                            "job_id": job_id,
                            "gaps": _blocking_gaps(match.result),
                        }
                    )
            targets.append((job, queue_item))
    elif payload.use_queue:
        items = (
            db.query(ApplyQueueItem)
            .filter(ApplyQueueItem.status == QUEUE_STATUS_PENDING)
            .order_by(ApplyQueueItem.sort_order, ApplyQueueItem.id)
            .all()
        )
        for queue_item in items:
            job = db.get(Job, queue_item.job_id) if queue_item.job_id else None
            if job is None:
                continue  # 岗位已删除的队列条目直接跳过（快照仍在队列里可读）
            targets.append((job, queue_item))
    else:
        raise ApplyBadRequest("请先选择要投递的岗位（传入 job_ids 或 use_queue=true）")

    # 按岗位去重、保序。
    seen: set[int] = set()
    unique: list[tuple[Job, ApplyQueueItem | None]] = []
    for job, queue_item in targets:
        if job.id in seen:
            continue
        seen.add(job.id)
        unique.append((job, queue_item))
    return unique


def create_apply_task(db: Session, payload: ApplyTaskCreate) -> ApplyTask:
    """显式开始投递：建批次 + 逐条记录，再把批次交给单例运行器。"""
    from . import task_runner

    runner = task_runner.get_task_runner()
    if runner.is_running():
        raise ApplyConflict("已有任务正在进行中，请先停止或等待其完成")

    config = get_apply_config(db)
    targets = _resolve_targets(db, payload)
    if not targets:
        raise ApplyBadRequest("队列为空或所选岗位无效，没有可投递的岗位")
    if daily_success_count(db) >= config.daily_limit:
        raise ApplyConflict(f"今日投递已达上限（{config.daily_limit}），请明天再试或调高上限")

    targets = targets[: config.per_task_limit]
    task = ApplyTask(
        kind=TASK_KIND_APPLY,
        status=TASK_STATUS_PENDING,
        total=len(targets),
        config=config.model_dump(),
    )
    db.add(task)
    db.flush()
    for index, (job, queue_item) in enumerate(targets):
        resume = resolve_resume(
            db, job.id, queue_item.resume_id if queue_item is not None else None
        )
        db.add(
            ApplyTaskItem(
                task_id=task.id,
                job_id=job.id,
                job_title=job.title,
                company=job.company,
                resume_id=resume.id if resume is not None else None,
                resume_title=resume.title if resume is not None else "",
                greeting=_clip_greeting(queue_item.greeting) if queue_item is not None else "",
                sort_order=index,
            )
        )
    db.commit()
    db.refresh(task)
    runner.start(task.id)
    return task


def create_collect_task(db: Session, *, save_site_samples: bool = False) -> ApplyTask:
    """显式开始采集：用已保存的采集配置建一个 kind=collect 批次。

    ``save_site_samples`` 是**每次采集一次性**的开关（是否保存本次抓到的站点原文）。
    它不属于采集配置，所以刻意**不放进** ``CollectConfigIn``（那是 ``extra="forbid"`` 的公开
    配置模型）；只有为真时才写进 ``task.config``，为假就不放这个键——保持旧任务的 config 形状
    不变（与 ``backfill_job_ids`` 同一套做法，见 ``task_runner._load_config`` 的 ``ignore``）。
    """
    from . import task_runner

    runner = task_runner.get_task_runner()
    if runner.is_running():
        raise ApplyConflict("已有任务正在进行中，请先停止或等待其完成")

    config = get_collect_config(db)
    if not config.keywords and not config.city.strip():
        raise ApplyBadRequest("请先设置采集关键词或城市后再开始采集")

    task_config = config.model_dump()
    if save_site_samples:
        task_config["save_site_samples"] = True

    task = ApplyTask(
        kind=TASK_KIND_COLLECT,
        status=TASK_STATUS_PENDING,
        total=config.per_task_limit,
        config=task_config,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    runner.start(task.id)
    return task


def create_backfill_task(db: Session, job_ids: Sequence[int]) -> ApplyTask:
    """按岗位 id 只补抓详情，修"当年采集时详情没抓到、JD 为空"的历史数据。

    复用采集任务的一整套机制（浏览器会话、详情抓取、限速、暂停/停止、进度显示），所以它仍然是一个
    ``kind=collect`` 批次，只是把"这一批岗位从哪儿来"从关键词翻页换成用户点名，写进
    ``config['backfill_job_ids']``。
    """
    from . import task_runner

    runner = task_runner.get_task_runner()
    if runner.is_running():
        raise ApplyConflict("已有任务正在进行中，请先停止或等待其完成")

    # 去重并保序：用户可能重复勾选，前端分批提交时也可能出现重复 id。
    ids = list(dict.fromkeys(int(job_id) for job_id in job_ids))
    if not ids:
        raise ApplyBadRequest("请先选择要补齐详情的岗位")
    if len(ids) > MAX_BACKFILL_JOBS:
        raise ApplyBadRequest(
            f"一次最多补齐 {MAX_BACKFILL_JOBS} 个岗位的详情（当前选了 {len(ids)} 个）："
            "补详情要逐个打开岗位页面，很慢，请分批操作。"
        )

    # 这里**不**预先过滤"描述为空的岗位"——是否真的需要补由采集器的 ``_backfill`` 统一判断
    # （已有描述 / 没有投递链接 / 在回收站里都会跳过）。两处各判一次必然漂移。
    config = get_collect_config(db)
    task = ApplyTask(
        kind=TASK_KIND_COLLECT,
        status=TASK_STATUS_PENDING,
        total=len(ids),
        config={**config.model_dump(), "backfill_job_ids": ids},
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    runner.start(task.id)
    return task


def fail_orphaned_tasks(db: Session) -> int:
    """应用重启后，把仍停留在"进行中"的任务标记为失败，避免出现"幽灵进度"。"""
    orphans = db.query(ApplyTask).filter(ApplyTask.status.in_(ACTIVE_TASK_STATUSES)).all()
    for task in orphans:
        task.status = TASK_STATUS_FAILED
        task.stop_reason = STOP_REASON_ERROR
        task.message = "应用重启，任务已中断，请重新开始"
        task.finished_at = utcnow()
        task.current_step = "idle"
    if orphans:
        db.commit()
        logger.warning("清理了 %s 个中断的投递/采集任务", len(orphans))
    return len(orphans)


# ===== 当前站点（"当前招聘网站"概念的落点）=====


def current_site(db: Session) -> SiteAdapter | None:
    """当前选中的站点适配器。

    先按配置里的 ``site_key`` 精确取；取不到（配置为空 / 站点被移除）就回退到注册表里的
    第一个站点，保证界面与入口地址永远有一个可用值。
    """
    registry = get_registry()
    config = get_apply_config(db)
    adapter = registry.resolve(config.site_key)
    if adapter is not None:
        return adapter
    adapters = registry.all()
    return adapters[0] if adapters else None


def current_site_key(db: Session) -> str:
    adapter = current_site(db)
    return adapter.key if adapter is not None else ""


def _site_option_out(adapter: SiteAdapter) -> SiteOptionOut:
    return SiteOptionOut(
        key=adapter.key,
        display_name=adapter.display_name,
        host=adapter.hosts[0] if adapter.hosts else "",
        entry_url=adapter.entry_url,
        supports_collect=adapter.supports_collect,
        supports_apply=adapter.supports_apply,
    )


def list_sites(db: Session) -> SiteListOut:
    """已注册站点列表 + 当前选中项。

    前端据此展示"当前招聘网站"，**不把站点名写死在组件里**；将来后端注册表里多加一行，
    界面自动多出一个站点可选。
    """
    registry = get_registry()
    return SiteListOut(
        current=current_site_key(db),
        sites=[_site_option_out(adapter) for adapter in registry.all()],
    )


# ===== 投递专用浏览器（进程内单例，端口 / 浏览器选择 / 自定义路径共同决定是否重建）=====

_browser_lock = threading.Lock()
_browser_manager: BrowserManager | None = None
_browser_manager_key: tuple[Any, ...] | None = None


def _browser_cache_key(config: ApplyConfigIn) -> tuple[Any, ...]:
    """浏览器单例的缓存键：端口、浏览器选择、自定义路径任一变化都要重建。"""
    return (
        config.browser_port or DEFAULT_BROWSER_PORT,
        config.browser_choice,
        config.browser_path.strip(),
    )


def get_browser_manager(db: Session) -> BrowserManager:
    """按当前配置返回浏览器管理器单例；配置（端口 / 选择 / 路径）变更时先关旧实例再重建。"""
    global _browser_manager, _browser_manager_key
    config = get_apply_config(db)
    key = _browser_cache_key(config)
    port = key[0]
    with _browser_lock:
        if _browser_manager is None or _browser_manager_key != key:
            if _browser_manager is not None:
                _browser_manager.stop()
            _browser_manager = BrowserManager(
                port=port,
                browser_choice=config.browser_choice,
                browser_path=config.browser_path.strip() or None,
            )
            _browser_manager_key = key
        return _browser_manager


def default_entry_url(db: Session) -> str:
    """投递专用浏览器启动时要打开的**当前站点**入口地址。

    取当前站点的 ``entry_url``；当前站点没有入口地址时退化到"第一个有入口的站点"。
    取不到就返回空串，调用方会让窗口停在 about:blank，界面上仍可用「打开招聘网站」手动导航。
    """
    adapter = current_site(db)
    if adapter is not None and adapter.entry_url:
        return adapter.entry_url
    for candidate in get_registry().all():
        if candidate.entry_url:
            return candidate.entry_url
    return ""


def _browser_status_out(status: BrowserStatus, db: Session) -> BrowserStatusOut:
    """把浏览器状态快照转成对外 schema。字段只在这一处列，避免多个出口漏字段。"""
    return BrowserStatusOut(
        state=status.state,
        port=status.port,
        profile_dir=status.profile_dir,
        browser_path=status.browser_path,
        browser_name=status.browser_name,
        entry_url=default_entry_url(db),
        logged_in_hint=status.logged_in_hint,
    )


def browser_status(db: Session) -> BrowserStatusOut:
    manager = get_browser_manager(db)
    return _browser_status_out(manager.status(), db)


def start_browser(db: Session) -> BrowserStatusOut:
    manager = get_browser_manager(db)
    try:
        # 带上站点入口地址：只开 about:blank 的话用户面对空白窗口无从登录。
        status = manager.start(url=default_entry_url(db) or None)
    except BrowserError as exc:
        raise ApplyConflict(str(exc)) from exc
    return _browser_status_out(status, db)


def open_browser_url(db: Session) -> BrowserStatusOut:
    """在已启动的专用浏览器里打开站点入口地址。

    用户可能自己把标签页关掉或跳到了别处，这时不必重启浏览器，导航回去即可。
    """
    manager = get_browser_manager(db)
    url = default_entry_url(db)
    if not url:
        raise ApplyConflict("暂时没有可打开的招聘网站入口地址")
    try:
        manager.open_url(url)
    except (BrowserError, CdpError) as exc:
        raise ApplyConflict(str(exc)) from exc
    return _browser_status_out(manager.status(), db)


def stop_browser(db: Session) -> None:
    manager = get_browser_manager(db)
    manager.stop()


def reset_browser_manager() -> None:
    """测试用：清掉进程内浏览器单例，避免用例之间互相影响。"""
    global _browser_manager, _browser_manager_key
    with _browser_lock:
        if _browser_manager is not None:
            _browser_manager.stop()
        _browser_manager = None
        _browser_manager_key = None


# ===== 匹配结论持久化（供 job_match 服务与队列准入共用）=====


def persist_match(
    db: Session, job: Job, result: JobMatchResult, *, model: str = ""
) -> JobMatchAnalysis:
    """写入/覆盖某岗位最近一次匹配结论（job_id 唯一）。"""
    requires_confirm = match_requires_confirmation(result)
    row = (
        db.query(JobMatchAnalysis)
        .filter(JobMatchAnalysis.job_id == job.id)
        .one_or_none()
    )
    payload = result.model_dump()
    if row is None:
        row = JobMatchAnalysis(
            job_id=job.id,
            job_title=job.title,
            company=job.company,
            result=payload,
            hard_gate=result.hard_gate,
            requires_confirm=requires_confirm,
            model=model,
        )
        db.add(row)
    else:
        row.job_title = job.title
        row.company = job.company
        row.result = payload
        row.hard_gate = result.hard_gate
        row.requires_confirm = requires_confirm
        row.model = model
        row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return row


def delete_match(db: Session, job_id: int) -> None:
    row = latest_match(db, job_id)
    if row is not None:
        db.delete(row)
        db.commit()


__all__ = [
    "ACTIVE_TASK_STATUSES",
    "APPLY_CONFIG_KEY",
    "COLLECT_CONFIG_KEY",
    "ApplyBadRequest",
    "ApplyConflict",
    "ApplyNotFound",
    "ApplyServiceError",
    "add_to_queue",
    "browser_status",
    "build_apply_data",
    "collect_config_out",
    "config_out",
    "create_apply_task",
    "create_backfill_task",
    "create_collect_task",
    "current_site",
    "current_site_key",
    "current_task",
    "daily_success_count",
    "default_entry_url",
    "delete_match",
    "fail_orphaned_tasks",
    "get_apply_config",
    "get_browser_manager",
    "get_collect_config",
    "get_task_detail",
    "latest_match",
    "list_queue",
    "list_records",
    "list_sites",
    "mark_queue_done",
    "open_browser_url",
    "persist_match",
    "remove_queue_item",
    "reorder_queue",
    "reset_browser_manager",
    "resolve_greeting",
    "resolve_resume",
    "save_apply_config",
    "save_collect_config",
    "start_browser",
    "stop_browser",
    "update_queue_item",
    "write_back_job_status",
]
