"""Database migration orchestration and safe SQLite backups."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
BASELINE_REVISION = "0001_existing_schema"
_APPLICATION_TABLES = (
    "job",
    "user_profile",
    "education",
    "experience",
    "campus_experience",
    "project",
    "skill",
    "award",
    "resume_record",
    "app_setting",
    "llm_config_record",
    "chat_conversation",
    "chat_message",
)
_USER_DATA_TABLES = _APPLICATION_TABLES


def build_alembic_config(bind: Engine) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.attributes["configure_logger"] = False
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", bind.url.render_as_string(hide_password=False))
    return config


def _database_has_user_data(bind: Engine) -> bool:
    tables = set(inspect(bind).get_table_names())
    with bind.connect() as connection:
        for table_name in _USER_DATA_TABLES:
            if table_name not in tables:
                continue
            quoted = bind.dialect.identifier_preparer.quote(table_name)
            if connection.execute(text(f"SELECT 1 FROM {quoted} LIMIT 1")).first() is not None:
                return True
    return False


def _database_has_application_tables(bind: Engine) -> bool:
    """Return whether an unversioned database is a legacy ResumeForge database."""
    return bool(set(inspect(bind).get_table_names()).intersection(_APPLICATION_TABLES))


def is_unversioned_legacy_database(bind: Engine) -> bool:
    """Identify databases that predate Alembic but already contain app tables."""
    if not _database_has_application_tables(bind):
        return False
    with bind.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision() is None


def backup_sqlite_database(bind: Engine, output_dir: Path | None = None) -> Path | None:
    """Create a consistent SQLite backup and return its path.

    Non-SQLite databases are expected to use their platform backup tooling.
    """
    if bind.dialect.name != "sqlite" or not bind.url.database:
        return None
    source = Path(bind.url.database).resolve()
    if not source.exists():
        return None
    destination_dir = output_dir or source.parent / "backups"
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destination = destination_dir / f"{source.stem}-{timestamp}{source.suffix or '.db'}"
    with sqlite3.connect(source) as source_db, sqlite3.connect(destination) as backup_db:
        source_db.backup(backup_db)
    logger.info("数据库升级前备份已创建 path=%s", destination)
    return destination


def run_database_migrations(bind: Engine) -> Path | None:
    """Upgrade an empty or legacy database to the current Alembic head."""
    config = build_alembic_config(bind)
    scripts = ScriptDirectory.from_config(config)
    head_revision = scripts.get_current_head()
    with bind.connect() as connection:
        current_revision = MigrationContext.configure(connection).get_current_revision()
    if current_revision == head_revision:
        return None

    legacy_database = current_revision is None and _database_has_application_tables(bind)
    backup_path = backup_sqlite_database(bind) if _database_has_user_data(bind) else None
    # Reuse the application's connection so sqlite:///:memory: is migrated in
    # place instead of creating and discarding a second in-memory database.
    with bind.begin() as connection:
        config.attributes["connection"] = connection
        if legacy_database:
            # Legacy startup creates/repairs the schema before this runner. Stamp
            # only those databases; a genuinely empty database must execute 0001.
            command.stamp(config, BASELINE_REVISION)
        command.upgrade(config, "head")
    logger.info("数据库迁移完成 revision=%s", head_revision)
    return backup_path
