"""导出与脱敏的请求 Schema（R-16 / R-17）。

``ExportRequest`` 是 ``POST /api/resumes/{id}/export`` 的请求体，字段与
``services/export_pipeline.ExportRequest``（内部 dataclass）一一对应，由 API 层转换。
``RedactionOptions`` 是 ``services/privacy.py::RedactionOptions``（内部 dataclass）的
Pydantic 镜像，作为脱敏预览接口的请求体；脱敏规则本身仍只有 ``privacy.redact`` 一份
实现，这里只负责把 HTTP 请求的字段白名单化（``extra="forbid"`` 防注入多余参数）。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .resume import MAX_RESUME_PAGES, ResumeFontScale

ExportFormat = Literal["json", "md", "html", "pdf", "docx", "txt"]


class RedactionOptions(BaseModel):
    """脱敏范围。默认遮罩可直接识别身份的四项，其余按需开启（与 privacy 默认值逐字一致）。"""

    model_config = ConfigDict(extra="forbid")

    mask_name: bool = True
    mask_phone: bool = True
    mask_email: bool = True
    mask_company: bool = True
    mask_school: bool = False
    mask_project: bool = False
    mask_product: bool = False


class ExportRequest(BaseModel):
    """全参数导出请求体。缺省项回退到记录里存的版式 / 不做后处理。"""

    model_config = ConfigDict(extra="forbid")

    format: ExportFormat = "pdf"
    watermark: str = Field(default="", max_length=200)
    redact: bool = False
    redact_options: RedactionOptions = Field(default_factory=RedactionOptions)
    # 页边距直接覆盖（mm）：None 表示用记录里的版式（模板默认或 format_config.page_padding）。
    margin_mm: float | None = Field(default=None, ge=4, le=40)
    # 字号 / 页数覆盖：None 表示沿用记录里存的值。
    font_scale: ResumeFontScale | None = None
    page_limit: int | None = Field(default=None, ge=1, le=MAX_RESUME_PAGES)
    include_photo: bool = True
    allow_incomplete: bool = False


__all__ = ["ExportFormat", "ExportRequest", "RedactionOptions"]
