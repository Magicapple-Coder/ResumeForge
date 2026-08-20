"""应用入口：装配中间件与路由、配置日志、启动时升级数据库。"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import models  # noqa: F401 - 确保全部模型注册到 Base.metadata
from .api import assistant, jobs, profile, resumes, search, settings as settings_api, stats
from .config import get_settings
from .database import Base, engine, ensure_sqlite_columns
from .database_migrations import is_unversioned_legacy_database, run_database_migrations
from .middleware import RequestContextMiddleware, RequestIdFilter, get_request_id

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] [request_id=%(request_id)s] %(message)s",
)
for handler in logging.getLogger().handlers:
    handler.addFilter(RequestIdFilter())

settings = get_settings()

SQLITE_REQUIRED_COLUMNS = {
    "job": {
        "note": "TEXT NOT NULL DEFAULT ''",
        "favorite": "BOOLEAN NOT NULL DEFAULT 0",
    },
    "user_profile": {
        "photo": "TEXT NOT NULL DEFAULT ''",
        "section_order": "TEXT NOT NULL DEFAULT '[]'",
    },
    "education": {
        "reference_file_name": "VARCHAR(255) NOT NULL DEFAULT ''",
        "reference_content": "TEXT NOT NULL DEFAULT ''",
    },
    "experience": {
        "reference_file_name": "VARCHAR(255) NOT NULL DEFAULT ''",
        "reference_content": "TEXT NOT NULL DEFAULT ''",
    },
    "campus_experience": {
        "reference_file_name": "VARCHAR(255) NOT NULL DEFAULT ''",
        "reference_content": "TEXT NOT NULL DEFAULT ''",
    },
    "project": {
        "reference_file_name": "VARCHAR(255) NOT NULL DEFAULT ''",
        "reference_content": "TEXT NOT NULL DEFAULT ''",
    },
    "resume_record": {
        "job_id": "INTEGER",
        "source": "VARCHAR(16) NOT NULL DEFAULT 'ai'",
        "enhancement_enabled": "BOOLEAN NOT NULL DEFAULT 0",
        "enhancement_level": "VARCHAR(16) NOT NULL DEFAULT 'balanced'",
    },
}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 只有早期未版本化数据库需要兼容建表/补列；空库与后续升级均由
    # Alembic 独立管理，避免 create_all 提前创建结构而掩盖 revision。
    if is_unversioned_legacy_database(engine):
        Base.metadata.create_all(bind=engine)
        ensure_sqlite_columns(engine, SQLITE_REQUIRED_COLUMNS)
    run_database_migrations(engine)
    yield


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)

app.add_middleware(
    RequestContextMiddleware,
    max_body_bytes=settings.max_request_body_mb * 1024 * 1024,
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
    search.router,
    stats.router,
    assistant.router,
):
    app.include_router(router)


@app.exception_handler(Exception)
async def unhandled_exception(_request: Request, exc: Exception):
    request_id = get_request_id()
    logging.getLogger(__name__).exception("未处理的请求异常", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "服务器处理请求时发生内部错误，请查看后端日志",
            "request_id": request_id,
        },
    )


@app.get("/api/health")
def health():
    return {"status": "ok", "name": settings.app_name, "version": settings.app_version}
