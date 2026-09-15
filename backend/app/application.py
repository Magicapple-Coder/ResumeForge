"""FastAPI 应用装配与生命周期配置。"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import models  # noqa: F401 - 确保全部模型注册到 Base.metadata
from .api import (
    assistant,
    backup,
    jobs,
    profile,
    resumes,
    search,
    settings as settings_api,
    stats,
)
from .config import get_settings
from .database import Base, engine, ensure_sqlite_columns
from .database_compat import SQLITE_REQUIRED_COLUMNS
from .database_migrations import is_unversioned_legacy_database, run_database_migrations
from .middleware import RequestContextMiddleware, RequestIdFilter, get_request_id
from .services.data_backup import cleanup_temp_directories


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] [request_id=%(request_id)s] %(message)s",
)
# HTTPX 的 INFO 摘要包含完整 URL，可能暴露助手联网搜索词。
# 业务层会另行记录不含查询参数的主机、状态码和请求 ID。
logging.getLogger("httpx").setLevel(logging.WARNING)
for handler in logging.getLogger().handlers:
    handler.addFilter(RequestIdFilter())

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 只有早期未版本化数据库需要兼容建表/补列；空库与后续升级均由
    # Alembic 独立管理，避免 create_all 提前创建结构而掩盖 revision。
    if is_unversioned_legacy_database(engine):
        Base.metadata.create_all(bind=engine)
        ensure_sqlite_columns(engine, SQLITE_REQUIRED_COLUMNS)
    run_database_migrations(engine)
    # 上次运行若中途退出，可能留下未应用的备份包与导出产物，它们不会再用到。
    cleanup_temp_directories(engine)
    yield


async def unhandled_exception(_request: Request, exc: Exception):
    """将未处理异常转换为不泄露内部细节的统一响应。"""
    request_id = get_request_id()
    logging.getLogger(__name__).exception("未处理的请求异常", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "服务器处理请求时发生内部错误，请查看后端日志",
            "request_id": request_id,
        },
    )


def health():
    return {"status": "ok", "name": settings.app_name, "version": settings.app_version}


def create_app() -> FastAPI:
    """创建并装配应用；保留工厂便于离线测试和未来多实例部署。"""
    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    app.add_middleware(
        RequestContextMiddleware,
        max_body_bytes=settings.max_request_body_mb * 1024 * 1024,
        # 备份上传的体积随用户数据增长，且是流式落盘；其余接口维持原上限。
        larger_body_paths={
            backup.UPLOAD_PATH: settings.max_backup_upload_mb * 1024 * 1024,
        },
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for router in (
        jobs.router,
        resumes.router,
        profile.router,
        settings_api.router,
        backup.router,
        search.router,
        stats.router,
        assistant.router,
    ):
        app.include_router(router)
    app.add_exception_handler(Exception, unhandled_exception)
    app.add_api_route("/api/health", health, methods=["GET"])
    return app


app = create_app()
