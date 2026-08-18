"""Create an on-demand backup of the configured SQLite database."""
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.database import engine  # noqa: E402
from app.database_migrations import backup_sqlite_database  # noqa: E402


def main() -> int:
    destination = backup_sqlite_database(engine)
    if destination is None:
        print("当前数据库不是可备份的本地 SQLite 文件。")
        return 1
    print(f"备份完成：{destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
