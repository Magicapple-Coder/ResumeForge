"""AI 求职助手请求、会话和消息结构。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .material import MAX_MATERIAL_TITLE_CHARS

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


# 思考强度："" 表示不发送该参数（沿用服务商默认），其余透传给支持推理的模型。
REASONING_EFFORTS = ("", "none", "low", "medium", "high")
ReasoningEffort = Literal["", "none", "low", "medium", "high"]


class AssistantMessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(default="", max_length=MAX_ASSISTANT_MESSAGE_CHARS)
    job_id: int | None = Field(default=None, ge=1)
    resume_id: int | None = Field(default=None, ge=1)
    # 保留字段是为了兼容旧版客户端，但现在助手默认读取本地完整个人资料，前端不再提供
    # 关闭开关。无论旧客户端传 false 还是新客户端省略，都在校验后归一为 True。
    include_profile: bool = True
    web_search: bool = False
    # 有思考模式的大模型可以在这里调整推理强度；不支持该参数的服务商会被忽略。
    reasoning_effort: ReasoningEffort = ""
    # 「引用某条消息追问」：指向同一会话里的某条消息，模型会在引用上下文中作答。
    quoted_message_id: int | None = Field(default=None, ge=1)
    attachments: list[AssistantAttachmentInput] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def require_content_or_attachment(self):
        self.content = self.content.strip()
        self.include_profile = True
        if not self.content and not self.attachments:
            raise ValueError("请输入问题或添加附件")
        return self


class ChatConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=120)
    # 为真时自动附上一条引导消息（介绍助手功能与用法），用于首次进入创建默认会话。
    welcome: bool = False


class ChatConversationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=120)
    pinned: bool | None = None
    favorite: bool | None = None
    archived: bool | None = None
    # 分组名（"移动到项目"）；空串表示移出分组。
    group_name: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def require_update(self):
        if all(
            value is None
            for value in (self.title, self.pinned, self.favorite, self.archived, self.group_name)
        ):
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

    @field_validator("group_name")
    @classmethod
    def group_name_must_be_clean(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return " ".join(value.split())[:64]


class ChatConversationForkRequest(BaseModel):
    """「在新对话中继续」：把原会话最近若干条消息复制成一段新会话。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=120)
    message_limit: int = Field(default=10, ge=1, le=40)


class ChatMessageDeleteRequest(BaseModel):
    """批量删除消息（一次最多 200 条）。"""

    model_config = ConfigDict(extra="forbid")

    message_ids: list[int] = Field(min_length=1, max_length=200)

    @field_validator("message_ids")
    @classmethod
    def ids_must_be_unique(cls, value: list[int]) -> list[int]:
        return list(dict.fromkeys(value))


class ChatMessageDeleteResult(BaseModel):
    deleted: int


class ConversationToMaterialRequest(BaseModel):
    """把一段对话存进资料箱（内容用导出的 Markdown，助手之后能直接读它）。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=MAX_MATERIAL_TITLE_CHARS)
    category: str = Field(default="", max_length=64)
    note: str = Field(default="", max_length=1000)


class ChatAttachmentOut(BaseModel):
    name: str
    mime_type: str
    # document：PDF/DOCX 等文档，文字已在本地提取进 ``text``，原始文件不外发。
    kind: Literal["text", "image", "document"]
    size_bytes: int
    text: str = ""
    data_url: str = ""
    # 提取过程中的说明（例如内容过长只取了前一部分）；目前只有文档会产生。
    notes: list[str] = Field(default_factory=list)


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: Literal["user", "assistant"]
    content: str
    # 引用的消息 id（被引用消息删除后为 None，但 context.quoted 里仍有快照）。
    quoted_message_id: int | None = None
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
    archived: bool = False
    group_name: str = ""
    # 列表里展示条数与最后活动时间，方便区分同名会话。
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


class ChatConversationDetail(ChatConversationBrief):
    messages: list[ChatMessageOut] = Field(default_factory=list)
