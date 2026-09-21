"""把「有正文却没有技能标签」的历史采集岗位的标签重算回来（可反复运行、默认只预览）。

**为什么需要它**：早期采集器有一条自己直写 ``job`` 表的老路径，只写了 description /
requirements，从来没算过 ``keywords``，于是标签取模型默认值 ``[]``。当前工作区的采集链路已经
改成「暂存候选 → import_candidates → create_job_record → refresh_job_keywords」，**新采集不会
再产生空标签**；但库里已经落地的那批行仍然是空的，而它们又修不了别的手段：

- **重采集修不好**：采集器按 ``source_url`` 去重，同一岗位会被判为「已存在」而跳过；
- **「补齐详情」修不好**：那条路径的跳过条件是「已有描述就跳过」（它只补空），这十行都有描述
  → 永远被记为 ``backfill_skipped``。

所以只能就地重算。

**只补空**：只处理 ``keywords`` 为空的行——用户可能自己编辑过标签，重算不该覆盖他的劳动成果。
这正是「只补空」而不是「一律覆盖」的取舍。

**默认 dry-run**：不加 ``--apply`` 只打印将要发生的变化，不动数据库。加了 ``--apply`` 会先把
数据库整体复制一份到 ``<数据库目录>/backups/``，再逐行更新。脚本**幂等**——已经补好的行不会
被再次改动（第二次运行会显示 0 处变化）。

用法（在仓库根目录执行）::

    backend/.venv/Scripts/python.exe scripts/repair_job_keywords.py
    backend/.venv/Scripts/python.exe scripts/repair_job_keywords.py --apply
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.models.job import Job  # noqa: E402  (需要先补 sys.path)
from app.services.job.job_service import refresh_job_keywords  # noqa: E402  (需要先补 sys.path)

DEFAULT_DB = BACKEND_ROOT / "data" / "resume_forge.db"


def _empty_keywords(value: str | None) -> bool:
    """这一行的 ``keywords`` 是否为空（NULL / ``''`` / ``'[]'`` / 非法 JSON 都算空）。

    非法 JSON 也当空处理：那是损坏的行，重算一遍就是修复；反正「非空且合法」才会被当成
    用户数据保留。
    """
    if value is None:
        return True
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return True
    return not parsed


def _has_body(row: sqlite3.Row) -> bool:
    """有没有可供解析的正文（description / requirements / additional_info 任一非空）。"""
    return any(
        (row[column] or "").strip()
        for column in ("description", "requirements", "additional_info")
    )


def _keywords_for_row(row: sqlite3.Row) -> list[dict]:
    """用与运行时**完全相同**的实现算标签。

    刻意复用 ``refresh_job_keywords``（它内部走 ``_keywords_for → parse_jd``），而不是在这里
    再拼一遍 ``parse_jd(f"{description}\\n{requirements}\\n{additional_info}")``：两个实现必然
    漂移，而漂移的症状正是本次要修的 bug 本身（脚本说算出来了、线上搜索却仍按空标签走）。
    """
    job = Job(
        description=row["description"] or "",
        requirements=row["requirements"] or "",
        additional_info=row["additional_info"] or "",
    )
    refresh_job_keywords(job)
    return list(job.keywords or [])


def _plan(row: sqlite3.Row) -> list[dict] | None:
    """算出一行修好后的标签；**不需要修**时返回 ``None``（调用方就跳过它）。

    返回 ``None`` 的三种情况都**不动数据库**：
    - 没有正文的算不出标签（重算也是空）；
    - 已有非空标签的只保留原值（只补空、不覆盖）；
    - 重算仍然为空的不写一个空值上去（保持幂等：下一轮也不会再被选中）。
    """
    if not _has_body(row):
        return None
    if not _empty_keywords(row["keywords"]):
        return None
    return _keywords_for_row(row) or None


def select_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    """取出所有**有正文**的岗位行（无正文的行根本不可能算出标签，先排除）。"""
    connection.row_factory = sqlite3.Row
    return connection.execute(
        "SELECT id, title, description, requirements, additional_info, keywords FROM job "
        "WHERE TRIM(COALESCE(description, '')) <> '' "
        "OR TRIM(COALESCE(requirements, '')) <> '' "
        "OR TRIM(COALESCE(additional_info, '')) <> '' "
        "ORDER BY id"
    ).fetchall()


def plan_rows(rows: list[sqlite3.Row]) -> list[tuple[sqlite3.Row, list[dict]]]:
    """筛出需要重算的行及其新标签（纯函数，便于 dry-run 与测试复用）。"""
    plans: list[tuple[sqlite3.Row, list[dict]]] = []
    for row in rows:
        keywords = _plan(row)
        if keywords:
            plans.append((row, keywords))
    return plans


def apply_plans(
    connection: sqlite3.Connection, plans: list[tuple[sqlite3.Row, list[dict]]]
) -> int:
    """把计划写回数据库（批量一次提交）。返回实际改动的行数。"""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for row, keywords in plans:
        connection.execute(
            "UPDATE job SET keywords = ?, updated_at = ? WHERE id = ?",
            (json.dumps(keywords, ensure_ascii=False), now, row["id"]),
        )
    connection.commit()
    return len(plans)


def _describe(keywords: list[dict]) -> str:
    return "、".join(str(item.get("name", "")) for item in keywords)


def main() -> int:
    parser = argparse.ArgumentParser(description="重算「有正文却标签为空」的历史岗位技能标签")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="数据库文件路径")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真正写库（默认只预览）。写库前会自动备份数据库文件。",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"数据库不存在：{db_path}")
        return 1

    connection = sqlite3.connect(db_path)
    try:
        rows = select_rows(connection)
        plans = plan_rows(rows)

        print(f"有正文的岗位共 {len(rows)} 条，标签为空且可重算的 {len(plans)} 条。")
        for row, keywords in plans:
            print(f"  id={row['id']} {row['title']} -> {_describe(keywords)}")
        if plans:
            print(f"  样例：id={plans[0][0]['id']} 将写入 {len(plans[0][1])} 个标签")

        if not plans:
            print("没有需要修复的行（脚本是幂等的）。")
            return 0

        if not args.apply:
            print("\n以上只是预览；确认无误后加 --apply 真正写库。")
            return 0

        backup_dir = db_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup_path = backup_dir / f"{db_path.stem}-before-keyword-repair-{stamp}{db_path.suffix}"
        shutil.copy2(db_path, backup_path)
        print(f"\n已备份数据库 -> {backup_path}")

        changed = apply_plans(connection, plans)
        print(f"已修复 {changed} 条。")
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
