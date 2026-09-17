"""服务端配置：全部集中在此，可通过环境变量 / .env 文件覆盖。

注意：这里只放服务端自身的配置；大模型 API 等用户运行时配置
在「设置」页中填写，保存在本地数据库，二者互不混淆。
"""
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_URL = f"sqlite:///{(BACKEND_DIR / 'data' / 'resume_forge.db').as_posix()}"


class Settings(BaseSettings):
    app_name: str = "ResumeForge"
    app_version: str = "0.8.0"

    # SQLite 文件路径（相对 backend 目录），目录不存在时自动创建
    database_url: str = DEFAULT_DATABASE_URL

    # 允许跨域的前端地址，英文逗号分隔
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_request_body_mb: int = Field(default=8, ge=1, le=64)

    # 备份上传单独放宽：恢复用的压缩包体积随用户数据增长，而请求体是流式落盘的，
    # 内存占用与包大小无关。其余接口仍受 max_request_body_mb 约束。
    max_backup_upload_mb: int = Field(default=512, ge=1, le=4096)

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("database_url")
    @classmethod
    def resolve_relative_sqlite_path(cls, value: str) -> str:
        prefix = "sqlite:///"
        if not value.startswith(prefix):
            return value
        database = value.removeprefix(prefix)
        if database == ":memory:" or database.startswith("file:"):
            return value
        path = Path(database)
        if path.is_absolute():
            return value
        return f"{prefix}{(BACKEND_DIR / path).resolve().as_posix()}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """全局唯一的配置实例（进程内缓存，环境变量只在启动时读取）。"""
    return Settings()
