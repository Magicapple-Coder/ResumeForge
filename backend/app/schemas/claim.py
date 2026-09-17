"""事实台账 Schema。

这里承担两类职责：

1. **结构校验**：字段长度、枚举取值、来源条目形状、日期格式。
2. **跨字段一致性**：只有一条硬规则——``已确认`` 的主张不得含未完成占位符。
   两者并存本身就是自相矛盾（"我已经核实过了，但这里待补"），必须挡在保存之前。

其余"建议改进"（例如强主张没填面试细节）走**服务端算出的 ``warnings``** 而不是保存失败：
它是提醒不是矛盾，硬拦会让用户放弃维护台账，反而拿不到这套规则的好处。
"""
from __future__ import annotations

import re
from datetime import datetime, date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..models.claim import (
    CLAIM_CATEGORIES,
    CLAIM_CATEGORY_OTHER,
    RESPONSIBILITY_LEVELS,
    VERIFICATION_CONFIRMED,
    VERIFICATION_STATUSES,
    has_placeholder,
    placeholder_hit,
)

MAX_CLAIM_TITLE_CHARS = 200
MAX_CLAIM_SUBJECT_CHARS = 200
MAX_CLAIM_TEXT_CHARS = 8_000
MAX_CLAIM_BOUNDARY_CHARS = 1_000
MAX_CLAIM_SOURCES = 10
MAX_CLAIM_ALLOWED_USES = 20
MAX_CLAIM_RISK_NOTES = 20
MAX_SOURCE_NOTE_CHARS = 500
MAX_ALLOWED_USE_CHARS = 100
MAX_RISK_NOTE_CHARS = 500
# 面试细节的每一条都有上限：它们是"能讲出来的东西"，不是第二份简历。
MAX_INTERVIEW_ITEM_CHARS = 1_000
MAX_INTERVIEW_ITEMS = 20

# 证据来源的类型。（界面上的下拉选项也由这份取值驱动。）
SOURCE_TYPES = (
    "pull_request",
    "repository",
    "document",
    "certificate",
    "link",
    "screenshot",
    "reference",
    "other",
)
SOURCE_TYPE_LABELS = {
    "pull_request": "合并请求 / PR",
    "repository": "代码仓库",
    "document": "文档 / 报告",
    "certificate": "证书 / 证明",
    "link": "公开链接",
    "screenshot": "截图",
    "reference": "可联系的人 / 推荐人",
    "other": "其他",
}

_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")


def _valid_calendar_date(value: str) -> bool:
    """``YYYY-MM-DD`` 且必须是真实存在的日历日（挡掉 2026-02-31 这类）。"""
    if not _DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


class ClaimSource(BaseModel):
    """一条证据来源：只放"去哪儿能找到"，不放内容本身。"""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(default="other", max_length=32)
    location: str = Field(default="", max_length=1_024)
    public: bool = False
    note: str = Field(default="", max_length=MAX_SOURCE_NOTE_CHARS)

    @field_validator("type")
    @classmethod
    def type_must_be_known(cls, value: str) -> str:
        cleaned = (value or "").strip() or "other"
        if cleaned not in SOURCE_TYPES:
            raise ValueError(f"未知的证据类型「{cleaned}」")
        return cleaned


def _clean_string_list(value: list[str], *, limit: int, label: str) -> list[str]:
    """去空白、丢空项、去重并保序——重复项只会让界面变乱，没有信息量。"""
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    if len(result) > limit:
        raise ValueError(f"{label}最多 {limit} 条")
    return result


class ClaimBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=MAX_CLAIM_TITLE_CHARS)
    category: str = Field(default=CLAIM_CATEGORY_OTHER, max_length=32)
    subject: str = Field(default="", max_length=MAX_CLAIM_SUBJECT_CHARS)
    source_fact: str = Field(default="", max_length=MAX_CLAIM_TEXT_CHARS)
    candidate_wording: str = Field(default="", max_length=MAX_CLAIM_TEXT_CHARS)
    sources: list[ClaimSource] = Field(default_factory=list, max_length=MAX_CLAIM_SOURCES)
    responsibility_level: str = Field(default=RESPONSIBILITY_LEVELS[0], max_length=32)
    verification_status: str = Field(default=VERIFICATION_STATUSES[1], max_length=16)
    allowed_uses: list[str] = Field(default_factory=list, max_length=MAX_CLAIM_ALLOWED_USES)
    interview_details: dict[str, Any] = Field(default_factory=dict)
    boundary: str = Field(default="", max_length=MAX_CLAIM_BOUNDARY_CHARS)
    risk_notes: list[str] = Field(default_factory=list, max_length=MAX_CLAIM_RISK_NOTES)
    last_verified: str = Field(default="", max_length=10)

    @field_validator("category")
    @classmethod
    def category_must_be_known(cls, value: str) -> str:
        cleaned = (value or "").strip() or CLAIM_CATEGORY_OTHER
        if cleaned not in CLAIM_CATEGORIES:
            raise ValueError(f"未知的分类「{cleaned}」")
        return cleaned

    @field_validator("responsibility_level")
    @classmethod
    def responsibility_must_be_known(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if cleaned not in RESPONSIBILITY_LEVELS:
            raise ValueError(f"未知的承担程度「{cleaned}」")
        return cleaned

    @field_validator("verification_status")
    @classmethod
    def verification_must_be_known(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if cleaned not in VERIFICATION_STATUSES:
            raise ValueError(f"未知的核实状态「{cleaned}」")
        return cleaned

    @field_validator("last_verified")
    @classmethod
    def last_verified_must_be_a_date(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            return ""
        if not _valid_calendar_date(cleaned):
            raise ValueError("最近核实日期要写成 2026-09-18 这样的真实日期，或留空")
        return cleaned

    @field_validator("allowed_uses")
    @classmethod
    def clean_allowed_uses(cls, value: list[str]) -> list[str]:
        return _clean_string_list(
            [str(item)[:MAX_ALLOWED_USE_CHARS] for item in value],
            limit=MAX_CLAIM_ALLOWED_USES,
            label="可用范围",
        )

    @field_validator("risk_notes")
    @classmethod
    def clean_risk_notes(cls, value: list[str]) -> list[str]:
        return _clean_string_list(
            [str(item)[:MAX_RISK_NOTE_CHARS] for item in value],
            limit=MAX_CLAIM_RISK_NOTES,
            label="风险备注",
        )

    @field_validator("interview_details")
    @classmethod
    def clean_interview_details(cls, value: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {"decisions": [], "difficulties": [], "verification": []}
        raw_result: Any = None
        for key in ("decisions", "difficulties", "verification", "result"):
            if key not in value:
                continue
            item = value[key]
            if key == "result":
                if item is not None:
                    # 只写空白等于没写：统一成 None，避免"看起来填了"却没有任何内容。
                    raw_result = str(item).strip()[:MAX_INTERVIEW_ITEM_CHARS] or None
                continue
            if not isinstance(item, list):
                raise ValueError(f"面试细节的「{key}」必须是列表")
            trimmed = [str(entry)[:MAX_INTERVIEW_ITEM_CHARS] for entry in item]
            result[key] = _clean_string_list(
                trimmed, limit=MAX_INTERVIEW_ITEMS, label=f"面试细节的「{key}」"
            )
        result["result"] = raw_result
        return result

    @model_validator(mode="after")
    def must_be_describable(self) -> "ClaimBase":
        """一条主张至少要写清"原始事实"或"准备怎么表述"，否则它没有内容可核对。"""
        self.title = self.title.strip()
        self.subject = self.subject.strip()
        self.source_fact = self.source_fact.strip()
        self.candidate_wording = self.candidate_wording.strip()
        self.boundary = self.boundary.strip()
        if not self.source_fact and not self.candidate_wording:
            raise ValueError("请至少填写原始事实或简历表述之一")
        return self

    @model_validator(mode="after")
    def confirmed_must_not_be_incomplete(self) -> "ClaimBase":
        """已确认的主张不能含未完成占位符——这两件事不能同时为真。"""
        if self.verification_status != VERIFICATION_CONFIRMED:
            return self
        for label, text in (
            ("原始事实", self.source_fact),
            ("简历表述", self.candidate_wording),
            ("个人边界", self.boundary),
        ):
            if has_placeholder(text):
                raise ValueError(
                    f"{label}里还有「{placeholder_hit(text)}」这样的未完成标记，"
                    "不能标记为「已确认」——请先补齐内容，或把状态改回「待确认」"
                )
        return self


class ClaimCreate(ClaimBase):
    pass


class ClaimUpdate(ClaimBase):
    """PUT 语义：整体替换一条主张。"""


class ClaimOut(ClaimBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    # 服务端算出的改进建议（不是保存失败）：例如强主张缺面试细节、已确认但没写个人边界。
    warnings: list[str] = Field(default_factory=list)


class ClaimListOut(BaseModel):
    """列表接口：条目 + 一份汇总，避免前端为了统计再拉一次全量。"""

    items: list[ClaimOut]
    total: int
    confirmed_count: int
    pending_count: int
    # 各分类的条目数，供界面上的筛选器显示数量。
    category_counts: dict[str, int] = Field(default_factory=dict)


class ClaimDigestOut(BaseModel):
    """给生成链路用的事实基线摘要（只含可进入正式材料的内容）。"""

    confirmed_count: int
    # 已确认主张的原始事实 + 边界，拼成可直接注入提示词的文本。
    baseline_text: str
    # 不可用主张的表述清单：生成时要显式避开这些说法。
    blocked_wording: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ClaimDraftRequest(BaseModel):
    """从一段资料草拟台账条目（不落库，用户确认后再保存）。"""

    model_config = ConfigDict(extra="forbid")

    category: str = Field(default=CLAIM_CATEGORY_OTHER, max_length=32)
    subject: str = Field(default="", max_length=MAX_CLAIM_SUBJECT_CHARS)
    # 用户提供的原始描述（某段经历、项目说明、获奖情况）。
    raw_text: str = Field(default="", max_length=MAX_CLAIM_TEXT_CHARS)

    @field_validator("category")
    @classmethod
    def category_must_be_known(cls, value: str) -> str:
        cleaned = (value or "").strip() or CLAIM_CATEGORY_OTHER
        if cleaned not in CLAIM_CATEGORIES:
            raise ValueError(f"未知的分类「{cleaned}」")
        return cleaned

    @model_validator(mode="after")
    def raw_text_must_have_content(self) -> "ClaimDraftRequest":
        """空资料直接拒绝：没有可拆的内容时返回空草稿只会让人以为"没提取出来"。"""
        self.raw_text = self.raw_text.strip()
        if not self.raw_text:
            raise ValueError("请先粘贴要整理的资料内容")
        return self


class ClaimDraftOut(BaseModel):
    drafts: list[ClaimCreate]
    # 无模型可用时的本地降级说明，或模型抽取失败的提示。
    notes: list[str] = Field(default_factory=list)


__all__ = [
    "ClaimCreate",
    "ClaimDigestOut",
    "ClaimDraftOut",
    "ClaimDraftRequest",
    "ClaimListOut",
    "ClaimOut",
    "ClaimSource",
    "ClaimUpdate",
    "MAX_CLAIM_TITLE_CHARS",
    "SOURCE_TYPES",
    "SOURCE_TYPE_LABELS",
]
