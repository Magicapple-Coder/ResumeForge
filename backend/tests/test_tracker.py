"""求职进度的核心规则：合并键归一化、状态取舍、合并计划与执行、导出。

这个模块唯一会误导用户的地方是**状态**：一个错的「面试中」会让人按面试去准备。
所以测试重点全在这条上——尤其是"乱序粘贴旧通知不该把进度打回去"和"自动回执不能
推断成面试"。
"""
from datetime import date

import pytest
from pydantic import ValidationError

from app.models.tracker import (
    MERGE_CREATED,
    MERGE_UNCHANGED,
    MERGE_UPDATED,
    SOURCE_APPLY,
    STATUS_APPLIED,
    STATUS_ASSESSMENT,
    STATUS_INTERVIEW,
    STATUS_OFFER,
    STATUS_REJECTED,
    STATUS_SCREENING,
    STATUS_UNKNOWN,
    normalize_key,
    resolve_status,
)
from app.schemas.tracker import TrackCreate, TrackRecordIn
from app.services.tracker import (
    apply_merges,
    create_track,
    delete_track,
    export_rows,
    list_tracks,
    plan_merges,
    preview_merges,
    record_applied,
    summarize,
    to_csv,
    to_json,
    update_track,
)


def _record(**overrides) -> TrackRecordIn:
    base = {
        "company": "示例科技",
        "title": "后端开发实习生",
        "status": STATUS_APPLIED,
    }
    base.update(overrides)
    return TrackRecordIn(**base)


# ===== 归一化 =====


def test_normalize_key_ignores_spacing_case_and_fullwidth():
    assert normalize_key(" 示例 科技 ") == normalize_key("示例科技")
    assert normalize_key("ABC") == normalize_key("abc")
    assert normalize_key("ＡＢＣ") == normalize_key("abc")
    # 不同的东西不能被归一化成同一个：这两家是不同公司。
    assert normalize_key("示例科技") != normalize_key("示例科技有限公司")


# ===== 状态取舍 =====


def test_status_only_moves_forward():
    assert resolve_status(STATUS_INTERVIEW, STATUS_APPLIED) == STATUS_INTERVIEW
    assert resolve_status(STATUS_APPLIED, STATUS_SCREENING) == STATUS_SCREENING
    assert resolve_status(STATUS_INTERVIEW, STATUS_INTERVIEW) == STATUS_INTERVIEW


def test_rejection_always_wins():
    """拒信是决定性的：流程已经结束，之后不该再被任何通知复活。"""
    assert resolve_status(STATUS_OFFER, STATUS_REJECTED) == STATUS_REJECTED
    assert resolve_status(STATUS_INTERVIEW, STATUS_REJECTED) == STATUS_REJECTED
    assert resolve_status(STATUS_UNKNOWN, STATUS_REJECTED) == STATUS_REJECTED


def test_unknown_is_replaced_by_any_concrete_status():
    assert resolve_status(STATUS_UNKNOWN, STATUS_APPLIED) == STATUS_APPLIED
    assert resolve_status("", STATUS_SCREENING) == STATUS_SCREENING


def test_unknown_status_cannot_overwrite_a_concrete_one():
    # 模型把状态判成待确认时，不该把已有的明确状态抹掉。
    assert resolve_status(STATUS_INTERVIEW, STATUS_UNKNOWN) == STATUS_INTERVIEW


# ===== 合并计划与执行 =====


def test_preview_and_apply_agree(db_session):
    """预览说什么，确认执行就得做什么——这是这个功能最基本的一致性。"""
    records = [_record()]
    preview = preview_merges(db_session, records)
    assert [item.action for item in preview] == [MERGE_CREATED]

    result = apply_merges(db_session, records)
    assert result.created == 1
    assert result.updated == 0
    assert result.unchanged == 0

    # 同一条再来一次：这次应该判成"没有新变化"，而不是又建一条。
    second = preview_merges(db_session, records)
    assert [item.action for item in second] == [MERGE_UNCHANGED]
    applied = apply_merges(db_session, records)
    assert applied.unchanged == 1
    assert len(list_tracks(db_session)) == 1


def test_a_later_notice_advances_the_status(db_session):
    apply_merges(db_session, [_record()])
    preview = preview_merges(
        db_session,
        [_record(status=STATUS_INTERVIEW, stage_note="一面", status_date="2026-09-20")],
    )
    assert preview[0].action == MERGE_UPDATED
    assert preview[0].current_status == STATUS_APPLIED
    assert "推进为" in preview[0].reason

    result = apply_merges(
        db_session,
        [_record(status=STATUS_INTERVIEW, stage_note="一面", status_date="2026-09-20")],
    )
    assert result.updated == 1
    stored = list_tracks(db_session)[0]
    assert stored.status == STATUS_INTERVIEW
    assert stored.stage_note == "一面"
    assert stored.status_date == "2026-09-20"


