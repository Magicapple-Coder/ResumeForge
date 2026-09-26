"""测试夹具：独立的文件型测试数据库 + 测试客户端。

必须在导入 app 之前设置 DATABASE_URL（config 在导入时读取一次）。

测试库放在**每个进程独立的目录**里，而不是共享的系统临时目录根下：数据集功能把
指针（active.json）与 datasets/ 目录都解析成"数据库所在目录"的子项，放在共享目录
会让不同测试运行互相看到对方的数据集。
"""
import os
import shutil
import sqlite3
from pathlib import Path
import tempfile

_TEST_DIR = Path(tempfile.gettempdir()) / f"resume_forge_test_{os.getpid()}"
_TEST_DIR.mkdir(parents=True, exist_ok=True)
_TEST_DB = _TEST_DIR / "resume_forge.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.as_posix()}"  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402

from app import database  # noqa: E402
from app.database import Base, SessionLocal, get_db  # noqa: E402
from app.dataset_registry import (  # noqa: E402
    MAIN_DATASET_ID,
    datasets_directory,
    write_active_dataset_id,
)
from app.main import app  # noqa: E402


@event.listens_for(Engine, "connect")
def _relax_test_database_durability(dbapi_connection, _connection_record) -> None:
    """关掉测试库的落盘同步——``clean_db`` 每个用例都重建 38 张表，而 fsync 是全部成本。

    实测（本机 Windows）``drop_all`` + ``create_all`` 一次要 **436 ms**，其中删表只占
    11 ms，剩下约 429 ms 全是 **建表**：38 张表连同索引，在 SQLite 默认的
    ``synchronous=FULL`` 下每条 DDL 都要 fsync 一次。这一个动作就占了单个用例总耗时的
    97%，也就是说**整个后端套件的运行时间几乎全是建表**。换成 ``journal_mode=MEMORY`` +
    ``synchronous=OFF`` 后是 **44.7 ms**（快 9.8 倍）。

    为什么必须动它：GitHub 的 Windows runner 磁盘慢、且带 Defender 实时防护，fsync 被
    放大了约 12 倍——实测每个用例 5.4 s（本机 0.46 s），2149 个用例跑 28 分钟才到 15%，
    外推要 **3.2 小时**，而后端 job 的超时是 30 分钟。加并行救不了这个：瓶颈是文件同步，
    4 个 worker 只是排队。

    为什么在测试里改是安全的：这两项只影响**断电时能否恢复**，不影响任何一条 SQL 的语义、
    隔离级别或约束。测试库随会话结束整个删掉（见 ``cleanup_test_db``），没有需要扛住崩溃
    的数据；生产引擎的持久性由 ``app/database.build_engine`` 决定，这里碰不到它。

    监听器挂在 ``Engine`` **类**上而不是实例上：``database.rebind()`` 换数据集时会新建引擎
    对象，挂在实例上的监听器会漏掉那些新引擎。
    """
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    try:
        # journal_mode 会返回一行结果，必须取走，否则连接上会留着一个未读完的语句。
        cursor.execute("PRAGMA journal_mode=MEMORY")
        cursor.fetchone()
        cursor.execute("PRAGMA synchronous=OFF")
    finally:
        cursor.close()


def _reset_to_test_database() -> None:
    """把活动指针与引擎复位到测试库本身。

    数据集用例会切换引擎，不复位的话，一个用例切到的数据集会被后续用例继续使用。
    引擎一律用属性访问：它是可以被重绑的模块级对象，按值导入会拿到旧的那个。
    """
    write_active_dataset_id(MAIN_DATASET_ID)
    current = database.engine.url.database
    if current is None or Path(current).resolve() != _TEST_DB.resolve():
        database.rebind(_TEST_DB)


def _clear_datasets() -> None:
    """清掉用例产生的数据集文件。

    数据集目录建在测试库同级，所以同一进程里前一个用例导入的数据集会出现在后一个
    用例的列表里。这里删的是本进程独占的临时目录内容（整个目录在会话结束时统一
    删除），不是用户数据。
    """
    directory = datasets_directory()
    if directory.exists():
        shutil.rmtree(directory, ignore_errors=True)


