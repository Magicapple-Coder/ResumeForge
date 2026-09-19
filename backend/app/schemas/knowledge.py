"""知识库条目（E4）的请求/响应结构。

知识库与资料箱的区别：资料箱是「还没归档的零散材料」，知识库是「整理好、愿意反复查阅的
成文内容」——面经总结、简历技巧、求职策略、行业笔记等。正文允许 Markdown 长文，列表检索
按标题/正文命中，分类给一组内置常量作起点、仍允许自定义。
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# 与 ``models/knowledge_entry.py`` 的列定义保持一致（服务端 schema 仍是权威校验）。
MAX_KNOWLEDGE_TITLE_CHARS = 200
MAX_KNOWLEDGE_CATEGORY_CHARS = 32
MAX_KNOWLEDGE_SOURCE_CHARS = 64
# 正文是 Markdown 长文，上限给得比资料箱更宽松，但仍在请求体上限之内。
MAX_KNOWLEDGE_CONTENT_CHARS = 200_000
# 标签数量与单条长度：标签是检索维度，不是自由文本，限长避免列表被撑爆。
MAX_KNOWLEDGE_TAGS = 20
MAX_KNOWLEDGE_TAG_CHARS = 32

# 内置分类：给用户一个起点，仍允许自定义文本（与资料箱 MATERIAL_CATEGORIES 同一取舍）。
KNOWLEDGE_CATEGORIES = (
    "面经",
    "简历技巧",
    "求职策略",
    "面试问答",
    "公司信息",
    "行业知识",
    "其他",
)


def _clean_tags(value: list[str]) -> list[str]:
    """标签清洗：去空白、去空项、去重（保序），超长单个标签直接拒绝。"""
    cleaned: list[str] = []
    for tag in value:
        item = (tag or "").strip()
        if not item:
            continue
        if len(item) > MAX_KNOWLEDGE_TAG_CHARS:
            raise ValueError(f"单个标签不能超过 {MAX_KNOWLEDGE_TAG_CHARS} 字")
        if item not in cleaned:
            cleaned.append(item)
    return cleaned


class KnowledgeCreate(BaseModel):
    """新增一条知识库条目。标题必填，其余字段给合理默认值。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=MAX_KNOWLEDGE_TITLE_CHARS)
    category: str = Field(default="其他", max_length=MAX_KNOWLEDGE_CATEGORY_CHARS)
    tags: list[str] = Field(default_factory=list, max_length=MAX_KNOWLEDGE_TAGS)
    content: str = Field(default="", max_length=MAX_KNOWLEDGE_CONTENT_CHARS)
    source: str = Field(default="手动录入", max_length=MAX_KNOWLEDGE_SOURCE_CHARS)

    @field_validator("tags")
    @classmethod
    def tags_must_be_clean(cls, value: list[str]) -> list[str]:
        return _clean_tags(value)

    @model_validator(mode="after")
    def normalize_and_require_title(self) -> "KnowledgeCreate":
        self.title = self.title.strip()
        self.category = self.category.strip() or "其他"
        self.source = self.source.strip() or "手动录入"
        if not self.title:
            raise ValueError("请填写标题")
        return self


class KnowledgeUpdate(KnowledgeCreate):
    """PUT 语义：整体替换一条知识库条目。"""


class KnowledgeOut(KnowledgeCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


__all__ = [
    "KNOWLEDGE_CATEGORIES",
    "MAX_KNOWLEDGE_CATEGORY_CHARS",
    "MAX_KNOWLEDGE_CONTENT_CHARS",
    "MAX_KNOWLEDGE_SOURCE_CHARS",
    "MAX_KNOWLEDGE_TAG_CHARS",
    "MAX_KNOWLEDGE_TAGS",
    "MAX_KNOWLEDGE_TITLE_CHARS",
    "KnowledgeCreate",
    "KnowledgeOut",
    "KnowledgeUpdate",
]
