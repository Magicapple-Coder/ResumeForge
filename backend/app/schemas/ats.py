"""ATS 本地检测的请求/响应 schema（R-10）。

三类结论：格式风险（format）/ 关键词覆盖（keyword）/ 信息位置（position）。结果里
强制携带 ``disclaimer``（本地规则估计，不代表真实 ATS 解析结果），前端必须展示。
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_JD_TEXT_CHARS = 50_000

AtsIssueCategory = Literal["format", "keyword", "position"]
AtsSeverity = Literal["high", "medium", "low"]

# 免责声明全文；测试会断言它逐字出现在响应里。
ATS_DISCLAIMER = "本地规则估计，不代表真实 ATS 解析结果"


class AtsCheckRequest(BaseModel):
    """ATS 检测请求。``jd_text`` 可选：提供后按 JD 命中的词库关键词检查覆盖。"""

    model_config = ConfigDict(extra="forbid")
    jd_text: str = Field(default="", max_length=MAX_JD_TEXT_CHARS)


class AtsIssue(BaseModel):
    category: AtsIssueCategory
    severity: AtsSeverity = "medium"
    title: str = ""
    detail: str = ""
    # 涉及的关键词 / 命中的符号，便于前端定位。
    evidence: list[str] = Field(default_factory=list, max_length=20)


class AtsCheckOut(BaseModel):
    resume_id: int
    issues: list[AtsIssue] = Field(default_factory=list)
    # 简历里已命中的关键词。
    matched_keywords: list[str] = Field(default_factory=list)
    # 未命中的关键词（JD 或通用词库）。
    missing_keywords: list[str] = Field(default_factory=list)
    # 0~100 的粗略估计分，仅作参考。
    score: int = Field(default=0, ge=0, le=100)
    disclaimer: str = ATS_DISCLAIMER
    summary: dict[str, int] = Field(default_factory=dict)


__all__ = [
    "ATS_DISCLAIMER",
    "AtsCheckOut",
    "AtsCheckRequest",
    "AtsIssue",
    "AtsIssueCategory",
    "AtsSeverity",
    "MAX_JD_TEXT_CHARS",
]
