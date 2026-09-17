"""``0012_application_tracker`` 迁移：建表、唯一约束、幂等与完整 downgrade。"""
from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.database_migrations import build_alembic_config

PREVIOUS_REVISION = "0011_claim_ledger"
HEAD_REVISION = "0012_application_tracker"

EXPECTED_COLUMNS = {
    "id",
    "company",
    "title",
    "company_key",
    "title_key",
    "status",
    "stage_note",
    "applied_at",
    "status_date",
    "next_action",
    "next_action_date",
    "note",
    "evidence",
    "job_id",
    "resume_id",
    "source",
    "created_at",
    "updated_at",
}

EXPECTED_INDEXES = {
    "ix_application_track_company_key",
    "ix_application_track_title_key",
    "ix_application_track_status",
    "ix_application_track_job_id",
}


def _revision(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def test_upgrade_creates_the_track_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'tracker.db'}")
    try:
        command.upgrade(build_alembic_config(engine), HEAD_REVISION)

        inspector = inspect(engine)
        assert "application_track" in inspector.get_table_names()
        assert _revision(engine) == HEAD_REVISION
        assert {
            item["name"] for item in inspector.get_columns("application_track")
        } == EXPECTED_COLUMNS
        assert EXPECTED_INDEXES <= {
            item["name"] for item in inspector.get_indexes("application_track")
        }

        # 岗位 / 简历被删掉后记录仍要可读。
        fks = inspector.get_foreign_keys("application_track")
        for table, column in (("job", "job_id"), ("resume_record", "resume_id")):
            assert any(
                item["referred_table"] == table
                and item["constrained_columns"] == [column]
                and item["options"].get("ondelete") == "SET NULL"
                for item in fks
            ), f"{column} 的删除语义应为 SET NULL"
    finally:
        engine.dispose()


def test_company_and_title_pair_is_unique(tmp_path):
    """同一公司同一岗位只能有一条——漏斗的一个口径靠它兜住。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'tracker-unique.db'}")
    try:
        command.upgrade(build_alembic_config(engine), HEAD_REVISION)
        constraints = inspect(engine).get_unique_constraints("application_track")
        assert any(
            set(item["column_names"]) == {"company_key", "title_key"} for item in constraints
        )

        insert = (
            "INSERT INTO application_track (company, title, company_key, title_key, status, "
            "created_at, updated_at) VALUES ('示例公司', '后端开发', '示例公司', '后端开发', "
            "'applied', '2026-09-18', '2026-09-18')"
        )
        with engine.begin() as connection:
            connection.execute(text(insert))

        with engine.begin() as connection:
            try:
                connection.execute(text(insert))
            except Exception as exc:  # noqa: BLE001 - 只关心"被拒了"
                assert "UNIQUE" in str(exc).upper()
            else:  # pragma: no cover - 约束失效时才会走到
                raise AssertionError("重复的公司+岗位没有被唯一约束拦下")
    finally:
        engine.dispose()


def test_upgrade_is_idempotent_when_the_table_already_exists(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'tracker-idempotent.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        command.stamp(config, PREVIOUS_REVISION)
        command.upgrade(config, HEAD_REVISION)

        assert "application_track" in inspect(engine).get_table_names()
        assert _revision(engine) == HEAD_REVISION
    finally:
        engine.dispose()


def test_downgrade_drops_only_the_track_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'tracker-downgrade.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        command.downgrade(config, PREVIOUS_REVISION)

        inspector = inspect(engine)
        assert "application_track" not in inspector.get_table_names()
        assert {
            "job",
            "resume_record",
            "claim_record",
            "apply_task_item",
        } <= set(inspector.get_table_names())
        assert _revision(engine) == PREVIOUS_REVISION
    finally:
        engine.dispose()


def test_upgrade_downgrade_round_trip_keeps_existing_data(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'tracker-roundtrip.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO job (title, company, location, salary, job_type, description, "
                    "requirements, additional_info, keywords, source, source_url, posted_at, "
                    "status, note, note_images, favorite, recognition_source, created_at, "
                    "updated_at) VALUES ('后端开发', '示例科技', '', '', '社招', '', '', '', '[]', "
                    "'手动添加', '', '', '开放中', '', '[]', 0, '', '2026-09-18', '2026-09-18')"
                )
            )

        command.downgrade(config, PREVIOUS_REVISION)
        command.upgrade(config, HEAD_REVISION)

        assert "application_track" in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(1) FROM job")).scalar_one() == 1
            # 重建后的进度表是空的（数据不可逆丢失，符合预期）。
            assert (
                connection.execute(text("SELECT count(1) FROM application_track")).scalar_one() == 0
            )
    finally:
        engine.dispose()


def test_defaults_match_the_model_constants(tmp_path):
    """迁移里的 server_default 必须与模型常量一致，否则升级上来的库和新建的库表现不同。"""
    from app.models.tracker import SOURCE_MANUAL, STATUS_APPLIED

    engine = create_engine(f"sqlite:///{tmp_path / 'tracker-defaults.db'}")
    try:
        command.upgrade(build_alembic_config(engine), HEAD_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO application_track (created_at, updated_at) "
                    "VALUES ('2026-09-18', '2026-09-18')"
                )
            )
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT status, source, company, title, company_key, title_key, stage_note, "
                    "applied_at, status_date, next_action, next_action_date, note, evidence, "
                    "job_id, resume_id FROM application_track"
                )
            ).one()

        assert row.status == STATUS_APPLIED
        assert row.source == SOURCE_MANUAL
        assert (
            row.company,
            row.title,
            row.company_key,
            row.title_key,
            row.stage_note,
            row.applied_at,
            row.status_date,
            row.next_action,
            row.next_action_date,
            row.note,
            row.evidence,
        ) == ("", "", "", "", "", "", "", "", "", "", "")
        assert row.job_id is None and row.resume_id is None
    finally:
        engine.dispose()
