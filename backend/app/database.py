"""数据库连接与会话管理。

选用 SQLite：单用户本地应用，零部署成本；后续需要多用户时
换 PostgreSQL 只需改 DATABASE_URL 并替换 JSON 列写法。
"""
from collections.abc import Mapping
from pathlib import Path

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import get_settings

settings = get_settings()

# SQLite 文件所在目录不存在时自动创建
if settings.database_url.startswith("sqlite:///"):
    db_path = Path(settings.database_url.removeprefix("sqlite:///"))
    db_path.parent.mkdir(parents=True, exist_ok=True)

_is_sqlite = settings.database_url.startswith("sqlite")
_is_memory_sqlite = settings.database_url in {"sqlite://", "sqlite:///:memory:"}
engine_options = {
    # FastAPI 在线程池中运行同步接口，SQLite 需要允许跨线程共用连接
    "connect_args": {"check_same_thread": False} if _is_sqlite else {},
}
if _is_memory_sqlite:
    # 内存库默认按线程分配连接；StaticPool 才能让 lifespan、请求和测试
    # 线程看到同一份数据库内容。
    engine_options["poolclass"] = StaticPool

engine = create_engine(settings.database_url, **engine_options)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        """SQLite 默认不启用外键约束，显式打开以保证级联删除等行为正确。"""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def ensure_sqlite_columns(
    bind: Engine,
    required_columns: Mapping[str, Mapping[str, str]],
) -> None:
    """为已有 SQLite 表补充缺失列；重复执行不会改动现有结构或数据。

    ``create_all`` 只会创建缺失的表，不会升级旧表。这里保留一个最小的
    列级兼容层；列定义来自代码内的可信常量，不接受用户输入。
    """
    if bind.dialect.name != "sqlite":
        return

    quote = bind.dialect.identifier_preparer.quote
    with bind.begin() as connection:
        inspector = inspect(connection)
        existing_tables = set(inspector.get_table_names())
        for table_name, columns in required_columns.items():
            if table_name not in existing_tables:
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, column_ddl in columns.items():
                if column_name in existing_columns:
                    continue
                connection.exec_driver_sql(
                    f"ALTER TABLE {quote(table_name)} ADD COLUMN {quote(column_name)} {column_ddl}"
                )
                existing_columns.add(column_name)


def get_db():
    """FastAPI 依赖：每个请求一个独立会话，请求结束自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
