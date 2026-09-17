"""自动投递服务层。

- ``form_engine``：站点无关的通用表单理解与填写引擎。
- ``apply_service``：队列 / 配置 / 准入 / 简历与招呼语解析 / 回写 / 记录。
- ``collector``：采集编排（翻页 / 去重 / 限速 / 可暂停）。
- ``task_runner``：进程内单例任务运行器（线程 + 事件 + 落库 + 熔断）。
"""
from .apply_service import (
    ApplyBadRequest,
    ApplyConflict,
    ApplyNotFound,
    ApplyServiceError,
    add_to_queue,
    build_apply_data,
    create_apply_task,
    create_collect_task,
    current_task,
    daily_success_count,
    delete_match,
    get_apply_config,
    get_browser_manager,
    get_collect_config,
    list_queue,
    list_records,
    persist_match,
    remove_queue_item,
    reorder_queue,
    resolve_greeting,
    resolve_resume,
    save_apply_config,
    save_collect_config,
    update_queue_item,
    write_back_job_status,
)
from .collector import CollectReport, Collector
from .form_engine import Control, FIELD_SYNONYMS, FieldMapping, FormEngine
from .task_runner import (
    TaskRunner,
    TaskRunnerError,
    TaskStopped,
    get_task_runner,
    reset_task_runner,
)

__all__ = [
    "ApplyBadRequest",
    "ApplyConflict",
    "ApplyNotFound",
    "ApplyServiceError",
    "CollectReport",
    "Collector",
    "Control",
    "FIELD_SYNONYMS",
    "FieldMapping",
    "FormEngine",
    "TaskRunner",
    "TaskRunnerError",
    "TaskStopped",
    "add_to_queue",
    "build_apply_data",
    "create_apply_task",
    "create_collect_task",
    "current_task",
    "daily_success_count",
    "delete_match",
    "get_apply_config",
    "get_browser_manager",
    "get_collect_config",
    "get_task_runner",
    "list_queue",
    "list_records",
    "persist_match",
    "remove_queue_item",
    "reorder_queue",
    "reset_task_runner",
    "resolve_greeting",
    "resolve_resume",
    "save_apply_config",
    "save_collect_config",
    "update_queue_item",
    "write_back_job_status",
]
