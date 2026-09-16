"""简历 Schema：生成请求、LLM 输出结构、历史记录。"""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .profile import validate_photo_data_url


MAX_RESUME_SECTION_ITEMS = 200
MAX_RESUME_LIST_ITEMS = 500
MAX_RESUME_TEXT_CHARS = 50_000
ResumeLine = Annotated[str, Field(max_length=20_000)]


# 版式参数：最大篇幅（A4 页数）、字号档位、模板。默认 1 页 + 标准字号。
MAX_RESUME_PAGES = 3
ResumeFontScale = Literal["small", "standard", "large"]
MIN_CUSTOM_INSTRUCTION_CHARS = 0
MAX_CUSTOM_INSTRUCTION_CHARS = 2000


class GenerateOptions(BaseModel):
    """控制是否允许模型基于已有事实做岗位导向的改写和拓展，以及输出篇幅。"""

    model_config = ConfigDict(extra="forbid")
    enhance: bool = False
    enhancement_level: Literal["light", "balanced", "strong"] = "balanced"
    # 目标篇幅：默认 1 页 A4。塞不下时用户可在预览页加大页数或缩小字号后重新渲染。
    page_limit: int = Field(default=1, ge=1, le=MAX_RESUME_PAGES)
    font_scale: ResumeFontScale = "standard"
    template: str = Field(default="classic", max_length=32)
    # 用户自己补充的生成要求；只作为附加上下文，不会覆盖系统提示里的防虚构规则。
    custom_instruction: str = Field(default="", max_length=MAX_CUSTOM_INSTRUCTION_CHARS)


class GenerateRequest(BaseModel):
    """生成请求。``job_id`` 为空表示生成**通用简历**（不针对任何岗位）。"""

    job_id: int | None = Field(default=None, ge=1)
    title: str = Field(default="", max_length=256)
    options: GenerateOptions = GenerateOptions()


# ===== 简历内容结构（LLM 输出的 JSON 必须符合此结构） =====
# 与个人资料的差异：多行文本拆成了数组，更利于模型逐条输出与后续渲染。
class ResumeEducation(BaseModel):
    school: str = Field(default="", max_length=128)
    major: str = Field(default="", max_length=128)
    degree: str = Field(default="", max_length=32)
    start_date: str = Field(default="", max_length=32)
    end_date: str = Field(default="", max_length=32)
    gpa: str = Field(default="", max_length=64)
    courses: list[ResumeLine] = Field(default_factory=list, max_length=MAX_RESUME_LIST_ITEMS)
    achievements: list[ResumeLine] = Field(default_factory=list, max_length=MAX_RESUME_LIST_ITEMS)


class ResumeExperience(BaseModel):
    company: str = Field(default="", max_length=128)
    role: str = Field(default="", max_length=128)
    start_date: str = Field(default="", max_length=32)
    end_date: str = Field(default="", max_length=32)
    description: list[ResumeLine] = Field(default_factory=list, max_length=MAX_RESUME_LIST_ITEMS)


class ResumeCampusExperience(BaseModel):
    organization: str = Field(default="", max_length=128)
    role: str = Field(default="", max_length=128)
    start_date: str = Field(default="", max_length=32)
    end_date: str = Field(default="", max_length=32)
    description: list[ResumeLine] = Field(default_factory=list, max_length=MAX_RESUME_LIST_ITEMS)


class ResumeProject(BaseModel):
    name: str = Field(default="", max_length=128)
    role: str = Field(default="", max_length=128)
    start_date: str = Field(default="", max_length=32)
    end_date: str = Field(default="", max_length=32)
    tech_stack: list[ResumeLine] = Field(default_factory=list, max_length=MAX_RESUME_LIST_ITEMS)
    description: list[ResumeLine] = Field(default_factory=list, max_length=MAX_RESUME_LIST_ITEMS)
    highlights: list[ResumeLine] = Field(default_factory=list, max_length=MAX_RESUME_LIST_ITEMS)


class ResumeSkill(BaseModel):
    name: str = Field(default="", max_length=128)
    level: str = Field(default="", max_length=64)


class ResumeAward(BaseModel):
    name: str = Field(default="", max_length=256)
    date: str = Field(default="", max_length=32)
    description: str = Field(default="", max_length=20_000)


