"""岗位 Schema。"""
from datetime import datetime
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models.job import JOB_STATUSES


MAX_SQLITE_INTEGER = 2**63 - 1
MAX_JOB_TEXT_CHARS = 200_000
JobId = Annotated[int, Field(strict=True, ge=1, le=MAX_SQLITE_INTEGER)]


def _validate_status(value: str) -> str:
    if value not in JOB_STATUSES:
        allowed = "、".join(JOB_STATUSES)
        raise ValueError(f"无效的岗位状态，可选值：{allowed}")
    return value


def _validate_source_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise ValueError("投递链接必须是有效的 HTTP 或 HTTPS 地址") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("投递链接只支持 HTTP 或 HTTPS 地址")
    return value


class SkillTag(BaseModel):
    name: str = Field(max_length=128)
    category: str = Field(max_length=64)


class JobCreate(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    company: str = Field(default="", max_length=128)
    location: str = Field(default="", max_length=64)
    salary: str = Field(default="", max_length=64)
    job_type: str = Field(default="校招", max_length=32)
    description: str = Field(default="", max_length=MAX_JOB_TEXT_CHARS)
    requirements: str = Field(default="", max_length=MAX_JOB_TEXT_CHARS)
    source_url: str = Field(default="", max_length=512)
    posted_at: str = Field(default="", max_length=32)
    status: str = Field(default="开放中", max_length=16)
    note: str = Field(default="", max_length=2000)
    favorite: bool = False

    @field_validator("status")
    @classmethod
    def status_must_be_supported(cls, value: str) -> str:
        return _validate_status(value)

    @field_validator("source_url")
    @classmethod
    def source_url_must_be_http(cls, value: str) -> str:
        return _validate_source_url(value)


class JobUpdate(BaseModel):
    """PUT 语义：只更新提交了的字段。"""

    title: str = Field(default="", max_length=128)
    company: str = Field(default="", max_length=128)
    location: str = Field(default="", max_length=64)
    salary: str = Field(default="", max_length=64)
    job_type: str = Field(default="", max_length=32)
    description: str = Field(default="", max_length=MAX_JOB_TEXT_CHARS)
    requirements: str = Field(default="", max_length=MAX_JOB_TEXT_CHARS)
    source_url: str = Field(default="", max_length=512)
    posted_at: str = Field(default="", max_length=32)
    status: str = Field(default="开放中", max_length=16)
    note: str = Field(default="", max_length=2000)
    favorite: bool = False

    @field_validator("status")
    @classmethod
    def status_must_be_supported_when_set(cls, value: str) -> str:
        return _validate_status(value)

    @field_validator("source_url")
    @classmethod
    def source_url_must_be_http_when_set(cls, value: str) -> str:
        return _validate_source_url(value)


class JobBatchRequest(BaseModel):
    job_ids: list[JobId] = Field(max_length=500)

    @field_validator("job_ids")
    @classmethod
    def validate_and_deduplicate_ids(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("请至少选择一个岗位")
        unique_ids = list(dict.fromkeys(value))
        return unique_ids


class JobBatchStatusRequest(JobBatchRequest):
    status: str = Field(min_length=1, max_length=16)


class JobBatchStatusResult(BaseModel):
    updated: int


class JobBatchDeleteResult(BaseModel):
    deleted: int


class JobTextParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)

    @field_validator("text")
    @classmethod
    def text_must_contain_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("招聘信息不能为空")
        return value


class JobTextParseResult(BaseModel):
    """从粘贴文本生成的可编辑草稿，不要求岗位名称已成功识别。"""

    title: str = Field(default="", max_length=128)
    company: str = Field(default="", max_length=128)
    location: str = Field(default="", max_length=64)
    salary: str = Field(default="", max_length=64)
    job_type: str = Field(default="其他", max_length=32)
    description: str = ""
    requirements: str = ""
    source_url: str = Field(default="", max_length=512)
    posted_at: str = Field(default="", max_length=32)
    status: str = Field(default="开放中", max_length=16)
    warnings: list[str] = Field(default_factory=list)


class JobOut(JobCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source: str = Field(default="手动添加", max_length=64)
    keywords: list[SkillTag] = Field(default_factory=list, max_length=500)
    created_at: datetime
    updated_at: datetime
