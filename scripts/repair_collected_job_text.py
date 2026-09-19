"""修理由字体反爬与水印导致的历史采集数据污染（可反复运行、默认只预览）。

**为什么需要它**：投递台的采集在早期版本里没有还原 BOSS 的文本混淆，于是写进库的岗位带着
两类问题——岗位名被粘上了薪资、且数字被映射成私用区字符（界面上显示成方框，用户看到的
"全栈工程师-K" 就是 "23-26K" 被吃掉数字后的样子）；JD 正文里夹着 ``boss`` / ``kanzhun`` /
``直聘`` 水印，或者整段被塞进「职位描述」而「任职要求」为空。

**重采集修不好这些行**：采集器按 `source_url` 去重，同一岗位会被判为"已存在"而跳过。
所以必须就地修复。

**默认 dry-run**：不加 ``--apply`` 只打印将要发生的变化，不动数据库。加了 ``--apply`` 会先
把数据库整体复制一份到 ``<数据库目录>/backups/``，再逐行更新。脚本**幂等**——已经修好的行
不会被再次改动（第二次运行会显示 0 处变化）。

用法（在仓库根目录执行）::

    backend/.venv/Scripts/python.exe scripts/repair_collected_job_text.py
    backend/.venv/Scripts/python.exe scripts/repair_collected_job_text.py --apply
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.sites.boss_text import (  # noqa: E402  (需要先补 sys.path)
    normalize_text,
    split_job_sections,
    split_title_salary,
)
from app.services.apply.collector import COLLECT_RECOGNITION_SOURCE  # noqa: E402

DEFAULT_DB = BACKEND_ROOT / "data" / "resume_forge.db"


def _repair(row: sqlite3.Row) -> dict[str, str]:
    """算出一行修好之后应该长什么样（纯函数，便于 dry-run 与测试复用）。"""
    title, title_salary = split_title_salary(row["title"])
    description, split_requirements = split_job_sections(row["description"])
    return {
        "title": title,
        "company": normalize_text(row["company"]),
        "location": normalize_text(row["location"]),
        # 标题里拆出来的薪资只在原本为空时补上：已经填好的值不覆盖。
        "salary": (row["salary"] or "").strip() or title_salary,
        "description": description,
        # 原本就单独取到「任职要求」的行保留原值，只在为空时用切分结果补齐。
        "requirements": (row["requirements"] or "").strip() or split_requirements,
    }


def _changed(row: sqlite3.Row, repaired: dict[str, str]) -> list[str]:
    fields = ("title", "company", "location", "salary", "description", "requirements")
    return [name for name in fields if (row[name] or "") != repaired[name]]


def main() -> int:
    parser = argparse.ArgumentParser(description="修理由文本混淆导致的历史采集数据污染")
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
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        "SELECT id, title, company, location, salary, description, requirements "
        "FROM job WHERE recognition_source = ? ORDER BY id",
        (COLLECT_RECOGNITION_SOURCE,),
    ).fetchall()

    plans: list[tuple[int, dict[str, str], list[str]]] = []
    for row in rows:
        repaired = _repair(row)
        touched = _changed(row, repaired)
        if touched:
            plans.append((row["id"], repaired, touched))

    print(f"采集来源的岗位共 {len(rows)} 条，需要修复 {len(plans)} 条。")
    for job_id, repaired, touched in plans:
        print(f"  id={job_id} 将更新：{'、'.join(touched)}")
        print(f"    标题 -> {repaired['title']!r}   薪资 -> {repaired['salary']!r}")

    if not plans:
        connection.close()
        print("没有需要修复的行（脚本是幂等的）。")
        return 0

    if not args.apply:
        connection.close()
        print("\n以上只是预览；确认无误后加 --apply 真正写库。")
        return 0

    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"{db_path.stem}-before-text-repair-{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    print(f"\n已备份数据库 -> {backup_path}")

    for job_id, repaired, _ in plans:
        connection.execute(
            "UPDATE job SET title = ?, company = ?, location = ?, salary = ?, "
            "description = ?, requirements = ?, updated_at = ? WHERE id = ?",
            (
                repaired["title"],
                repaired["company"],
                repaired["location"],
                repaired["salary"],
                repaired["description"],
                repaired["requirements"],
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                job_id,
            ),
        )
    connection.commit()
    connection.close()
    print(f"已修复 {len(plans)} 条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