class ResumeContent(BaseModel):
    name: str = Field(default="", max_length=128)
    photo: str = ""
    gender: str = Field(default="", max_length=64)
    birth_year: str = Field(default="", max_length=32)
    phone: str = Field(default="", max_length=32)
    email: str = Field(default="", max_length=128)
    city: str = Field(default="", max_length=64)
    job_intent: str = Field(default="", max_length=128)
    summary: str = Field(default="", max_length=MAX_RESUME_TEXT_CHARS)
    education: list[ResumeEducation] = Field(default_factory=list, max_length=MAX_RESUME_SECTION_ITEMS)
    experience: list[ResumeExperience] = Field(default_factory=list, max_length=MAX_RESUME_SECTION_ITEMS)
    campus_experience: list[ResumeCampusExperience] = Field(
        default_factory=list, max_length=MAX_RESUME_SECTION_ITEMS
    )
    projects: list[ResumeProject] = Field(default_factory=list, max_length=MAX_RESUME_SECTION_ITEMS)
    skills: list[ResumeSkill] = Field(default_factory=list, max_length=MAX_RESUME_SECTION_ITEMS)
    awards: list[ResumeAward] = Field(default_factory=list, max_length=MAX_RESUME_SECTION_ITEMS)

    @field_validator("photo")
    @classmethod
    def photo_must_be_safe_image(cls, value: str) -> str:
        return validate_photo_data_url(value)


class ManualResumeRequest(BaseModel):
    """用户手写简历的保存请求；内容仍使用统一的结构化格式。"""

    model_config = ConfigDict(extra="forbid")
    job_id: int | None = Field(default=None, ge=1)
    title: str = Field(default="", max_length=256)
    content: ResumeContent


class ResumeBrief(BaseModel):
    """列表页不携带完整 content，避免大 JSON 反复传输。"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    job_id: int | None = None
    job_title: str
    company: str
    source: Literal["ai", "manual"] = "ai"
    favorite: bool = False
    model: str
    enhancement_enabled: bool
    enhancement_level: Literal["light", "balanced", "strong"]
    # 生成/最近一次渲染时使用的版式参数，重新打开预览或导出时保持一致。
    template: str = "classic"
    page_limit: int = 1
    font_scale: ResumeFontScale = "standard"
    created_at: datetime


class ResumeOut(ResumeBrief):
    content: ResumeContent
    warnings: list[str] = []
    parse_error: str = ""


class ResumeFavoriteUpdate(BaseModel):
    """只更新收藏状态，避免切换收藏时覆盖整份简历内容。"""

    favorite: bool


class ResumeTitleUpdate(BaseModel):
    """只更新简历名称，避免重命名时覆盖整份简历内容。"""

    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=256)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("简历名称不能为空")
        return cleaned


class ResumeSuggestion(BaseModel):
    """岗位化修改建议；每条建议都必须能回溯到简历或 JD 中的事实。"""

    priority: Literal["high", "medium", "low"] = "medium"
    section: str = Field(default="", max_length=128)
    issue: str = Field(default="", max_length=10_000)
    suggestion: str = Field(default="", max_length=10_000)
    evidence: list[Annotated[str, Field(max_length=2000)]] = Field(
        default_factory=list, max_length=20
    )


class ResumeSuggestionsOut(BaseModel):
    job_id: int
    job_title: str
    company: str
    suggestions: list[ResumeSuggestion] = Field(default_factory=list, max_length=20)


class ResumeRenderRequest(BaseModel):
    """生成完成后、未落库前的即时预览渲染；版式参数可选，缺省用默认单页标准字号。"""

    model_config = ConfigDict(extra="forbid")

    content: ResumeContent
    template: str = Field(default="classic", max_length=32)
    page_limit: int = Field(default=1, ge=1, le=MAX_RESUME_PAGES)
    font_scale: ResumeFontScale = "standard"


class ResumeLayoutUpdate(BaseModel):
    """只调整已有记录的版式参数，不重新生成内容。"""

    model_config = ConfigDict(extra="forbid")

    template: str = Field(default="classic", max_length=32)
    page_limit: int = Field(default=1, ge=1, le=MAX_RESUME_PAGES)
    font_scale: ResumeFontScale = "standard"
