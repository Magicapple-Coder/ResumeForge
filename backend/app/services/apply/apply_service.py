"""投递台业务逻辑：配置、队列、准入、简历/招呼语解析、回写与记录。

设计要点（决定它为什么长这样）：

- **准入闸门只认一处**：能不能自动投、要不要逐条确认，全部通过 ``models.apply``
  的 ``admission_of`` / ``requires_confirmation`` 判断，本模块**不再另写一份**映射。
- **队列去重是第一道闸**：同一岗位在队列里只能有一条（数据库唯一约束 + 这里的显式 409）。
- **记录只保存展示快照**，不含任何完整个人资料；招呼语按"记全文但截断到上限"处理。

实现按职责拆到 ``_base``（常量/异常/通用剪裁）、``_config``（配置）、``_match``（匹配结论）、
``_queue``（队列与简历/招呼语）、``_records``（回写与记录）、``_tasks``（任务批次）、
``_site_browser``（站点与浏览器）；本文件只做对外门面，重新导出公共符号。
"""
from ...schemas.apply import ApplyConfigIn, ApplyTaskCreate  # noqa: F401 - 历史导出
from ..browser.browser_manager import BrowserManager  # noqa: F401 - 历史导出
from ._base import (
    ACTIVE_TASK_STATUSES,
    APPLY_CONFIG_KEY,
    COLLECT_CONFIG_KEY,
    ApplyBadRequest,
    ApplyConflict,
    ApplyNotFound,
    ApplyServiceError,
    _clip_greeting,  # noqa: F401 - 历史导出
)
from ._config import (
    collect_config_out,
    config_out,
    get_apply_config,
    get_collect_config,
    save_apply_config,
    save_collect_config,
)
from ._match import delete_match, latest_match, persist_match
from ._queue import (
    add_to_queue,
    build_apply_data,
    job_apply_site,  # noqa: F401 - 历史导出
    list_queue,
    remove_queue_item,
    reorder_queue,
    resolve_greeting,
    resolve_resume,
    unsupported_site_message,  # noqa: F401 - 历史导出
    update_queue_item,
)
from ._records import (
    daily_success_count,
    list_record_batches,
    list_records,
    mark_queue_done,
    write_back_job_status,
)
from ._tasks import (
    create_apply_task,
    create_backfill_task,
    create_collect_task,
    current_task,
    fail_orphaned_tasks,
    get_task_detail,
)
from ._site_browser import (
    browser_status,
    collect_filter_options,
    current_site,
    current_site_key,
    default_entry_url,
    get_browser_manager,
    list_sites,
    open_browser_url,
    reset_browser_manager,
    start_browser,
    stop_browser,
)

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
    "collect_filter_options",
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
    "list_record_batches",
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
