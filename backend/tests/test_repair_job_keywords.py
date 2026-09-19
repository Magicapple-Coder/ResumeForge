"""技能标签修复脚本的规则。

脚本是「就地改用户数据」的工具，所以它最容易犯的错不是解析错，而是**把用户已经编辑好的
标签覆盖掉**（或者反过来：只跑规划就动了库）。这里把「只补空」「规划不写库」「幂等」三条
规则钉死，并且脚本复用的必须是运行时同一实现（``refresh_job_keywords``）。

脚本在 `scripts/` 下（不在 `backend` 包内），所以按文件路径加载。
"""
import importlib.util
import sqlite3
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "repair_job_keywords.py"


def _load():
    spec = importlib.util.spec_from_file_location("repair_job_keywords", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _connect(*rows) -> sqlite3.Connection:
    """建一张只含脚本所需的列的 ``job`` 表，并塞入给定的行。

    行的形状：(id, title, description, requirements, additional_info, keywords)。
    """
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE job (id INTEGER PRIMARY KEY, title TEXT, description TEXT, "
        "requirements TEXT, additional_info TEXT, keywords TEXT, updated_at TEXT)"
    )
    for row in rows:
        connection.execute(
            "INSERT INTO job (id, title, description, requirements, additional_info, "
            "keywords, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'old')",
            row,
        )
    connection.commit()
    return connection


def _keywords_of(connection: sqlite3.Connection, job_id: int) -> str:
    return connection.execute("SELECT keywords FROM job WHERE id = ?", (job_id,)).fetchone()[0]


def test_plan_fills_empty_keywords_from_a_technical_jd():
    connection = _connect(
        (
            1,
            "后端开发",
            "技术栈：Java、Spring Boot、MySQL。",
            "熟悉 Docker 与 Redis。",
            "",
            "[]",
        )
    )
    plans = _load().plan_rows(_load().select_rows(connection))

    assert len(plans) == 1
    job_id, keywords = plans[0]
    assert job_id["id"] == 1
    assert {"Java", "Spring Boot", "MySQL", "Docker", "Redis"} <= {
        item["name"] for item in keywords
    }


def test_plan_never_overwrites_existing_keywords():
    """已经非空的标签**一律保留**——那是用户（或旧数据）的劳动成果。"""
    existing = '[{"name": "我手动编辑的标签", "category": "自定义"}]'
    connection = _connect((1, "后端开发", "技术栈：Java。", "", "", existing))

    assert _load().plan_rows(_load().select_rows(connection)) == []
    # 规划阶段本来就不写库，值必须原样。
    assert _keywords_of(connection, 1) == existing


def test_plan_skips_rows_without_body():
    """没有正文的行算不出标签，不该被选中（选中了也只是写回一个空值）。"""
    connection = _connect((1, "空岗位", "", "", "", "[]"))

    assert _load().select_rows(connection) == []
    assert _load().plan_rows(_load().select_rows(connection)) == []


def test_planning_does_not_write_to_the_database():
    """dry-run 只规划、不改数据。"""
    connection = _connect((1, "后端开发", "技术栈：Java、MySQL。", "", "", "[]"))
    before = _keywords_of(connection, 1)

    plans = _load().plan_rows(_load().select_rows(connection))

    assert plans, "这一行应当被选中"
    assert _keywords_of(connection, 1) == before


def test_apply_is_idempotent():
    """写库后第二次规划应当为空（脚本可以反复运行）。"""
    module = _load()
    connection = _connect((1, "后端开发", "技术栈：Java、MySQL。", "", "", "[]"))

    changed = module.apply_plans(connection, module.plan_rows(module.select_rows(connection)))

    assert changed == 1
    assert _keywords_of(connection, 1)  # 空列表会被 JSON 序列化成 "[]"，这里断言非空
    assert module.plan_rows(module.select_rows(connection)) == []