@pytest.fixture(autouse=True)
def no_real_search_network(monkeypatch):
    """测试默认**不许真的联网**。

    联网搜索改成"多来源聚合 + 可选正文抓取"之后，只要有一条测试忘了替换网络层，整轮
    测试就会去请求 Bing / DuckDuckGo / 结果页，表现为长时间卡住而不是失败——这是最难
    排查的一类测试问题。这里把网络层统一换成"没有结果"，需要真实行为的测试自己再
    patch 回来（那些 patch 在 fixture 之后生效，优先级更高）。
    """

    async def empty_results(*_args, **_kwargs):
        return []

    async def empty_page(*_args, **_kwargs):
        return ""

    async def empty_rss(_query: str) -> bytes:
        return b"<rss><channel></channel></rss>"

    monkeypatch.setattr("app.services.search.aggregate.bing_search", empty_results)
    monkeypatch.setattr("app.services.search.aggregate.search_duckduckgo", empty_results)
    monkeypatch.setattr("app.services.search.aggregate.search_searxng", empty_results)
    monkeypatch.setattr("app.services.search.aggregate.fetch_page_text", empty_page)
    monkeypatch.setattr("app.services.assistant.assistant_web_search.fetch_bing_rss", empty_rss)

    def no_filter_network(url: str, timeout: float):
        # 站点筛选项清单的默认取数口子。**默认封掉**：忘了注入 fetcher 的用例会立刻失败，
        # 而不是安静地去请求 zhipin.com——后者在能联网的开发机上"碰巧通过"、在 CI 上超时，
        # 是最难定位的一类测试问题。需要真实响应的用例自己 monkeypatch 回来。
        raise OSError(f"测试环境不访问真实站点：{url}")

    monkeypatch.setattr("app.services.sites.boss_filters.default_fetcher", no_filter_network)


@pytest.fixture(autouse=True)
def clean_db():
    """每个用例前重建表结构，保证用例之间完全隔离。"""
    _reset_to_test_database()
    _clear_datasets()
    Base.metadata.drop_all(bind=database.engine)
    Base.metadata.create_all(bind=database.engine)
    yield
    _reset_to_test_database()
    Base.metadata.drop_all(bind=database.engine)
    _clear_datasets()


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.close()


# 官网站点采集的用例会走真实的 SSRF 防护，而那道防护要解析域名。**刻意不是 autouse**：
# 只有需要它的用例才取用，避免给两千多个既有用例换掉 DNS 行为。
PUBLIC_IP_FOR_TESTS = "93.184.216.34"
PRIVATE_IP_FOR_TESTS = "10.0.0.1"


@pytest.fixture
def fake_public_dns(monkeypatch):
    """把域名解析固定下来：``*.internal.example`` 指向内网，其余指向公网。

    替换 ``socket.getaddrinfo`` 而不是替换 ``is_public_http_url``——**防护本身必须在被测
    路径上**，把防范函数打桩等于把要验的东西换成恒真式。

    字面 IP **原样返回**（真实 ``getaddrinfo`` 就是这么做的）：若在这里也把它们换成公网地址，
    "127.0.0.1 会被拒绝"这条断言会通过，但什么也没有证明。
    """
    import ipaddress
    import socket

    def _getaddrinfo(host, port, *args, **kwargs):  # noqa: ARG001
        try:
            ipaddress.ip_address(host)
            address = host
        except ValueError:
            address = (
                PRIVATE_IP_FOR_TESTS if str(host).endswith("internal.example")
                else PUBLIC_IP_FOR_TESTS
            )
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port or 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo)


@pytest.fixture
def client():
    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # 生产版只监听本机；测试客户端也使用回环地址覆盖密钥查看边界。
    with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_db():
    """测试全部结束后删除测试数据目录。"""
    yield
    # Windows 下引擎的连接池仍持有文件句柄，必须先 dispose 才能删除
    database.engine.dispose()
    shutil.rmtree(_TEST_DIR, ignore_errors=True)
