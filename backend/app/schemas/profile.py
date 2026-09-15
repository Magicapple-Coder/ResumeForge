"""个人资料 Schema：In 为写入结构（子表不带 id），Out 为读取结构。"""
import base64
import binascii
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .extraction import MAX_EXTRACTION_IMAGE_COUNT, MAX_RECOGNIZED_TEXT_CHARS, ExtractionImageInput


MAX_PROFILE_PHOTO_BYTES = 2 * 1024 * 1024
MAX_REFERENCE_FILE_NAME_CHARS = 255
MAX_REFERENCE_CONTENT_CHARS = 200_000
MAX_PROFILE_TEXT_CHARS = 100_000
MAX_PROFILE_DETAIL_CHARS = 200_000
MAX_PROFILE_SECTION_ITEMS = 200
PROFILE_SECTION_KEYS = (
    "basic_info",
    "educations",
    "experiences",
    "campus_experiences",
    "projects",
    "skills",
    "awards",
    "summary",
)
_MAX_ENCODED_PHOTO_CHARS = 4 * ((MAX_PROFILE_PHOTO_BYTES + 2) // 3)
_PHOTO_HEADER_RE = re.compile(r"^data:(image/(?:jpeg|png|webp));base64$", re.IGNORECASE)


def validate_photo_data_url(value: str) -> str:
    """只接受体积受限且文件签名匹配的 JPEG/PNG/WebP data URL。"""
    if not value:
        return ""

    header, separator, encoded = value.partition(",")
    header_match = _PHOTO_HEADER_RE.fullmatch(header)
    if not separator or header_match is None:
        raise ValueError("照片必须是 JPEG、PNG 或 WebP 格式的 base64 data URL")
    if len(encoded) > _MAX_ENCODED_PHOTO_CHARS:
        raise ValueError("照片大小不能超过 2 MB")

    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("照片数据不是有效的 base64 编码") from exc
    if len(image_bytes) > MAX_PROFILE_PHOTO_BYTES:
        raise ValueError("照片大小不能超过 2 MB")

    mime = header_match.group(1).lower()
    signatures_match = {
        "image/jpeg": image_bytes.startswith(b"\xff\xd8\xff"),
        "image/png": image_bytes.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": (
            len(image_bytes) >= 12
            and image_bytes.startswith(b"RIFF")
            and image_bytes[8:12] == b"WEBP"
        ),
    }
    if not signatures_match[mime]:
        raise ValueError("照片内容与声明的图片格式不一致")
    return value


class ReferenceFileFields(BaseModel):
    """浏览器读取的参考文件；服务端不接收也不保存本地路径。"""

    reference_file_name: str = ""
    reference_content: str = ""

    @field_validator("reference_file_name")
    @classmethod
    def reference_file_name_must_fit(cls, value: str) -> str:
        if len(value) > MAX_REFERENCE_FILE_NAME_CHARS:
            raise ValueError(
                f"参考文件名不能超过 {MAX_REFERENCE_FILE_NAME_CHARS} 个字符"
            )
        return value

    @field_validator("reference_content")
    @classmethod
    def reference_content_must_fit(cls, value: str) -> str:
        if len(value) > MAX_REFERENCE_CONTENT_CHARS:
            raise ValueError(
                f"参考文件内容不能超过 {MAX_REFERENCE_CONTENT_CHARS} 个字符"
            )
        return value


class EducationIn(ReferenceFileFields):
    school: str = Field(default="", max_length=128)
    major: str = Field(default="", max_length=128)
    degree: str = Field(default="", max_length=32)
    start_date: str = Field(default="", max_length=32)
    end_date: str = Field(default="", max_length=32)
    gpa: str = Field(default="", max_length=64)
    courses: str = Field(default="", max_length=MAX_PROFILE_DETAIL_CHARS)  # 换行分隔
    achievements: str = Field(default="", max_length=MAX_PROFILE_DETAIL_CHARS)  # 换行分隔


class ExperienceIn(ReferenceFileFields):
    company: str = Field(default="", max_length=128)
    role: str = Field(default="", max_length=128)
    start_date: str = Field(default="", max_length=32)
    end_date: str = Field(default="", max_length=32)
    description: str = Field(default="", max_length=MAX_PROFILE_DETAIL_CHARS)  # 换行分隔


class CampusExperienceIn(ReferenceFileFields):
    organization: str = Field(default="", max_length=128)
    role: str = Field(default="", max_length=128)
    start_date: str = Field(default="", max_length=32)
    end_date: str = Field(default="", max_length=32)
    description: str = Field(default="", max_length=MAX_PROFILE_DETAIL_CHARS)  # 换行分隔


