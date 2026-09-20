"""服务端配置：全部集中在此，可通过环境变量 / .env 文件覆盖。

注意：这里只放服务端自身的配置；大模型 API 等用户运行时配置
在「设置」页中填写，保存在本地数据库，二者互不混淆。
"""
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[1]
# 数据目录：数据库、备份、导出、样例等本地产物都落在它下面。其它模块一律从这里推导子目录，
# 不各自去拼相对路径（拼错一处就会写到仓库里、被误提交）。
DATA_DIR = BACKEND_DIR / "data"
DEFAULT_DATABASE_URL = f"sqlite:///{(DATA_DIR / 'resume_forge.db').as_posix()}"


def captures_dir() -> Path:
    """站点原文样例的根目录：``<数据目录>/captures``。

    与 ``DEFAULT_DATABASE_URL`` 同源推导（都从 ``DATA_DIR`` 来），而不是在别处再拼一个
    相对路径。``backend/data/`` 已被 ``.gitignore`` 忽略，样例因此天然**不进仓库、不进备份**，
    也**不属于任何 dataset 目录**——它是排查产物，不该跟着数据集切换，更不该和投递浏览器的
    登录态（``backend/data/browser-profile/``）混在一起。
    """
    return DATA_DIR / "captures"

# 投递专用浏览器的 CDP 调试端口默认值。这是**唯一**的常量来源：
# schemas 的配置出厂默认与 browser_manager 的兜底默认都从这里取，避免两处各写一个 9333
# 而在改端口时漏改一处。运行期真正生效的端口由 ApplyConfig.browser_port 驱动。
DEFAULT_BROWSER_PORT = 9333


class Settings(BaseSettings):
    app_name: str = "ResumeForge"
    app_version: str = "0.9.0"

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
