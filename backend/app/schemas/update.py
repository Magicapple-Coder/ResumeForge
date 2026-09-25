"""软件更新检查 Schema。"""
from datetime import datetime

from typing import Literal

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
    download_url: str = Field(default="", max_length=1024)
    download_size: int | None = Field(default=None, ge=0)
    asset_name: str = Field(default="", max_length=256)
    installable: bool = False


class UpdateDownloadRequest(BaseModel):
    """开始下载已检查到的版本。后台下载只影响程序临时目录。"""

    background: bool = False


class UpdateInstallRequest(BaseModel):
    """请求下载完成后安排覆盖安装并重启。"""

    restart: bool = True


class UpdateStatus(BaseModel):
    """应用内更新任务的可轮询状态。"""

    state: Literal["idle", "downloading", "ready", "installing", "failed"] = "idle"
    current_version: str = ""
    target_version: str = ""
    progress: float = Field(default=0, ge=0, le=100)
    downloaded_bytes: int = Field(default=0, ge=0)
    total_bytes: int | None = Field(default=None, ge=0)
    background: bool = False
    installable: bool = False
    message: str = Field(default="", max_length=1000)