def test_pasting_an_older_notice_does_not_roll_the_progress_back(db_session):
    apply_merges(db_session, [_record(status=STATUS_INTERVIEW)])
    preview = preview_merges(db_session, [_record(status=STATUS_APPLIED)])
    assert preview[0].action == MERGE_UNCHANGED
    assert "更早" in preview[0].reason

    apply_merges(db_session, [_record(status=STATUS_APPLIED)])
    assert list_tracks(db_session)[0].status == STATUS_INTERVIEW


def test_one_batch_with_several_notices_for_the_same_position_collapses(db_session):
    """一封邮件里连着「已投递 → 测评 → 面试」时，只该得到一条记录。"""
    preview = preview_merges(
        db_session,
        [
            _record(status=STATUS_APPLIED),
            _record(status=STATUS_ASSESSMENT),
            _record(status=STATUS_INTERVIEW),
        ],
    )
    assert len(preview) == 1
    assert preview[0].action == MERGE_CREATED
    assert preview[0].record.status == STATUS_INTERVIEW
    assert "3 条通知" in preview[0].reason

    apply_merges(
        db_session,
        [
            _record(status=STATUS_APPLIED),
            _record(status=STATUS_ASSESSMENT),
            _record(status=STATUS_INTERVIEW),
        ],
    )
    stored = list_tracks(db_session)
    assert len(stored) == 1
    assert stored[0].status == STATUS_INTERVIEW


def test_merging_does_not_wipe_fields_the_notice_did_not_mention(db_session):
    apply_merges(
        db_session,
        [
            _record(
                next_action="准备自我介绍",
                next_action_date="2026-09-19",
                note="HR 说会电话联系",
            )
        ],
    )
    # 只写了"进入面试"的通知不该把上一条记的下一步和备注抹掉。
    apply_merges(db_session, [_record(status=STATUS_INTERVIEW, evidence="恭喜进入面试环节")])
    stored = list_tracks(db_session)[0]
    assert stored.status == STATUS_INTERVIEW
    assert stored.next_action == "准备自我介绍"
    assert stored.next_action_date == "2026-09-19"
    assert "HR 说会电话联系" in stored.note
    assert stored.evidence == "恭喜进入面试环节"


def test_notes_are_appended_not_replaced(db_session):
    apply_merges(db_session, [_record(note="第一条")])
    apply_merges(db_session, [_record(status=STATUS_SCREENING, note="第二条")])
    note = list_tracks(db_session)[0].note
    assert "第一条" in note and "第二条" in note


def test_unchanged_records_still_keep_the_new_evidence(db_session):
    """用户可能正是为了留下这封通知的原文才导入它的。"""
    apply_merges(db_session, [_record(status=STATUS_INTERVIEW)])
    assert list_tracks(db_session)[0].evidence == ""
    apply_merges(db_session, [_record(status=STATUS_APPLIED, evidence="感谢您的投递")])
    assert list_tracks(db_session)[0].evidence == "感谢您的投递"


def test_different_positions_stay_separate(db_session):
    apply_merges(
        db_session,
        [
            _record(title="后端开发实习生"),
            _record(title="算法实习生"),
            _record(company="另一家公司"),
        ],
    )
    assert len(list_tracks(db_session)) == 3


# ===== 与投递台的接合点 =====


def test_record_applied_creates_a_row_with_todays_date(db_session):
    from app.models.job import Job

    job = Job(title="后端开发实习生", company="示例科技")
    db_session.add(job)
    db_session.commit()

    record_applied(
        db_session, company="示例科技", title="后端开发实习生", job_id=job.id
    )
    db_session.commit()
    stored = list_tracks(db_session)[0]
    assert stored.status == STATUS_APPLIED
    assert stored.source == SOURCE_APPLY
    assert stored.applied_at == date.today().isoformat()
    assert stored.job_id == job.id


def test_record_applied_never_pulls_a_later_status_back(db_session):
    """用户已经手动推到「面试」了，投递台的批量任务又跑了一次同一个岗位。"""
    apply_merges(db_session, [_record(status=STATUS_INTERVIEW)])
    record_applied(db_session, company="示例科技", title="后端开发实习生")
    db_session.commit()
    assert list_tracks(db_session)[0].status == STATUS_INTERVIEW


