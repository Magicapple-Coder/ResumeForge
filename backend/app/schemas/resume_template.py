"""用户自制简历模板的请求/响应结构。"""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .resume import ResumeContent

TemplateKind = Literal["style", "format"]

MAX_TEMPLATE_HTML_CHARS = 200_000
MAX_TEMPLATE_NAME_CHARS = 40
MAX_TEMPLATE_DESCRIPTION_CHARS = 255


class ResumeTemplateCreate(BaseModel):
    """新建模板：样式模板给 ``html``，格式模板给 ``config``。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_TEMPLATE_NAME_CHARS)
    kind: TemplateKind = "style"
    description: str = Field(default="", max_length=MAX_TEMPLATE_DESCRIPTION_CHARS)
    html: str = Field(default="", max_length=MAX_TEMPLATE_HTML_CHARS)
    config: dict[str, Any] = Field(default_factory=dict)
    # 从文件导入时的原始文件名，便于用户认出是哪一版。
    source_name: str = Field(default="", max_length=MAX_TEMPLATE_DESCRIPTION_CHARS)


class ResumeTemplateUpdate(BaseModel):
    """修改模板：只传要改的字段。"""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=MAX_TEMPLATE_NAME_CHARS)
    description: str | None = Field(default=None, max_length=MAX_TEMPLATE_DESCRIPTION_CHARS)
    html: str | None = Field(default=None, max_length=MAX_TEMPLATE_HTML_CHARS)
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class ResumeTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    kind: TemplateKind
    description: str
    enabled: bool
    source_name: str
    created_at: datetime
    updated_at: datetime


class ResumeTemplateDetail(ResumeTemplateOut):
    """详情：带 HTML 正文或格式配置，工作台编辑时用。"""

    html: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


class TemplatePreviewRequest(BaseModel):
    """渲染一段模板预览。

    ``html`` 为空时用已保存模板（``template_id``）或内置模板（``template_name``）。
    ``content`` 为空时用内置示例内容——工作台里的实时预览就是靠它。
    """

    model_config = ConfigDict(extra="forbid")

    template_id: int | None = Field(default=None, ge=1)
    template_name: str = Field(default="", max_length=64)
    html: str = Field(default="", max_length=MAX_TEMPLATE_HTML_CHARS)
    format_name: str = Field(default="", max_length=64)
    format_config: dict[str, Any] = Field(default_factory=dict)
    page_limit: int = Field(default=1, ge=1, le=3)
    font_scale: Literal["small", "standard", "large"] = "standard"
    content: ResumeContent | None = None
    # 用哪份已保存的简历做预览（优先于内置示例，低于显式传入的 content）。
    resume_id: int | None = Field(default=None, ge=1)
