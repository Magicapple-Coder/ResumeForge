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
from .dataset_registry import DatasetError, active_database_file

settings = get_settings()


def database_url_for(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    """SQLite 默认不启用外键约束，显式打开以保证级联删除等行为正确。

    这个监听器是**绑定在 Engine 实例上**的，所以每次新建引擎都必须重新注册；
    漏掉的话新数据集的外键级联会静默失效。
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def build_engine(database_url: str) -> Engine:
    is_sqlite = database_url.startswith("sqlite")
    options: dict = {
        # FastAPI 在线程池中运行同步接口，SQLite 需要允许跨线程共用连接
        "connect_args": {"check_same_thread": False} if is_sqlite else {},
    }
    if database_url in {"sqlite://", "sqlite:///:memory:"}:
        # 内存库默认按线程分配连接；StaticPool 才能让 lifespan、请求和测试
        # 线程看到同一份数据库内容。
        options["poolclass"] = StaticPool
    built = create_engine(database_url, **options)
    if is_sqlite:
        event.listen(built, "connect", _enable_sqlite_foreign_keys)
    return built


# 启动时连接当前激活的数据集（指针缺失时即 DATABASE_URL 指向的「主数据」）。
if settings.database_url.startswith("sqlite:///"):
    _configured = Path(settings.database_url.removeprefix("sqlite:///"))
    _configured.parent.mkdir(parents=True, exist_ok=True)
try:
    _initial_url = database_url_for(active_database_file())
except DatasetError:
    # 指针损坏或指向的文件缺失：退回配置里的库，让应用还能起得来并让用户
    # 到设置页处理，而不是直接启动失败。
    _initial_url = settings.database_url

engine = build_engine(_initial_url)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def rebind(database_path: Path) -> Engine:
    """把全局引擎切换到另一个数据库文件。

    ``engine`` 与 ``SessionLocal`` 的改法不同，这是有意为之：

    - ``engine`` 的 URL 在建引擎时就固化进了连接池的 creator 闭包，改
      ``engine.url`` 不会改变实际连接的文件，所以必须**新建引擎对象**并替换
      模块属性。代价是那些按值导入 ``engine`` 的模块要改成属性访问。
    - ``SessionLocal`` 用 ``configure`` 原地改绑，**对象 identity 不变**，于是
      「按值导入 SessionLocal」的模块（助手流式写入、简历保存）自动跟随，
      一行都不用改。
    """
    global engine
    database_path.parent.mkdir(parents=True, exist_ok=True)
    engine.dispose()
    engine = build_engine(database_url_for(database_path))
    SessionLocal.configure(bind=engine)
    return engine


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