def test_record_applied_skips_blank_snapshots(db_session):
    """岗位被删掉后条目上的快照可能是空的——别造一条「(空) · (空)」。"""
    record_applied(db_session, company="", title="后端开发")
    record_applied(db_session, company="示例科技", title="  ")
    db_session.commit()
    assert list_tracks(db_session) == []


# ===== 增删改查与统计 =====


def test_crud_round_trip(db_session):
    created = create_track(db_session, TrackCreate(**_record().model_dump()))
    assert created.id
    assert created.company_key == normalize_key("示例科技")

    updated = update_track(
        db_session,
        created,
        TrackCreate(**_record(status=STATUS_OFFER, note="已接受").model_dump()),
    )
    assert updated.status == STATUS_OFFER
    assert delete_track(db_session, created.id) is True
    assert delete_track(db_session, created.id) is False


def test_list_filters_and_orders_by_stage(db_session):
    apply_merges(
        db_session,
        [
            _record(title="A 岗", status=STATUS_APPLIED),
            _record(title="B 岗", status=STATUS_INTERVIEW),
            _record(title="C 岗", status=STATUS_REJECTED),
        ],
    )
    titles = [item.title for item in list_tracks(db_session)]
    # 面试排最前、结束的排最后：打开页面最想先看到还在推进的。
    assert titles[0] == "B 岗"
    assert titles[-1] == "C 岗"

    assert [item.title for item in list_tracks(db_session, status=STATUS_REJECTED)] == ["C 岗"]
    assert [item.title for item in list_tracks(db_session, keyword="A 岗")] == ["A 岗"]


def test_summarize_counts_each_stage_and_this_month(db_session):
    today = date.today().isoformat()
    apply_merges(
        db_session,
        [
            _record(title="A 岗", status=STATUS_APPLIED, applied_at=today),
            _record(title="B 岗", status=STATUS_INTERVIEW, applied_at=today),
            _record(title="C 岗", status=STATUS_REJECTED, applied_at="2020-01-01"),
        ],
    )
    summary = summarize(list_tracks(db_session))
    assert summary["total"] == 3
    assert summary["status_counts"][STATUS_APPLIED] == 1
    assert summary["status_counts"][STATUS_INTERVIEW] == 1
    assert summary["active_count"] == 2  # 已投递 + 面试
    assert summary["rejected_count"] == 1
    assert summary["month_count"] == 2
    # 没有的状态也要出现在计数里，界面不用再补 0。
    assert summary["status_counts"][STATUS_OFFER] == 0


# ===== 导出 =====


def test_csv_export_has_a_bom_and_readable_status(db_session):
    apply_merges(db_session, [_record(status=STATUS_INTERVIEW, note="换行\n备注")])
    text = to_csv(list_tracks(db_session))
    # 不带 BOM 的 UTF-8 CSV 在 Excel 里中文是乱码，而这份文件最常见的用途就是丢进 Excel。
    assert text.startswith("﻿")
    assert "面试" in text
    # 换行必须被压平，否则一条记录会被拆成两行。
    assert "换行 备注" in text
    assert len(text.splitlines()) == 2


def test_json_export_carries_labels_not_raw_codes(db_session):
    import json

    apply_merges(db_session, [_record(status=STATUS_OFFER)])
    payload = json.loads(to_json(list_tracks(db_session)))
    assert payload["总数"] == 1
    assert payload["记录"][0]["状态"] == "Offer"


def test_export_rows_cover_every_column(db_session):
    apply_merges(db_session, [_record()])
    rows = export_rows(list_tracks(db_session))
    assert len(rows) == 1
    assert len(rows[0]) == 9


# ===== Schema 校验 =====


def test_records_must_identify_a_position():
    with pytest.raises(ValidationError):
        TrackRecordIn(title="后端开发")
    with pytest.raises(ValidationError):
        TrackRecordIn(company="示例科技")


def test_unknown_status_and_bad_dates_are_rejected():
    with pytest.raises(ValidationError):
        TrackRecordIn(company="A", title="B", status="大概吧")
    with pytest.raises(ValidationError):
        TrackRecordIn(company="A", title="B", status_date="2026-02-31")
    with pytest.raises(ValidationError):
        TrackRecordIn(company="A", title="B", applied_at="2026/09/18")
    # 留空是允许的：很多通知里根本没有日期。
    assert TrackRecordIn(company="A", title="B").status_date == ""


def test_plan_actions_are_the_documented_three():
    """合并结论只有三种，界面与导出都按这三种来呈现。"""
    from app.models.tracker import MERGE_RESULTS

    assert set(MERGE_RESULTS) == {MERGE_CREATED, MERGE_UPDATED, MERGE_UNCHANGED}


def test_plan_list_is_empty_for_no_records(db_session):
    assert plan_merges(db_session, []) == []
