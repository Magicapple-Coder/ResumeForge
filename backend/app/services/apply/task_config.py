"""任务配置快照的还原与一次性编排字段解析。"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from ...models.apply import ApplyTask

logger = logging.getLogger(__name__)


def load_config(
    task: ApplyTask,
    model: type,
    *,
    ignore: Sequence[str] = (),
    log: logging.Logger = logger,
) -> Any:
    """从任务快照还原配置模型，并剔除只属于单次任务的编排字段。"""
    raw = task.config or {}
    if ignore:
        raw = {key: value for key, value in raw.items() if key not in ignore}
    try:
        return model.model_validate(raw)
    except ValidationError:
        log.warning("任务配置快照损坏，已退回默认值 task_id=%s", task.id)
        return model()


def backfill_job_ids(task: ApplyTask) -> list[int]:
    """读取并归一化「补齐详情」模式的目标岗位 id。"""
    raw = (task.config or {}).get("backfill_job_ids")
    if not isinstance(raw, list):
        return []
    ids: list[int] = []
    for value in raw:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return ids


__all__ = ["backfill_job_ids", "load_config"]
