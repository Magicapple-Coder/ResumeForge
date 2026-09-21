"""采集批次执行：站点选择、样例录制、失败分类与收尾文案。"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from ...models.apply import (
    FAILURE_UNKNOWN,
    STEP_IDLE,
    STOP_REASON_DONE,
    STOP_REASON_ERROR,
    STOP_REASON_USER,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    ApplyTask,
)
from ...models.profile import utcnow
from ...schemas.apply import CollectConfigIn
from ..browser.cdp_client import CdpClient, CdpError
from ..browser.sample_recorder import SampleRecordingCdpClient
from ..sites.base import SiteFailure
from ..sites.registry import get_registry
from .collector import Collector

logger = logging.getLogger(__name__)


def is_within(path: Path, root: Path) -> bool:
    """``path`` 是否落在 ``root`` 内，解析 ``..`` 与符号链接后再判断。"""
    try:
        resolved = path.resolve()
        base = root.resolve()
    except OSError:
        return False
    return resolved == base or base in resolved.parents


def run_collect(
    runner: Any,
    session: Any,
    task: ApplyTask,
    *,
    stopped_error: type[Exception],
    wrap_client: Callable[[CdpClient], CdpClient],
    captures_root_factory: Callable[[], Path],
    log: logging.Logger = logger,
) -> None:
    """执行一个采集或补齐详情批次。"""
    backfill_job_ids = runner._backfill_job_ids(task)
    save_site_samples = bool((task.config or {}).get("save_site_samples"))
    config = runner._load_config(
        task, CollectConfigIn, ignore=("backfill_job_ids", "save_site_samples")
    )
    registry = runner._registry or get_registry()
    site_key = runner._collect_site_key(session)
    task.config = {**(task.config or {}), "site_key": site_key}
    session.commit()
    adapter = runner._collect_adapter(session, registry)
    if adapter is None:
        runner._record_failure_category(task, FAILURE_UNKNOWN)
        runner._finalize(
            session, task, TASK_STATUS_FAILED, STOP_REASON_ERROR, message="没有可用的采集适配器"
        )
        return
    try:
        client = runner._make_client(config)
    except Exception as exc:  # noqa: BLE001 - 连接错误要直接展示给用户
        runner._record_failure_category(task, FAILURE_UNKNOWN)
        runner._finalize(
            session,
            task,
            TASK_STATUS_FAILED,
            STOP_REASON_ERROR,
            message=str(exc) or "无法连接投递专用浏览器，请先在投递台启动浏览器",
        )
        return

    wrapped = wrap_client(client)
    recorder: SampleRecordingCdpClient | None = None
    markers = tuple(getattr(adapter, "sample_markers", ()) or ())
    if save_site_samples and markers:
        captures_root = captures_root_factory()
        target_dir = captures_root / (adapter.key or "unknown")
        if is_within(target_dir, captures_root):
            recorder = SampleRecordingCdpClient(wrapped, markers=markers, directory=target_dir)
            wrapped = recorder
        else:
            log.warning("站点样例目录不在 captures 之内，已跳过保存：%s", target_dir)
    try:
        Collector().run(
            session=session,
            task=task,
            client=wrapped,
            adapter=adapter,
            config=config,
            checkpoint=runner._checkpoint,
            sleeper=runner._sleeper,
            clock=runner._clock,
            backfill_job_ids=backfill_job_ids or None,
        )
    except stopped_error:
        runner._record_sample_result(task, recorder)
        runner._stop_remaining(session, task, [], 0, reason=STOP_REASON_USER, message="")
        return
    except SiteFailure as exc:
        runner._record_failure_category(task, exc.category)
        runner._finalize(
            session, task, TASK_STATUS_FAILED, STOP_REASON_ERROR, message=f"采集失败：{exc.detail}"
        )
        runner._record_sample_result(task, recorder)
        session.commit()
        return
    except CdpError as exc:
        runner._record_failure_category(task, FAILURE_UNKNOWN)
        runner._finalize(
            session, task, TASK_STATUS_FAILED, STOP_REASON_ERROR, message=f"采集失败：{exc}"
        )
        runner._record_sample_result(task, recorder)
        session.commit()
        return
    finally:
        client.close()

    task.status = TASK_STATUS_COMPLETED
    task.stop_reason = STOP_REASON_DONE
    task.current_step = STEP_IDLE
    task.finished_at = utcnow()
    task.message = task.message or runner._collect_message(task)
    runner._record_sample_result(task, recorder)
    session.commit()


def collect_adapter(session: Any, registry: Any, site_key_reader: Callable[[Any], str]) -> Any:
    """按当前站点取采集适配器，无法解析时回退到注册表首项。"""
    adapters = registry.all()
    if not adapters:
        return None
    site_key = site_key_reader(session)
    if site_key:
        adapter = registry.resolve(site_key)
        if adapter is not None:
            return adapter
    return adapters[0]


def collect_site_key(session: Any, *, log: logging.Logger = logger) -> str:
    """读取用户实际选择的站点 key；失败时留空，不编造默认值。"""
    from . import apply_service

    try:
        return apply_service.get_apply_config(session).site_key or ""
    except Exception:  # noqa: BLE001 - 配置损坏不应阻断采集
        log.warning("读取当前站点配置失败（站点标识留空）", exc_info=True)
        return ""


def record_failure_category(task: ApplyTask, category: str) -> None:
    task.config = {**(task.config or {}), "failure_category": category or FAILURE_UNKNOWN}


def record_sample_result(task: ApplyTask, recorder: SampleRecordingCdpClient | None) -> None:
    if recorder is None:
        return
    saved = int(recorder.saved_count)
    directory = str(recorder.directory)
    task.config = {**(task.config or {}), "saved_samples": saved, "samples_dir": directory}
    if saved:
        note = f"（已保存 {saved} 份站点原文，可在 {directory} 查看）"
    else:
        note = f"（本次未保存站点原文，目录 {directory}）"
    task.message = f"{task.message or ''}{note}"


def collect_message(task: ApplyTask) -> str:
    """生成搜索采集或补齐详情的用户可读收尾文案。"""
    config = task.config or {}
    if "backfill_job_ids" in config:
        return backfill_message(config)
    succeeded = int(task.succeeded or 0)
    skipped = int(task.skipped or 0)
    filtered = int(config.get("filtered_out") or 0)
    unapplied = config.get("filter_unapplied") or []
    # 站点侧筛选**没能生效**的那几条。和本地筛选的"没能识别"是两回事（一个发给了站点但被
    # 拒收，一个根本没发出去），但对用户是同一件事：**你选了这个条件，它这次没起作用**。
    # 收尾文案是用户最先看到的一句话（完成通知里带的也是它），漏掉这句就等于静默失效。
    site_unapplied = config.get("site_filter_unapplied") or []

    if succeeded > 0:
        parts = [f"采集完成：已暂存 {succeeded} 个岗位。"]
        if filtered:
            parts.append(f"另有 {filtered} 个不符合你填的筛选条件，已筛掉。")
        if unapplied:
            parts.append(
                f"注意：{'、'.join(str(item) for item in unapplied)} "
                "这条筛选条件没能识别，本次没有生效。"
            )
        if site_unapplied:
            parts.append(
                f"注意：{'、'.join(str(item) for item in site_unapplied)} "
                "这条站点筛选条件没能生效（编码没能在站点当前清单里核对上，没有发出去）。"
            )
        parts.append(
            "在下方「本次采集结果」里勾选要收进岗位广场的岗位，再点「导入选中的岗位」。"
        )
        return "".join(parts)
    if filtered and not skipped:
        return (
            f"采集到的 {filtered} 个岗位都不符合你填的筛选条件（学历 / 经验 / 薪资），已全部筛掉。"
            "把条件放宽一些再试。"
        )
    if skipped > 0:
        message = f"本次采集到的岗位都已存在，没有新增（跳过 {skipped} 个重复岗位）"
        trashed = int(config.get("skipped_trashed") or 0)
        if trashed:
            message += (
                f"。其中 {trashed} 条在岗位广场的「回收站」里"
                "——想重新收进来，先去「回收站」恢复或彻底删除它"
            )
        return message
    if config.get("site_filter_applied"):
        # 一条都没采到、站点侧筛选又开着时，最可能的原因就是筛选太窄——而默认文案会把人
        # 往"改关键词"上引。把已经生效的条件列出来，用户才知道该松哪一条。
        return (
            "采集完成：没有找到匹配的岗位。这次还按招聘网站的条件筛过"
            f"（{'、'.join(str(item) for item in config['site_filter_applied'])}），"
            "关键词、城市或这些筛选条件可能太窄，调整后重试"
        )
    return "采集完成：没有找到匹配的岗位（关键词或城市可能太窄），请调整后重试"


def backfill_message(config: dict[str, Any]) -> str:
    """生成补齐详情模式的收尾文案。"""
    backfilled = int(config.get("backfilled") or 0)
    skipped = int(config.get("backfill_skipped") or 0)
    if backfilled > 0:
        message = f"已为 {backfilled} 条岗位补齐职位描述。"
        if skipped:
            message += f"另有 {skipped} 条跳过（已有描述 / 仍然抓不到 / 已在回收站里）。"
        return message
    if skipped:
        return (
            f"没有补到新的职位描述：{skipped} 条岗位已跳过"
            "（已有描述 / 仍然抓不到 / 已在回收站里）。"
            "若这些岗位在浏览器里确实打不开，请确认岗位仍然在线后重试。"
        )
    return "没有补到新的职位描述：所选岗位都已无可补充的内容。"


__all__ = [
    "backfill_message",
    "collect_adapter",
    "collect_message",
    "collect_site_key",
    "is_within",
    "record_failure_category",
    "record_sample_result",
    "run_collect",
]
