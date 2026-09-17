"""FastAPI 应用装配与生命周期配置。"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import models  # noqa: F401 - 确保全部模型注册到 Base.metadata
from .api import (
    apply,
    assistant,
    candidate_jobs,
    claims,
    datasets,
    drill,
    interview,
    job_match,
    jobs,
    materials,
    profile,
    resume_templates as resume_templates_api,
    resumes,
    search,
    settings as settings_api,
    skills,
    stats,
    system as system_api,
    tracker,
    update as update_api,
)
from . import database
from .config import get_settings
from .database import Base, ensure_sqlite_columns
from .database_compat import SQLITE_REQUIRED_COLUMNS
from .database_migrations import is_unversioned_legacy_database, run_database_migrations
from .middleware import RequestContextMiddleware, RequestIdFilter, get_request_id
from .services.apply import apply_service
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
    # 用属性访问而不是按值导入：切换数据集会重建 engine，按值引用会指向旧库。
    bind = database.engine
    if is_unversioned_legacy_database(bind):
        Base.metadata.create_all(bind=bind)
        ensure_sqlite_columns(bind, SQLITE_REQUIRED_COLUMNS)
    run_database_migrations(bind)
    # 上次运行若中途退出，可能留下未应用的备份包与导出产物，它们不会再用到。
    cleanup_temp_directories(bind)
    # 应用重启后，把仍停留在"进行中"的投递/采集任务标记为失败，避免出现幽灵进度。
    with database.SessionLocal() as session:
        try:
            apply_service.fail_orphaned_tasks(session)
        except Exception:  # noqa: BLE001 - 清理失败不应阻断启动
            logging.getLogger(__name__).warning("清理中断的投递/采集任务失败", exc_info=True)
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
            datasets.IMPORT_PATH: settings.max_backup_upload_mb * 1024 * 1024,
            skills.IMPORT_PATH: settings.max_backup_upload_mb * 1024 * 1024,
        },
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
        # 默认只有简单响应头能被前端读到：导出 PDF 的页数/上限、以及附件文件名都靠
        # 自定义头回传，不在这里放行的话跨源部署下前端永远读到 null。
        expose_headers=[
            resumes.PDF_PAGES_HEADER,
            resumes.PDF_PAGE_LIMIT_HEADER,
            "Content-Disposition",
        ],
    )
    for router in (
        jobs.router,
        job_match.router,
        resumes.router,
        resume_templates_api.router,
        profile.router,
        materials.router,
        candidate_jobs.router,
        claims.router,
        drill.router,
        interview.router,
        apply.router,
        apply.collect_router,
        tracker.router,
        settings_api.router,
        datasets.router,
        skills.router,
        search.router,
        stats.router,
        system_api.router,
        update_api.router,
        assistant.router,
    ):
        app.include_router(router)
    app.add_exception_handler(Exception, unhandled_exception)
    app.add_api_route("/api/health", health, methods=["GET"])
    return app


app = create_app()
