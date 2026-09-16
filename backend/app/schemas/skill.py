"""助手技能 Schema：列表项、详情、创建与更新。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_SKILL_NAME_CHARS = 64
MAX_SKILL_DESCRIPTION_CHARS = 255
MAX_SKILL_PROMPT_CHARS = 200_000
MAX_SKILL_FILE_CHARS = 200_000
MAX_SKILL_FILES = 50
MAX_SKILL_FILE_PATH_CHARS = 255


class AssistantSkillFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=MAX_SKILL_FILE_PATH_CHARS)
    content: str = Field(default="", max_length=MAX_SKILL_FILE_CHARS)

    @field_validator("path")
    @classmethod
    def path_must_be_flat(cls, value: str) -> str:
        """知识文件名只允许一层，且不能带路径符号——读取时直接按名字匹配。"""
        value = value.strip().replace("\\", "/")
        if "/" in value or value in {".", ".."} or ":" in value:
            raise ValueError("知识文件名不能包含路径")
        if not value:
            raise ValueError("知识文件名不能为空")
        return value


# 详情接口一次最多回传多少知识文件正文；超出后只回文件名，避免一个超大技能包
# 把响应撑到几十 MB（工作台编辑时会用到正文，所以不能只给清单）。
MAX_SKILL_DETAIL_FILE_CHARS = 200_000


class AssistantSkillFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    path: str
    size_bytes: int
    content: str = ""


class AssistantSkillOut(BaseModel):
    """技能列表项。``prompt`` 正文不回传：列表只需要展示元信息。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    enabled: bool
    source_name: str
    prompt_chars: int
    files: list[str]
    updated_at: datetime


class AssistantSkillDetail(AssistantSkillOut):
    """技能详情：查看与编辑都需要提示词正文和文件内容。"""

    prompt: str = ""
    file_details: list[AssistantSkillFileOut] = Field(default_factory=list)
    # 为真表示有知识文件因超出上限没带正文；前端此时不要覆盖式提交 files，
    # 否则会把没加载到的内容写丢。
    files_truncated: bool = False


class AssistantSkillCreate(BaseModel):
    """在工作台里手工创建技能。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_SKILL_NAME_CHARS)
    description: str = Field(default="", max_length=MAX_SKILL_DESCRIPTION_CHARS)
    prompt: str = Field(default="", max_length=MAX_SKILL_PROMPT_CHARS)
    enabled: bool = True
    files: list[AssistantSkillFileInput] = Field(default_factory=list, max_length=MAX_SKILL_FILES)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("技能名称不能为空")
        return value

    def require_prompt(self) -> "AssistantSkillCreate":
        if not self.prompt.strip():
            raise ValueError("请填写技能提示词：它决定这个技能让助手怎么做")
        return self


class AssistantSkillUpdate(BaseModel):
    """更新技能；只提交要改的字段。``files`` 提交时整体替换。"""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=MAX_SKILL_NAME_CHARS)
    description: str | None = Field(default=None, max_length=MAX_SKILL_DESCRIPTION_CHARS)
    prompt: str | None = Field(default=None, max_length=MAX_SKILL_PROMPT_CHARS)
    enabled: bool | None = None
    files: list[AssistantSkillFileInput] | None = Field(default=None, max_length=MAX_SKILL_FILES)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank_when_set(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        if not value:
            raise ValueError("技能名称不能为空")
        return value
