"""运行时配置存取：用户在「设置」页填写的配置保存在本地 SQLite。

安全说明：API Key 以明文存放在本地数据库文件中。本项目定位为
单用户本地部署的工具，不做多用户暴露；如需对外部署请自行加锁。
"""
import json
import logging
from urllib.parse import urlsplit, urlunsplit

from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..models.setting import AppSetting, LLMConfigRecord
from ..schemas.setting import LLMConfig, LLMConfigRecordCreate, LLMConfigRecordOut

logger = logging.getLogger(__name__)

_LLM_CONFIG_KEY = "llm_config"
API_KEY_MASK = "********"
_RECORD_API_KEY_PREFIX = f"{API_KEY_MASK}:record:"


def _masked_api_key(api_key: str, record_id: int | None = None) -> str:
    """返回可安全发给前端、且能在后续写请求中解析的密钥引用。"""
    if not api_key:
        return ""
    if record_id is None:
        return API_KEY_MASK
    return f"{_RECORD_API_KEY_PREFIX}{record_id}"


def resolve_llm_config_api_key(db: Session, config: LLMConfig) -> LLMConfig:
    """把前端回传的脱敏占位符还原为本地保存的密钥。

    配置记录必须携带记录 ID，否则两个仅密钥不同的记录会在切换时混淆。
    该引用只在本地 API 内流转，真实密钥始终不会进入读取接口响应。
    """
    api_key = config.api_key
    if api_key == API_KEY_MASK:
        current = get_llm_config(db)
        if _normalized_base_url(config.base_url) != _normalized_base_url(current.base_url):
            raise ValueError("Base URL 已修改，请重新填写 API Key 后再保存或测试")
        resolved_key = current.api_key
    elif api_key.startswith(_RECORD_API_KEY_PREFIX):
        record_id_text = api_key.removeprefix(_RECORD_API_KEY_PREFIX)
        if not record_id_text.isdigit():
            raise ValueError("API Key 配置引用无效，请重新加载设置后再试")
        record = db.get(LLMConfigRecord, int(record_id_text))
        if record is None:
            raise ValueError("API Key 配置记录已不存在，请重新加载设置后再试")
        if _normalized_base_url(config.base_url) != _normalized_base_url(record.base_url):
            raise ValueError("Base URL 与配置记录不一致，请重新加载记录后再试")
        resolved_key = record.api_key
    else:
        resolved_key = api_key
    return config.model_copy(update={"api_key": resolved_key})


def _normalized_base_url(value: str) -> str:
    """绑定密钥引用与服务地址，避免占位符把密钥转发到其他主机。"""
    stripped = value.strip().rstrip("/")
    try:
        parsed = urlsplit(stripped)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return stripped
    if not parsed.scheme or not hostname or parsed.username or parsed.password:
        return stripped
    normalized_host = hostname.casefold()
    if ":" in normalized_host:
        normalized_host = f"[{normalized_host}]"
    netloc = f"{normalized_host}:{port}" if port is not None else normalized_host
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            netloc,
            parsed.path.rstrip("/"),
            parsed.query,
            parsed.fragment,
        )
    )


def mask_llm_config(db: Session, config: LLMConfig) -> LLMConfig:
    """脱敏当前配置；若它来自配置记录，则保留可安全回传的记录引用。"""
    record_id = None
    if config.api_key:
        fields = (
            "provider",
            "base_url",
            "api_key",
            "model",
            "temperature",
            "timeout_seconds",
            "max_tokens",
        )
        records = db.query(LLMConfigRecord).order_by(LLMConfigRecord.updated_at.desc()).all()
        matching = next(
            (
                row
                for row in records
                if all(getattr(row, field) == getattr(config, field) for field in fields)
            ),
            None,
        )
        record_id = matching.id if matching is not None else None
    return config.model_copy(update={"api_key": _masked_api_key(config.api_key, record_id)})


def _mask_llm_config_record(record: LLMConfigRecord) -> LLMConfigRecordOut:
    output = LLMConfigRecordOut.model_validate(record)
    return output.model_copy(update={"api_key": _masked_api_key(record.api_key, record.id)})


def get_llm_config(db: Session) -> LLMConfig:
    row = db.get(AppSetting, _LLM_CONFIG_KEY)
    if row is None:
        return LLMConfig()
    try:
        return LLMConfig.model_validate(json.loads(row.value))
    except (json.JSONDecodeError, ValidationError):
        # 脏数据降级为默认配置，不阻塞用户重新填写
        logger.warning("LLM 配置数据损坏，已重置为默认值")
        return LLMConfig()


def save_llm_config(db: Session, config: LLMConfig) -> LLMConfig:
    config = resolve_llm_config_api_key(db, config)
    row = db.get(AppSetting, _LLM_CONFIG_KEY)
    serialized = json.dumps(config.model_dump(), ensure_ascii=False)
    if row is None:
        db.add(AppSetting(key=_LLM_CONFIG_KEY, value=serialized))
    else:
        row.value = serialized
    db.commit()
    return config


def list_llm_config_records(db: Session) -> list[LLMConfigRecordOut]:
    rows = db.query(LLMConfigRecord).order_by(LLMConfigRecord.updated_at.desc()).all()
    return [_mask_llm_config_record(row) for row in rows]


def save_llm_config_record(db: Session, payload: LLMConfigRecordCreate) -> LLMConfigRecordOut:
    payload = resolve_llm_config_api_key(db, payload)
    row = db.query(LLMConfigRecord).filter(LLMConfigRecord.name == payload.name).one_or_none()
    values = payload.model_dump(exclude={"name"})
    if row is None:
        row = LLMConfigRecord(name=payload.name, **values)
        db.add(row)
    else:
        for field, value in values.items():
            setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _mask_llm_config_record(row)


def delete_llm_config_record(db: Session, record_id: int) -> None:
    row = db.get(LLMConfigRecord, record_id)
    if row is not None:
        db.delete(row)
        db.commit()
