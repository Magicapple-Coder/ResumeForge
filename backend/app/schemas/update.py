"""软件更新检查 Schema。"""
from datetime import datetime

from pydantic import BaseModel, Field


class UpdateCheckResult(BaseModel):
    """检查结果。网络不可用时 ``message`` 给出原因，其余字段留空。"""

    current_version: str = ""
    latest_version: str = ""
    update_available: bool = False
    release_name: str = Field(default="", max_length=256)
    release_url: str = Field(default="", max_length=512)
    published_at: str = Field(default="", max_length=64)
    notes: str = Field(default="", max_length=4000)
    message: str = Field(default="", max_length=1000)
    checked_at: datetime | None = None
