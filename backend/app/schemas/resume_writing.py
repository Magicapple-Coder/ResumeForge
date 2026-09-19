"""简历写作增强的请求/响应 schema（R-04~R-07）。

四个 LLM 变换（STAR 改写 / 话术生成器 / 多风格润色 / 中英互译）都是「一段文本进、
一段文本出」，结果直接回填到简历对应字段、零适配。版本对比则是两份简历的三态差异
（added / removed / unchanged），唯一实现见 ``services/resume_diff.py``。
"""
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

MAX_WRITING_TEXT_CHARS = 20_000


def _strip_writing_text(text: str) -> str:
    """去首尾空白并拦下纯空白输入。

    四个变换都是「一段文本进、一段文本出」，纯空白（只有空格 / 换行 / Tab）没有语义，
    交给模型只会浪费一次调用或得到与事实无关的输出，因此在 schema 层直接 422。
    """
    stripped = text.strip()
    if not stripped:
        raise ValueError("text 不能为空或纯空白")
    return stripped


# 四个变换共用的输入约束：长度上限 + 纯空白拦截。
WritingText = Annotated[
    str,
    Field(min_length=1, max_length=MAX_WRITING_TEXT_CHARS),
    AfterValidator(_strip_writing_text),
]


class StarRewriteRequest(BaseModel):
    """STAR 量化改写请求。

    ``claim_id`` 可选：提供时后端把该台账条目的候选表述与个人边界作为「不虚构事实」
    的约束上下文，改写不会越过事实边界。
    """

    model_config = ConfigDict(extra="forbid")
    text: WritingText
    claim_id: int | None = Field(default=None, ge=1)


class StarRewriteOut(BaseModel):
    result: str = ""


class PhrasesRequest(BaseModel):
    """话术生成器：同一段事实生成简历版 / STAR 版 / 面试口述版三种表达。"""

    model_config = ConfigDict(extra="forbid")
    text: WritingText
    modes: list[Literal["star", "resume", "interview"]] = Field(
        default_factory=lambda: ["star", "resume", "interview"], max_length=3
    )


class PhrasesOut(BaseModel):
    """三种版式；未请求的版式保持空串。"""

    star: str = ""
    resume: str = ""
    interview: str = ""


class PolishRequest(BaseModel):
    """多风格润色请求。``style`` 取值与前端枚举逐字一致。"""

    model_config = ConfigDict(extra="forbid")
    text: WritingText
    style: Literal["big_tech", "concise_tech", "campus"] = "concise_tech"


class PolishOut(BaseModel):
    result: str = ""


class TranslateRequest(BaseModel):
    """中英互译请求。``direction`` 取值与前端枚举逐字一致。"""

    model_config = ConfigDict(extra="forbid")
    text: WritingText
    direction: Literal["zh2en", "en2zh"] = "zh2en"


class TranslateOut(BaseModel):
    result: str = ""


class ResumeDiffRequest(BaseModel):
    """版本对比：把当前简历与 ``against_id`` 指向的那份简历做三态差异。"""

    model_config = ConfigDict(extra="forbid")
    against_id: int = Field(ge=1)


class DiffToken(BaseModel):
    """词级差异的最小单元。"""

    type: Literal["added", "removed", "unchanged"]
    text: str = ""


class DiffLine(BaseModel):
    """一行差异：整行三态 + 可选的行内词级三态（仅对「被改写」的成对行）。"""

    type: Literal["added", "removed", "unchanged"]
    text: str = ""
    tokens: list[DiffToken] = Field(default_factory=list)


class DiffStats(BaseModel):
    added: int = 0
    removed: int = 0
    unchanged: int = 0


class ResumeDiffOut(BaseModel):
    base_id: int
    against_id: int
    base_title: str = ""
    against_title: str = ""
    lines: list[DiffLine] = Field(default_factory=list)
    stats: DiffStats = DiffStats()
