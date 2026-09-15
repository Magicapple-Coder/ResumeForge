"""数据备份 Schema。"""
from pydantic import BaseModel, Field


class BackupApplyRequest(BaseModel):
    """用上传阶段返回的一次性 token 关联到具体的备份包。"""

    token: str = Field(min_length=32, max_length=32)
