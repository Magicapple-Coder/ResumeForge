"""投递台配置存取（app_setting 键值，脏数据退回默认）。"""
from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from ...models.setting import AppSetting
from ...schemas.apply import ApplyConfigIn, ApplyConfigOut, CollectConfigIn, CollectConfigOut
from ._base import APPLY_CONFIG_KEY, COLLECT_CONFIG_KEY

logger = logging.getLogger(__name__)
def get_apply_config(db: Session) -> ApplyConfigIn:
    """读取投递配置；缺失或脏数据退回默认。"""
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
    """读取采集配置；缺失或脏数据退回默认。"""
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
