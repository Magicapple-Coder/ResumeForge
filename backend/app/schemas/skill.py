"""助手技能 Schema。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


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


class AssistantSkillUpdate(BaseModel):
    """目前只支持切换启用状态。"""

    enabled: bool
