"""资料箱与备选岗位 Schema。"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .extraction import MAX_EXTRACTION_IMAGE_COUNT
from .profile import validate_photo_data_url

# 一条资料能挂多少个附件。资料箱现在主要放找工作/面试相关的材料（JD 原文、面经、
# 证书、投递记录），十条附件是够用的量级；真正的约束是下面的图片总量与请求体上限。
MAX_MATERIAL_FILES = 10
# 图片单独设上限：整份资料在一次请求里提交，图片体积远大于文字。4 张够放下证书正反面
# 加两张截图；再多的图片应该拆成两条资料。
MAX_MATERIAL_IMAGE_FILES = 4
# 图片的 base64 总长度上限：默认请求体上限是 8 MB，图片占大头，这里先卡住总额度，
# 免得用户一次性提交未压缩的大图后收到一个"请求体过大"的 413。张数放宽到 4 之后，
# 这条才是真正的约束——4 张未压缩的大图会在这里被挡住，而不是让请求撞上体积上限。
MAX_MATERIAL_IMAGE_CHARS = 6_000_000
# 单份文本附件的上限（字符数）：与经历参考文件同量级，中文约占 300 KB。
MAX_MATERIAL_FILE_TEXT_CHARS = 100_000
MAX_MATERIAL_TITLE_CHARS = 256
MAX_MATERIAL_CONTENT_CHARS = 100_000
MAX_MATERIAL_NOTE_CHARS = 4000
MAX_CANDIDATE_JOB_TEXT_CHARS = 50_000


class MaterialFileInput(BaseModel):
    """资料附件：本机提取出的文字，或一张图片的缩略图。

    与助手附件保持同一取舍：文档的原始文件不外发也不入库，只保留提取出的文字；
    图片则保存受限的 data URL 供界面预览。
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(default="", max_length=100)
    size_bytes: int = Field(default=0, ge=0, le=50 * 1024 * 1024)
    text: str = Field(default="", max_length=MAX_MATERIAL_FILE_TEXT_CHARS)
    data_url: str = Field(default="", max_length=4 * 1024 * 1024)

    @field_validator("data_url")
    @classmethod
    def data_url_must_be_safe_image(cls, value: str) -> str:
        return validate_photo_data_url(value)

    @model_validator(mode="after")
    def require_content(self) -> "MaterialFileInput":
        if not self.text.strip() and not self.data_url:
            raise ValueError(f"附件「{self.name}」没有可保存的内容")
        return self


class MaterialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=MAX_MATERIAL_TITLE_CHARS)
    category: str = Field(default="其他", max_length=64)
    content: str = Field(default="", max_length=MAX_MATERIAL_CONTENT_CHARS)
    url: str = Field(default="", max_length=1024)
    files: list[MaterialFileInput] = Field(default_factory=list, max_length=MAX_MATERIAL_FILES)
    note: str = Field(default="", max_length=MAX_MATERIAL_NOTE_CHARS)

    @model_validator(mode="after")
    def require_something(self) -> "MaterialCreate":
        self.title = self.title.strip()
        self.category = self.category.strip() or "其他"
        if not self.title and not self.content.strip() and not self.files and not self.url.strip():
            raise ValueError("请至少填写标题、内容、链接或添加附件")
        # 图片单独设上限：整份资料在一次请求里提交，图片体积远大于文字。
        images = [item for item in self.files if item.data_url]
        if len(images) > MAX_MATERIAL_IMAGE_FILES:
            raise ValueError(f"一份资料最多附加 {MAX_MATERIAL_IMAGE_FILES} 张图片")
        total_image_chars = sum(len(item.data_url) for item in images)
        if total_image_chars > MAX_MATERIAL_IMAGE_CHARS:
            # 说清是"总量"超了而不是"张数"超了：张数上限是 4，用户加到第 4 张才被拒会
            # 以为是张数问题，实际是这 4 张加起来太大。
            raise ValueError(
                f"图片总量过大（{len(images)} 张合计约 "
                f"{total_image_chars // 1_000_000} MB），请减少张数或压缩后再上传"
            )
        return self


class MaterialUpdate(MaterialCreate):
    """PUT 语义：整体替换一条资料。"""


class MaterialOut(MaterialCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class CandidateJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=128)
    company: str = Field(default="", max_length=128)
    raw_text: str = Field(default="", max_length=MAX_CANDIDATE_JOB_TEXT_CHARS)
    images: list[str] = Field(default_factory=list, max_length=MAX_EXTRACTION_IMAGE_COUNT)
    note: str = Field(default="", max_length=2000)
    source: Literal["手动添加", "粘贴文本", "招聘截图", "招聘文档", "助手录入"] = "手动添加"

    @field_validator("images")
    @classmethod
    def images_must_be_safe(cls, value: list[str]) -> list[str]:
        return [validate_photo_data_url(item) for item in value]

    @model_validator(mode="after")
    def require_content(self) -> "CandidateJobCreate":
        self.title = self.title.strip()
        self.company = self.company.strip()
        if not self.raw_text.strip() and not self.images and not self.title:
            raise ValueError("请粘贴招聘信息、上传截图或至少填写岗位名称")
        return self


class CandidateJobUpdate(BaseModel):
    """只更新提交了的字段。"""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=128)
    company: str | None = Field(default=None, max_length=128)
    raw_text: str | None = Field(default=None, max_length=MAX_CANDIDATE_JOB_TEXT_CHARS)
    images: list[str] | None = Field(default=None, max_length=MAX_EXTRACTION_IMAGE_COUNT)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("images")
    @classmethod
    def images_must_be_safe(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [validate_photo_data_url(item) for item in value]


class CandidateJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    company: str
    raw_text: str
    images: list[str] = Field(default_factory=list)
    note: str
    source: str
    status: Literal["pending", "imported"]
    imported_job_id: int | None = None
    created_at: datetime
    updated_at: datetime


class CandidateJobImportRequest(BaseModel):
    """把备选岗位标记为已导入；真正创建岗位仍走正式的岗位保存接口。"""

    model_config = ConfigDict(extra="forbid")

    job_id: int = Field(ge=1)
