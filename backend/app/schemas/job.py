"""岗位 Schema。"""
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..models.job import JOB_STATUSES
from .extraction import (
    MAX_EXTRACTION_DOCUMENT_COUNT,
    MAX_EXTRACTION_IMAGE_COUNT,
    MAX_RECOGNIZED_TEXT_CHARS,
    ExtractionDocumentInput,
    ExtractionImageInput,
)
from .profile import validate_photo_data_url


MAX_SQLITE_INTEGER = 2**63 - 1
MAX_JOB_TEXT_CHARS = 200_000
# 备注图片随岗位表单一次性提交，受默认 8 MB 请求体上限约束，所以只放 2 张。
MAX_JOB_NOTE_IMAGES = 2

# 招聘信息的录入方式，用于备注里的溯源标注。
# 注意顺序：这里既是可选值清单，也是前端下拉的展示顺序。
RECOGNITION_SOURCES = (
    "手动填写",
    "粘贴文本识别",
    "图片识别",
    "文档识别",
    "备选岗位导入",
    "AI 助手录入",
)

# 一次粘贴的材料最多拆成多少份岗位草稿；再多就不是"顺手粘了几份"了。
MAX_MULTI_JOBS = 12
JobId = Annotated[int, Field(strict=True, ge=1, le=MAX_SQLITE_INTEGER)]


def validate_note_images(values: list[str]) -> list[str]:
    """备注图片沿用资料照片的校验：JPEG/PNG/WebP、单张不超过 2 MB。"""
    if len(values) > MAX_JOB_NOTE_IMAGES:
        raise ValueError(f"备注图片最多 {MAX_JOB_NOTE_IMAGES} 张")
    return [validate_photo_data_url(value) for value in values]


def validate_recognition_source(value: str) -> str:
    value = (value or "").strip()
    if value and value not in RECOGNITION_SOURCES:
        raise ValueError("无效的招聘信息来源")
    return value


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
    additional_info: str = Field(default="", max_length=MAX_JOB_TEXT_CHARS)
    source_url: str = Field(default="", max_length=512)
    posted_at: str = Field(default="", max_length=32)
    status: str = Field(default="开放中", max_length=16)
    note: str = Field(default="", max_length=2000)
    note_images: list[str] = Field(default_factory=list, max_length=MAX_JOB_NOTE_IMAGES)
    recognition_source: str = Field(default="", max_length=32)
    favorite: bool = False

    @field_validator("status")
    @classmethod
    def status_must_be_supported(cls, value: str) -> str:
        return _validate_status(value)

    @field_validator("source_url")
    @classmethod
    def source_url_must_be_http(cls, value: str) -> str:
        return _validate_source_url(value)

    @field_validator("note_images")
    @classmethod
    def note_images_must_be_safe(cls, value: list[str]) -> list[str]:
        return validate_note_images(value)

    @field_validator("recognition_source")
    @classmethod
    def recognition_source_must_be_supported(cls, value: str) -> str:
        return validate_recognition_source(value)


class JobUpdate(BaseModel):
    """PUT 语义：只更新提交了的字段。"""

    title: str = Field(default="", max_length=128)
    company: str = Field(default="", max_length=128)
    location: str = Field(default="", max_length=64)
    salary: str = Field(default="", max_length=64)
    job_type: str = Field(default="", max_length=32)
    description: str = Field(default="", max_length=MAX_JOB_TEXT_CHARS)
    requirements: str = Field(default="", max_length=MAX_JOB_TEXT_CHARS)
    additional_info: str = Field(default="", max_length=MAX_JOB_TEXT_CHARS)
    source_url: str = Field(default="", max_length=512)
    posted_at: str = Field(default="", max_length=32)
    status: str = Field(default="开放中", max_length=16)
    note: str = Field(default="", max_length=2000)
    note_images: list[str] = Field(default_factory=list, max_length=MAX_JOB_NOTE_IMAGES)
    recognition_source: str = Field(default="", max_length=32)
    favorite: bool = False

    @field_validator("status")
    @classmethod
    def status_must_be_supported_when_set(cls, value: str) -> str:
        return _validate_status(value)

    @field_validator("source_url")
    @classmethod
    def source_url_must_be_http_when_set(cls, value: str) -> str:
        return _validate_source_url(value)

    @field_validator("note_images")
    @classmethod
    def note_images_must_be_safe_when_set(cls, value: list[str]) -> list[str]:
        return validate_note_images(value)

    @field_validator("recognition_source")
    @classmethod
    def recognition_source_must_be_supported_when_set(cls, value: str) -> str:
        return validate_recognition_source(value)


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
    """粘贴的招聘文本、招聘信息截图或招聘文档（可同时给）。"""

    text: str = Field(default="", max_length=50_000)
    images: list[ExtractionImageInput] = Field(
        default_factory=list, max_length=MAX_EXTRACTION_IMAGE_COUNT
    )
    documents: list[ExtractionDocumentInput] = Field(
        default_factory=list, max_length=MAX_EXTRACTION_DOCUMENT_COUNT
    )

    @model_validator(mode="after")
    def require_text_or_images(self) -> "JobTextParseRequest":
        if not self.text.strip() and not self.images and not self.documents:
            raise ValueError("请粘贴招聘信息，或上传至少一张截图或一份文档")
        return self


class JobTextParseResult(BaseModel):
    """从粘贴文本生成的可编辑草稿，不要求岗位名称已成功识别。"""

    title: str = Field(default="", max_length=128)
    company: str = Field(default="", max_length=128)
    location: str = Field(default="", max_length=64)
    salary: str = Field(default="", max_length=64)
    job_type: str = Field(default="其他", max_length=32)
    description: str = ""
    requirements: str = ""
    additional_info: str = ""
    source_url: str = Field(default="", max_length=512)
    posted_at: str = Field(default="", max_length=32)
    status: str = Field(default="开放中", max_length=16)
    warnings: list[str] = Field(default_factory=list)
    # 识别引擎（AI 还是本地规则）。**不要**和 `JobCreate.recognition_source` 混用：
    # 那个是"这条招聘信息是怎么录进来的"，会被写进备注做溯源；草稿里的这个字段只
    # 说明"这次识别是谁做的"，保存岗位时由前端按输入类型决定来源。
    parse_engine: Literal["ai", "local"] = "local"
    # 图片识别时模型逐字抄录的原文，供用户对照截图核对；纯文本识别为空。
    recognized_text: str = Field(default="", max_length=MAX_RECOGNIZED_TEXT_CHARS)


class JobMultiTextParseResult(BaseModel):
    """一次粘贴里含多份招聘信息时的解析结果。

    每一条都是独立的岗位草稿，字段规则与单份解析完全一致（都要求能在原文里找到）。
    ``items`` 只有一个元素时说明没识别出多份，前端按普通单份流程处理即可。
    """

    items: list[JobTextParseResult] = Field(default_factory=list, max_length=MAX_MULTI_JOBS)
    parse_engine: Literal["ai", "local"] = "local"
    warnings: list[str] = Field(default_factory=list)


class JobOut(JobCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source: str = Field(default="手动添加", max_length=64)
    keywords: list[SkillTag] = Field(default_factory=list, max_length=500)
    created_at: datetime
    updated_at: datetime
