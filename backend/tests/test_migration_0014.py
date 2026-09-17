"""``0014_interview_drill`` 迁移：建表、级联、幂等与完整 downgrade。"""
from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.database_migrations import build_alembic_config

PREVIOUS_REVISION = "0013_resume_format_config"
HEAD_REVISION = "0014_interview_drill"

EXPECTED_COLUMNS = {
    "drill_session": {
        "id",
        "title",
        "job_id",
        "job_title",
        "company",
        "status",
        "feedback_policy",
        "claim_ids",
        "max_questions",
        "current_index",
        "review",
        "created_at",
        "updated_at",
    },
    "drill_contract": {
        "id",
        "session_id",
        "claim_id",
        "claim_title",
        "question",
        "intent",
        "required_evidence",
        "followup_triggers",
        "stop_condition",
        "status",
        "evidence_found",
        "missing",
        "contradictions",
        "followup_depth",
        "next_followup_kind",
        "created_at",
        "updated_at",
    },
    "drill_turn": {
        "id",
        "session_id",
        "contract_id",
        "question",
        "answer",
        "status",
        "feedback",
        "next_question",
        "created_at",
    },
}


def _revision(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def test_upgrade_creates_the_three_tables(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'drill.db'}")
    try:
        command.upgrade(build_alembic_config(engine), HEAD_REVISION)

        inspector = inspect(engine)
        assert _revision(engine) == HEAD_REVISION
        for table, columns in EXPECTED_COLUMNS.items():
            assert table in inspector.get_table_names()
            assert {item["name"] for item in inspector.get_columns(table)} == columns, table

        # 契约与轮次随会话删除；主张被删掉后契约仍要可读（复盘要看当时问了什么）。
        assert any(
            item["referred_table"] == "drill_session"
            and item["options"].get("ondelete") == "CASCADE"
            for item in inspector.get_foreign_keys("drill_contract")
        )
        assert any(
            item["referred_table"] == "claim_record"
            and item["options"].get("ondelete") == "SET NULL"
            for item in inspector.get_foreign_keys("drill_contract")
        )
        assert any(
            item["referred_table"] == "drill_contract"
            and item["options"].get("ondelete") == "CASCADE"
            for item in inspector.get_foreign_keys("drill_turn")
        )
    finally:
        engine.dispose()


def test_upgrade_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'drill-idempotent.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        command.stamp(config, PREVIOUS_REVISION)
        command.upgrade(config, HEAD_REVISION)
        assert "drill_session" in inspect(engine).get_table_names()
        assert _revision(engine) == HEAD_REVISION
    finally:
        engine.dispose()


def test_downgrade_drops_only_the_drill_tables(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'drill-downgrade.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        command.downgrade(config, PREVIOUS_REVISION)

        tables = set(inspect(engine).get_table_names())
        assert not ({"drill_session", "drill_contract", "drill_turn"} & tables)
        # 既有表（含台账与投递表）不受影响。
        assert {
            "claim_record",
            "resume_record",
            "job",
            "application_track",
        } <= tables
        assert _revision(engine) == PREVIOUS_REVISION
    finally:
        engine.dispose()


def test_deleting_a_session_cascades_to_contracts_and_turns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'drill-cascade.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO drill_session (title, status, feedback_policy, claim_ids, "
                    "max_questions, current_index, review, created_at, updated_at) VALUES "
                    "('测试', 'active', 'deferred', '[]', 6, 1, '{}', '2026-09-18', '2026-09-18')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO drill_contract (session_id, claim_title, question, intent, "
                    "required_evidence, followup_triggers, stop_condition, status, evidence_found, "
                    "missing, contradictions, followup_depth, next_followup_kind, created_at, "
                    "updated_at) VALUES (1, '检索接口', '问什么？', '验证边界', '[\"一条\"]', '[]', "
                    "'', 'not_covered', '[]', '[]', '[]', 0, '', '2026-09-18', '2026-09-18')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO drill_turn (session_id, contract_id, question, answer, status, "
                    "feedback, next_question, created_at) VALUES (1, 1, '问', '答', 'partial', "
                    "'', '', '2026-09-18')"
                )
            )

        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
            connection.execute(text("DELETE FROM drill_session WHERE id = 1"))
            connection.commit()
            assert connection.execute(text("SELECT count(1) FROM drill_contract")).scalar_one() == 0
            assert connection.execute(text("SELECT count(1) FROM drill_turn")).scalar_one() == 0
    finally:
        engine.dispose()


def test_deleting_a_claim_keeps_the_contract_for_review(tmp_path):
    """主张删了，但"当时问了什么、判定成什么"要留着——复盘要靠它。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'drill-claim-null.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO claim_record (title, category, subject, source_fact, "
                    "candidate_wording, sources, responsibility_level, verification_status, "
                    "allowed_uses, interview_details, boundary, risk_notes, last_verified, "
                    "created_at, updated_at) VALUES ('检索接口', '项目经历', '平台', '做了接口', "
                    "'实现接口', '[]', '参与', '已确认', '[]', '{}', '', '[]', '', "
                    "'2026-09-18', '2026-09-18')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO drill_session (title, status, feedback_policy, claim_ids, "
                    "max_questions, current_index, review, created_at, updated_at) VALUES "
                    "('测试', 'finished', 'deferred', '[1]', 6, 1, '{}', '2026-09-18', '2026-09-18')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO drill_contract (session_id, claim_id, claim_title, question, "
                    "intent, required_evidence, followup_triggers, stop_condition, status, "
                    "evidence_found, missing, contradictions, followup_depth, next_followup_kind, "
                    "created_at, updated_at) VALUES (1, 1, '检索接口', '问什么？', '', '[\"一条\"]', "
                    "'[]', '', 'partial', '[]', '[]', '[]', 0, '', '2026-09-18', '2026-09-18')"
                )
            )

        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
            connection.execute(text("DELETE FROM claim_record WHERE id = 1"))
            connection.commit()
            row = connection.execute(
                text("SELECT claim_id, claim_title FROM drill_contract WHERE id = 1")
            ).one()
        assert row.claim_id is None
        assert row.claim_title == "检索接口"
    finally:
        engine.dispose()


def test_upgrade_downgrade_round_trip_keeps_existing_data(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'drill-roundtrip.db'}")
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

        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(1) FROM job")).scalar_one() == 1
            assert connection.execute(text("SELECT count(1) FROM drill_session")).scalar_one() == 0
    finally:
        engine.dispose()
