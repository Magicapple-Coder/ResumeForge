"""投递台与采集接口（prefix ``/api/apply`` 与 ``/api/collect``）。

薄路由：只做校验、调 service、返回 schema；错误统一 ``HTTPException(status, detail=中文)``。
执行采用**轮询模型**（前端按 1–2s 轮询任务详情），不用 SSE。
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.apply import (
    TASK_KIND_APPLY,
    TASK_KIND_COLLECT,
    ApplyQueueItem,
    ApplyTask,
    ApplyTaskItem,
)
from ..models.job import Job
from ..schemas.apply import (
    ApplyConfigIn,
    ApplyConfigOut,
    ApplyQueueAddRequest,
    ApplyQueueItemOut,
    ApplyQueueItemUpdate,
    ApplyQueueReorderRequest,
    ApplyRecordBatchOut,
    ApplyRecordOut,
    ApplyTaskCreate,
    ApplyTaskDetailOut,
    ApplyTaskItemOut,
    ApplyTaskOut,
    BrowserStatusOut,
    CollectBackfillIn,
    CollectConfigIn,
    CollectConfigOut,
    CollectFilterOptionsOut,
    CollectTaskCreateIn,
    GreetingPreviewOut,
    GreetingPreviewRequest,
    SiteHealthListOut,
    SiteListOut,
)
from ..schemas.common import Page
from ..services.apply import apply_service, task_runner
from ..services.job.job_match import generate_greeting, job_payload
from ..services.llm import create_provider
from ..services.llm.base import LLMError
from ..services.settings_service import get_llm_config
from ..services.site_health import site_health_overview

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/apply", tags=["apply"])
collect_router = APIRouter(prefix="/api/collect", tags=["collect"])


def _raise(exc: apply_service.ApplyServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


# ===== 配置 =====


@router.get("/config", response_model=ApplyConfigOut)
def get_apply_config(db: Session = Depends(get_db)):
    return apply_service.config_out(apply_service.get_apply_config(db))


@router.put("/config", response_model=ApplyConfigOut)
def update_apply_config(payload: ApplyConfigIn, db: Session = Depends(get_db)):
    return apply_service.config_out(apply_service.save_apply_config(db, payload))


@collect_router.get("/config", response_model=CollectConfigOut)
def get_collect_config(db: Session = Depends(get_db)):
    return apply_service.collect_config_out(apply_service.get_collect_config(db))


@collect_router.get("/filters", response_model=CollectFilterOptionsOut)
def collect_filters(db: Session = Depends(get_db)):
    """当前站点筛选栏的可选项（界面据此渲染下拉框）。

    **清单由站点提供，不是我们写死的**：写死的一份在站点改编码之后会静默筛错。
    每一项带 ``source`` 说明这份清单是从哪儿读来的（你的登录会话 / 全网通用 / 内置快照）。
    """
    return apply_service.collect_filter_options(db)


@collect_router.put("/config", response_model=CollectConfigOut)
def update_collect_config(payload: CollectConfigIn, db: Session = Depends(get_db)):
    return apply_service.collect_config_out(apply_service.save_collect_config(db, payload))


# ===== 招聘网站（当前站点）=====


@router.get("/sites", response_model=SiteListOut)
def list_sites(db: Session = Depends(get_db)):
    """已注册的招聘网站 + 当前选中项。

    界面据此展示"当前招聘网站"，不把站点名写死；以后新增站点只改后端注册表即可。
    """
    return apply_service.list_sites(db)


# ===== 投递专用浏览器 =====


@router.get("/browser/status", response_model=BrowserStatusOut)
def browser_status(db: Session = Depends(get_db)):
    return apply_service.browser_status(db)


@router.post("/browser/start", response_model=BrowserStatusOut)
def browser_start(open_entry: bool = True, db: Session = Depends(get_db)):
    """启动专用浏览器。

    ``open_entry=false`` 时**不打开任何站点页面**（停在空白页）。官网采集用它借浏览器
    当渲染引擎，默认打开站点入口页会让"只想采某公司官网"的用户莫名其妙跳出一个招聘网站；
    投递台保持默认，它要那个页面来登录。
    """
    try:
        return apply_service.start_browser(db, open_entry=open_entry)
    except apply_service.ApplyServiceError as exc:
        _raise(exc)


@router.post("/browser/open", response_model=BrowserStatusOut)
def browser_open(db: Session = Depends(get_db)):
    """在已启动的专用浏览器里重新打开招聘网站入口（标签页被关掉或跳走后使用）。"""
    try:
        return apply_service.open_browser_url(db)
    except apply_service.ApplyServiceError as exc:
        _raise(exc)


@router.post("/browser/refresh", response_model=BrowserStatusOut)
def browser_refresh(db: Session = Depends(get_db)):
    try:
        return apply_service.refresh_browser(db)
    except apply_service.ApplyServiceError as exc:
        _raise(exc)


@router.post("/browser/restart", response_model=BrowserStatusOut)
def browser_restart(db: Session = Depends(get_db)):
    try:
        return apply_service.restart_browser(db)
    except apply_service.ApplyServiceError as exc:
        _raise(exc)


@router.post("/browser/stop", status_code=204)
def browser_stop(db: Session = Depends(get_db)):
    """关闭专用浏览器。

    关不掉时（窗口是上一次运行留下的）必须给出可展示的中文提示，不能静默成功——
    与 /browser/start、/browser/open 用同一套错误映射。
    """
    try:
        apply_service.stop_browser(db)
    except apply_service.ApplyServiceError as exc:
        _raise(exc)
    return None


# ===== 投递队列 =====


@router.get("/queue", response_model=list[ApplyQueueItemOut])
def get_queue(db: Session = Depends(get_db)):
    return apply_service.list_queue(db)


@router.post("/queue", response_model=list[ApplyQueueItemOut])
def add_to_queue(payload: ApplyQueueAddRequest, db: Session = Depends(get_db)):
    try:
        return apply_service.add_to_queue(db, payload)
    except apply_service.ApplyServiceError as exc:
        _raise(exc)


@router.patch("/queue/reorder", response_model=list[ApplyQueueItemOut])
def reorder_queue(payload: ApplyQueueReorderRequest, db: Session = Depends(get_db)):
    return apply_service.reorder_queue(db, payload.order)


@router.patch("/queue/{item_id}", response_model=ApplyQueueItemOut)
def update_queue_item(item_id: int, payload: ApplyQueueItemUpdate, db: Session = Depends(get_db)):
    try:
        return apply_service.update_queue_item(db, item_id, payload)
    except apply_service.ApplyServiceError as exc:
        _raise(exc)


@router.delete("/queue/{item_id}", status_code=204)
def delete_queue_item(item_id: int, db: Session = Depends(get_db)):
    try:
        apply_service.remove_queue_item(db, item_id)
    except apply_service.ApplyServiceError as exc:
        _raise(exc)
    return None


# ===== 招呼语预览 =====


@router.post("/greeting/preview", response_model=GreetingPreviewOut)
async def greeting_preview(payload: GreetingPreviewRequest, db: Session = Depends(get_db)):
    job = db.get(Job, payload.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="岗位不存在或已被删除")
    config = apply_service.get_apply_config(db)

    if payload.item_id is not None:
        item = db.get(ApplyQueueItem, payload.item_id)
        if item is not None and item.greeting.strip():
            return GreetingPreviewOut(greeting=item.greeting.strip(), source="queue")

    llm = get_llm_config(db)
    if not (llm.base_url.strip() and llm.model.strip()):
        return GreetingPreviewOut(greeting=config.default_greeting.strip(), source="default")

    resume = apply_service.resolve_resume(db, job.id, None)
    resume_text = ""
    if resume is not None:
        resume_text = json.dumps(
            {"title": resume.title, "content": resume.content}, ensure_ascii=False
        )
    payload_data = job_payload(job)
    provider = create_provider(llm)
    db.close()
    try:
        greeting = await generate_greeting(provider, payload_data, resume_text)
        return GreetingPreviewOut(greeting=greeting, source="generated")
    except LLMError as exc:
        logger.warning("招呼语生成失败，回退默认招呼语：%s", exc)
    except Exception:  # noqa: BLE001 - 模型异常不能阻断预览
        logger.exception("招呼语生成发生内部错误，回退默认招呼语")
    return GreetingPreviewOut(greeting=config.default_greeting.strip(), source="default")


# ===== 执行批次（轮询模型）=====


def _task_detail(data: Session, task_id: int) -> ApplyTaskDetailOut:
    try:
        task = apply_service.get_task_detail(data, task_id)
    except apply_service.ApplyServiceError as exc:
        _raise(exc)
    items = (
        data.query(ApplyTaskItem)
        .filter(ApplyTaskItem.task_id == task_id)
        .order_by(ApplyTaskItem.sort_order, ApplyTaskItem.id)
        .all()
    )
    detail = ApplyTaskDetailOut.model_validate(task)
    detail.items = [ApplyTaskItemOut.model_validate(item) for item in items]
    return detail


def _control(db: Session, task_id: int, action: str) -> ApplyTaskOut:
    task = db.get(ApplyTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="投递任务不存在或已被删除")
    runner = task_runner.get_task_runner()
    try:
        getattr(runner, action)(task_id)
    except task_runner.TaskRunnerError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.expire_all()
    refreshed = db.get(ApplyTask, task_id)
    return ApplyTaskOut.model_validate(refreshed)


@router.post("/tasks", response_model=ApplyTaskOut)
def create_apply_task(payload: ApplyTaskCreate, db: Session = Depends(get_db)):
    try:
        task = apply_service.create_apply_task(db, payload)
    except apply_service.ApplyServiceError as exc:
        _raise(exc)
    except task_runner.TaskRunnerError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApplyTaskOut.model_validate(task)


@router.get("/tasks", response_model=list[ApplyTaskOut])
def list_tasks(
    kind: str = Query(default="", description="collect / apply；留空表示不限"),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """按时间**倒序**列出历史批次（默认最近 20 个）。

    「采集记录」靠它回看每次采集：采集是个"跑完就看不见过程"的动作，没有这份记录，
    用户第二天就不知道上次是按什么条件采的、采到了几条。
    """
    if kind and kind not in (TASK_KIND_APPLY, TASK_KIND_COLLECT):
        raise HTTPException(status_code=422, detail="无效的批次类型")
    query = db.query(ApplyTask)
    if kind:
        query = query.filter(ApplyTask.kind == kind)
    return query.order_by(ApplyTask.id.desc()).limit(limit).all()


@router.get("/tasks/current", response_model=ApplyTaskOut | None)
def current_task(
    kind: str = Query(default="", description="collect / apply；留空表示不限类型"),
    db: Session = Depends(get_db),
):
    """**正在进行中**的批次（投递或采集），没有则返回 null。

    默认**不限类型**是 2026-09-21 修的：以前这里写死 ``kind=apply``，于是采集批次在它眼里
    永远等于"没有任务"。后果不是少显示一行进度，而是两件体验直接失效——

    - 用户开始采集后切走再回到投递台，看不到正在跑的采集，进度面板是空的；
    - 全局完成通知（``useTaskCompletionWatcher``）靠它判断"这个批次刚才在跑"，采集批次
      从不出现，于是**采集跑完永远不弹通知**。

    两种批次本来就互斥（运行器同一时刻只跑一个），所以"任意类型"就是"那一个"。
    需要限定类型的调用方传 ``kind`` 即可。
    """
    if kind and kind not in (TASK_KIND_APPLY, TASK_KIND_COLLECT):
        raise HTTPException(status_code=422, detail="无效的批次类型")
    task = apply_service.current_task(db, kind=kind or None)
    return ApplyTaskOut.model_validate(task) if task is not None else None


@router.get("/tasks/{task_id}", response_model=ApplyTaskDetailOut)
def apply_task_detail(task_id: int, db: Session = Depends(get_db)):
    return _task_detail(db, task_id)


@router.post("/tasks/{task_id}/pause", response_model=ApplyTaskOut)
def pause_task(task_id: int, db: Session = Depends(get_db)):
    return _control(db, task_id, "pause")


@router.post("/tasks/{task_id}/resume", response_model=ApplyTaskOut)
def resume_task(task_id: int, db: Session = Depends(get_db)):
    return _control(db, task_id, "resume")


@router.post("/tasks/{task_id}/stop", response_model=ApplyTaskOut)
def stop_task(task_id: int, db: Session = Depends(get_db)):
    return _control(db, task_id, "stop")


# ===== 记录 =====


@router.get("/records", response_model=Page[ApplyRecordOut])
def list_records(
    keyword: str = Query(default=""),
    result: str = Query(default="", description="success / failed / skipped"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    items, total = apply_service.list_records(
        db, keyword=keyword, result=result, page=page, page_size=page_size
    )
    return Page(items=items, total=total)


@router.get("/records/grouped", response_model=Page[ApplyRecordBatchOut])
def list_record_batches(
    keyword: str = Query(default=""),
    result: str = Query(default="", description="success / failed / skipped"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=5, ge=1, le=20, description="每页批次（组）数"),
    db: Session = Depends(get_db),
):
    """投递记录按批次分组：一页若干个批次，每个批次带自己的记录。

    分组键是批次（一次「开始投递」= 一个批次）：用户一次性投 N 个岗位时，这 N 条记录
    在界面上折叠成一组、点击展开看明细。筛选作用在记录上；分页按批次计。
    """
    batches, total = apply_service.list_record_batches(
        db, keyword=keyword, result=result, page=page, page_size=page_size
    )
    return Page(items=batches, total=total)


@router.post("/records/{item_id}/retry", response_model=ApplyTaskOut)
def retry_record(item_id: int, db: Session = Depends(get_db)):
    item = db.get(ApplyTaskItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="投递记录不存在或已被删除")
    if item.job_id is None:
        raise HTTPException(status_code=409, detail="该记录对应的岗位已被删除，无法重投")
    payload = ApplyTaskCreate(job_ids=[item.job_id], use_queue=False)
    try:
        task = apply_service.create_apply_task(db, payload)
    except apply_service.ApplyServiceError as exc:
        _raise(exc)
    except task_runner.TaskRunnerError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApplyTaskOut.model_validate(task)


# ===== 采集 =====


@collect_router.post("/tasks", response_model=ApplyTaskOut)
def create_collect_task(payload: CollectTaskCreateIn | None = None, db: Session = Depends(get_db)):
    """开始一次采集。

    请求体可省略（保持既有调用方式不变）；给了 ``save_site_samples=true`` 才保存本次抓到的
    站点原文——默认关闭，绝不默默记录。
    """
    save_site_samples = bool(payload.save_site_samples) if payload is not None else False
    try:
        task = apply_service.create_collect_task(db, save_site_samples=save_site_samples)
    except apply_service.ApplyServiceError as exc:
        _raise(exc)
    except task_runner.TaskRunnerError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApplyTaskOut.model_validate(task)


@collect_router.post("/backfill", response_model=ApplyTaskOut)
def create_backfill_task(payload: CollectBackfillIn, db: Session = Depends(get_db)):
    """按岗位 id 只补抓详情：修"当年采集时详情没抓到、JD 为空"的历史数据。

    复用采集任务（``kind=collect``）的整套运行器——浏览器会话、详情抓取、限速、暂停/停止与进度
    显示都是现成的，这里只换掉"这一批岗位从哪儿来"（由用户点名，而不是关键词翻页）。
    """
    try:
        task = apply_service.create_backfill_task(db, payload.job_ids)
    except apply_service.ApplyServiceError as exc:
        _raise(exc)
    except task_runner.TaskRunnerError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApplyTaskOut.model_validate(task)


@collect_router.get("/tasks/{task_id}", response_model=ApplyTaskDetailOut)
def collect_task_detail(task_id: int, db: Session = Depends(get_db)):
    return _task_detail(db, task_id)


@collect_router.get("/site-health", response_model=SiteHealthListOut)
def collect_site_health(db: Session = Depends(get_db)):
    """每个招聘网站的采集健康度。

    把"采集悄悄抓不到东西"（站点改版后能翻到列表却读不出岗位/详情）变成用户看得见的
    ``degraded`` 标记与可操作原因。判据完全在后端（``services/site_health``），前端只展示。
    """
    return SiteHealthListOut(sites=site_health_overview(db))


__all__ = ["collect_router", "router"]
