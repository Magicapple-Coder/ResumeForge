"""把已入库的采集岗位按小标题重新切回「职位描述 / 任职要求 / 其他招聘信息」。

**为什么需要它**：切分逻辑（``boss_text.split_job_fields``）修好之后只对**新采集**生效，
而库里那批"整段 JD 全塞在职位描述里"的历史行不会自己变。界面上的「补齐详情」也帮不上——
它有意跳过**已经有描述**的岗位（那一趟是给"JD 都没抓到"的岗位补正文的），而这些行恰恰
是有描述、只是没分类。

只动 ``job`` 表的三个文本列，**不删除、不改标题/公司/链接等任何其它字段**；切不出来的
行原样跳过。因此可以反复跑：跑第二遍时已经没有可切的行，输出 0 条。

默认**只预览不写**；确认无误后加 ``--apply`` 落库（落库前自动备份一份数据库）。

    python scripts/repair_collected_job_sections.py            # 预览
    python scripts/repair_collected_job_sections.py --apply    # 实际写入
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal, engine  # noqa: E402
from app.database_migrations import backup_sqlite_database  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.services import trash  # noqa: E402
from app.services.sites.boss_text import split_job_fields  # noqa: E402

# 只处理采集进来的岗位：手动粘贴的描述是用户自己写的，不该被按小标题重切。
COLLECTED_SOURCE = "岗位采集"

# 预览时最多打印几条明细，避免刷屏。
_SAMPLE_LIMIT = 10


def _repairable(job: Job) -> tuple[str, str, str] | None:
    """这条岗位重切之后是否值得改写；不值得返回 None。"""
    sections = split_job_fields(job.description)
    if not sections.requirements and not sections.additional:
        # 切不出第二/第三段：要么本来就分好类了，要么这行没有可切的分界。
        return None
    if (
        sections.description == (job.description or "").strip()
        and sections.requirements == (job.requirements or "").strip()
    ):
        return None
    return sections.description, sections.requirements, sections.additional


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="实际写入（默认只预览，不改数据库）"
    )
    args = parser.parse_args()

    session = SessionLocal()
    try:
        jobs = (
            session.execute(
                select(Job).where(
                    trash.live_only(Job), Job.recognition_source == COLLECTED_SOURCE
                )
            )
            .scalars()
            .all()
        )
        pending: list[tuple[Job, tuple[str, str, str]]] = []
        for job in jobs:
            repaired = _repairable(job)
            if repaired is not None:
                pending.append((job, repaired))

        print(f"采集岗位共 {len(jobs)} 条，其中 {len(pending)} 条可重切。")
        for job, (description, requirements, additional) in pending[:_SAMPLE_LIMIT]:
            print(
                f"  #{job.id} {job.title[:24]}："
                f"描述 {len(job.description or '')} → {len(description)} 字，"
                f"要求 {len(job.requirements or '')} → {len(requirements)} 字，"
                f"其他 {len(job.additional_info or '')} → {len(additional)} 字"
            )
        if len(pending) > _SAMPLE_LIMIT:
            print(f"  …还有 {len(pending) - _SAMPLE_LIMIT} 条")

        if not args.apply:
            print("\n（预览模式，未改动数据库。确认后加 --apply 落库。）")
            return 0
        if not pending:
            return 0

        backup = backup_sqlite_database(engine)
        print(f"\n已备份：{backup}" if backup else "\n（当前数据库不是可备份的本地 SQLite 文件）")

        for job, (description, requirements, additional) in pending:
            job.description = description
            job.requirements = requirements
            job.additional_info = additional
        session.commit()
        print(f"已重切 {len(pending)} 条岗位。")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