class ProjectIn(ReferenceFileFields):
    name: str = Field(default="", max_length=128)
    role: str = Field(default="", max_length=64)
    start_date: str = Field(default="", max_length=32)
    end_date: str = Field(default="", max_length=32)
    tech_stack: str = Field(default="", max_length=10_000)  # 逗号分隔
    description: str = Field(default="", max_length=MAX_PROFILE_DETAIL_CHARS)  # 换行分隔
    highlights: str = Field(default="", max_length=MAX_PROFILE_DETAIL_CHARS)  # 换行分隔


class SkillIn(BaseModel):
    name: str = Field(default="", max_length=64)
    level: str = Field(default="", max_length=32)


class AwardIn(BaseModel):
    name: str = Field(default="", max_length=128)
    date: str = Field(default="", max_length=32)
    description: str = Field(default="", max_length=2000)


class EducationOut(EducationIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ExperienceOut(ExperienceIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class CampusExperienceOut(CampusExperienceIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ProjectOut(ProjectIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class SkillOut(SkillIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class AwardOut(AwardIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ProfileUpdate(BaseModel):
    """PUT 语义：整体替换，子表列表会先删后插。"""

    name: str = Field(default="", max_length=64)
    gender: str = Field(default="", max_length=64)
    birth_year: str = Field(default="", max_length=32)
    phone: str = Field(default="", max_length=32)
    email: str = Field(default="", max_length=128)
    city: str = Field(default="", max_length=64)
    target_city: str = Field(default="", max_length=64)
    job_intent: str = Field(default="", max_length=128)
    personal_website: str = Field(default="", max_length=256)
    github: str = Field(default="", max_length=256)
    photo: str = ""
    summary: str = Field(default="", max_length=MAX_PROFILE_DETAIL_CHARS)
    section_order: list[str] = Field(
        default_factory=lambda: list(PROFILE_SECTION_KEYS), max_length=len(PROFILE_SECTION_KEYS)
    )
    educations: list[EducationIn] = Field(default_factory=list, max_length=MAX_PROFILE_SECTION_ITEMS)
    experiences: list[ExperienceIn] = Field(default_factory=list, max_length=MAX_PROFILE_SECTION_ITEMS)
    campus_experiences: list[CampusExperienceIn] = Field(
        default_factory=list, max_length=MAX_PROFILE_SECTION_ITEMS
    )
    projects: list[ProjectIn] = Field(default_factory=list, max_length=MAX_PROFILE_SECTION_ITEMS)
    skills: list[SkillIn] = Field(default_factory=list, max_length=MAX_PROFILE_SECTION_ITEMS)
    awards: list[AwardIn] = Field(default_factory=list, max_length=MAX_PROFILE_SECTION_ITEMS)

    @field_validator("photo")
    @classmethod
    def photo_must_be_safe_image(cls, value: str) -> str:
        return validate_photo_data_url(value)

    @field_validator("section_order")
    @classmethod
    def section_order_must_be_supported(cls, value: list[str]) -> list[str]:
        supported = set(PROFILE_SECTION_KEYS)
        normalized = list(dict.fromkeys(key for key in value if key in supported))
        normalized.extend(key for key in PROFILE_SECTION_KEYS if key not in normalized)
        return normalized


class ProfileTextParseRequest(BaseModel):
    """粘贴的个人资料文本，或若干张资料截图（两者可同时给）。"""

    text: str = Field(default="", max_length=MAX_PROFILE_TEXT_CHARS)
    images: list[ExtractionImageInput] = Field(
        default_factory=list, max_length=MAX_EXTRACTION_IMAGE_COUNT
    )

    @model_validator(mode="after")
    def require_text_or_images(self) -> "ProfileTextParseRequest":
        if not self.text.strip() and not self.images:
            raise ValueError("请粘贴个人资料，或上传至少一张截图")
        return self


class ProfileTextParseResult(ProfileUpdate):
    warnings: list[str] = Field(default_factory=list)
    recognition_source: Literal["ai", "local"] = "local"
    # 图片识别时模型逐字抄录的原文，供用户对照截图核对；纯文本识别为空。
    recognized_text: str = Field(default="", max_length=MAX_RECOGNIZED_TEXT_CHARS)


class ProfileOut(ProfileUpdate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    # 读取历史数据时保持宽容；写入约束由 ProfileUpdate 执行。
    name: str = ""
    updated_at: datetime | None = None
    educations: list[EducationOut] = Field(default_factory=list, max_length=MAX_PROFILE_SECTION_ITEMS)
    experiences: list[ExperienceOut] = Field(default_factory=list, max_length=MAX_PROFILE_SECTION_ITEMS)
    campus_experiences: list[CampusExperienceOut] = Field(
        default_factory=list, max_length=MAX_PROFILE_SECTION_ITEMS
    )
    projects: list[ProjectOut] = Field(default_factory=list, max_length=MAX_PROFILE_SECTION_ITEMS)
    skills: list[SkillOut] = Field(default_factory=list, max_length=MAX_PROFILE_SECTION_ITEMS)
    awards: list[AwardOut] = Field(default_factory=list, max_length=MAX_PROFILE_SECTION_ITEMS)
