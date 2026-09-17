"""``0011_claim_ledger`` 迁移：建表、幂等与完整 downgrade。

迁移是数据安全的落点，所以这里不只测"能跑通"，还测：重复执行不报错（幂等）、
downgrade 只删自己那张表、以及 upgrade/downgrade 往返后既有数据仍在。
"""
from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.database_migrations import build_alembic_config

PREVIOUS_REVISION = "0010_apply_center"
HEAD_REVISION = "0011_claim_ledger"
# 本测试只针对 0011 自己这一版，所以显式指定 revision 而不是 "head"：
# 以后再加迁移时，"head" 会跑到新版本上去，这条测试就会因为一个与它无关的原因变红。

EXPECTED_COLUMNS = {
    "id",
    "title",
    "category",
    "subject",
    "source_fact",
    "candidate_wording",
    "sources",
    "responsibility_level",
    "verification_status",
    "allowed_uses",
    "interview_details",
    "boundary",
    "risk_notes",
    "last_verified",
    "created_at",
    "updated_at",
}

EXPECTED_INDEXES = {
    "ix_claim_record_category",
    "ix_claim_record_subject",
    "ix_claim_record_verification_status",
    "ix_claim_record_responsibility_level",
}


def _revision(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def test_upgrade_creates_the_claim_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'claim-ledger.db'}")
    try:
        command.upgrade(build_alembic_config(engine), HEAD_REVISION)

        inspector = inspect(engine)
        assert "claim_record" in inspector.get_table_names()
        assert _revision(engine) == HEAD_REVISION
        assert {item["name"] for item in inspector.get_columns("claim_record")} == EXPECTED_COLUMNS
        assert EXPECTED_INDEXES <= {item["name"] for item in inspector.get_indexes("claim_record")}

        # 台账不建外键：它记录的是"关于某段经历的主张"，主体用 subject 文本关联，
        # 这样资料库怎么改都不会连带删掉用户已经整理好的事实基线。
        assert inspector.get_foreign_keys("claim_record") == []
    finally:
        engine.dispose()


def test_upgrade_is_idempotent_when_the_table_already_exists(tmp_path):
    """重复执行迁移不能报错（表已存在时必须跳过，而不是抛 already exists）。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'claim-ledger-idempotent.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        command.stamp(config, PREVIOUS_REVISION)
        command.upgrade(config, HEAD_REVISION)

        inspector = inspect(engine)
        assert "claim_record" in inspector.get_table_names()
        assert _revision(engine) == HEAD_REVISION
    finally:
        engine.dispose()


def test_downgrade_drops_only_the_claim_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'claim-ledger-downgrade.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        command.downgrade(config, PREVIOUS_REVISION)

        inspector = inspect(engine)
        assert "claim_record" not in inspector.get_table_names()
        # 既有表（含 0010 建的投递表）不受影响。
        assert {
            "job",
            "resume_record",
            "job_match_analysis",
            "apply_task_item",
            "interview_session",
        } <= set(inspector.get_table_names())
        assert _revision(engine) == PREVIOUS_REVISION
    finally:
        engine.dispose()


def test_upgrade_downgrade_round_trip_keeps_existing_data(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'claim-ledger-roundtrip.db'}")
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

        inspector = inspect(engine)
        assert "claim_record" in inspector.get_table_names()
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(1) FROM job")).scalar_one() == 1
            assert connection.execute(text("SELECT title FROM job")).scalar_one() == "后端开发"
            # 重建后的台账是空的（数据不可逆丢失，符合预期）。
            assert connection.execute(text("SELECT count(1) FROM claim_record")).scalar_one() == 0
    finally:
        engine.dispose()


def test_defaults_match_the_model_constants(tmp_path):
    """迁移里写死的 server_default 必须与模型常量一致。

    两处不一致时，用 create_all 建出来的库和用迁移建出来的库会表现不同，而这类
    差异只会在"用户从旧版本升级"时才暴露，单元测试很难碰到。
    """
    from app.models.claim import (
        CLAIM_CATEGORY_OTHER,
        RESPONSIBILITY_PARTICIPATED,
        VERIFICATION_PENDING,
    )

    engine = create_engine(f"sqlite:///{tmp_path / 'claim-ledger-defaults.db'}")
    try:
        command.upgrade(build_alembic_config(engine), HEAD_REVISION)
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO claim_record (created_at, updated_at) "
                                    "VALUES ('2026-09-18', '2026-09-18')"))
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT category, responsibility_level, verification_status, sources, "
                    "allowed_uses, interview_details, risk_notes, last_verified, title, subject, "
                    "source_fact, candidate_wording, boundary FROM claim_record"
                )
            ).one()
        assert row.category == CLAIM_CATEGORY_OTHER
        assert row.responsibility_level == RESPONSIBILITY_PARTICIPATED
        assert row.verification_status == VERIFICATION_PENDING
        assert row.sources == "[]"
        assert row.allowed_uses == "[]"
        assert row.interview_details == "{}"
        assert row.risk_notes == "[]"
        assert row.last_verified == ""
        assert (row.title, row.subject, row.source_fact, row.candidate_wording, row.boundary) == (
            "",
            "",
            "",
            "",
            "",
        )
    finally:
        engine.dispose()
