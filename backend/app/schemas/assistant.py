"""AI 求职助手请求、会话和消息结构。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_ASSISTANT_MESSAGE_CHARS = 20_000
MAX_ATTACHMENT_DATA_CHARS = 7_100_000


class AssistantAttachmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(default="", max_length=100)
    data: str = Field(min_length=1, max_length=MAX_ATTACHMENT_DATA_CHARS)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("附件名称无效")
        return value


class AssistantMessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(default="", max_length=MAX_ASSISTANT_MESSAGE_CHARS)
    job_id: int | None = Field(default=None, ge=1)
    resume_id: int | None = Field(default=None, ge=1)
    include_profile: bool = False
    web_search: bool = False
    attachments: list[AssistantAttachmentInput] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def require_content_or_attachment(self):
        self.content = self.content.strip()
        if not self.content and not self.attachments:
            raise ValueError("请输入问题或添加附件")
        return self


class ChatConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=120)


class ChatConversationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=120)
    pinned: bool | None = None
    favorite: bool | None = None

    @model_validator(mode="after")
    def require_update(self):
        if self.title is None and self.pinned is None and self.favorite is None:
            raise ValueError("至少提供一个要修改的会话字段")
        return self

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        if not value:
            raise ValueError("会话标题不能为空")
        return value


class ChatAttachmentOut(BaseModel):
    name: str
    mime_type: str
    kind: Literal["text", "image"]
    size_bytes: int
    text: str = ""
    data_url: str = ""


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: Literal["user", "assistant"]
    content: str
    attachments: list[ChatAttachmentOut] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    status: Literal["pending", "complete", "error", "cancelled"]
    error: str = ""
    model: str = ""
    created_at: datetime


class ChatConversationBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    pinned: bool
    favorite: bool
    created_at: datetime
    updated_at: datetime


class ChatConversationDetail(ChatConversationBrief):
    messages: list[ChatMessageOut] = Field(default_factory=list)
