"""R-14 求职数据看板：四指标口径与 STATUSES 一致、六阶段漏斗、月度趋势。

口径唯一来源 ``models/tracker.py``：投递总量 / 有效投递数 / 面试数 / 面试率 /
测评笔试数 / 笔试通过率 / Offer 数，全部由 ``STATUSES`` / ``STATUS_RANK`` 推导，
本测试钉住这些数字，防止看板另写一份枚举导致漂移。
"""
from datetime import date, datetime, timedelta

from app.models.profile import utcnow
from app.models.referral import REFERRAL_STATUSES
from app.models.reminder import Reminder
from app.models.tracker import (
    SOURCE_LABELS,
    SOURCES,
    STATUSES,
    STATUS_LABELS,
    STATUS_APPLIED,
    STATUS_ASSESSMENT,
    STATUS_INTERVIEW,
    STATUS_OFFER,
    STATUS_REJECTED,
    STATUS_SCREENING,
    STATUS_UNKNOWN,
    ApplicationTrack,
    is_stalled,
    normalize_key,
)
from app.models.resume import ResumeRecord
from app.services import resume_health as resume_health_service
from app.services import trash
from app.services.analytics import TOP_COMPANY_LIMIT, build_dashboard, dashboard_brief
from app.services.referral_service import referral_stats


def _track(db_session, company, title, status, applied_at=""):
    track = ApplicationTrack(
        company=company,
        title=title,
        company_key=normalize_key(company),
        title_key=normalize_key(title),
        status=status,
        applied_at=applied_at,
    )
    db_session.add(track)
    db_session.commit()
    db_session.refresh(track)
    return track


def test_dashboard_metrics_match_tracker_statuses(client, db_session):
    # 七种状态各一条，覆盖漏斗全部阶段。
    _track(db_session, "A", "t", STATUS_APPLIED, "2026-08-01")
    _track(db_session, "B", "t", STATUS_SCREENING, "2026-08-05")
    _track(db_session, "C", "t", STATUS_ASSESSMENT, "2026-08-10")
    _track(db_session, "D", "t", STATUS_INTERVIEW, "2026-08-15")
    _track(db_session, "E", "t", STATUS_OFFER, "2026-08-20")
    _track(db_session, "F", "t", STATUS_REJECTED, "2026-08-25")
    _track(db_session, "G", "t", STATUS_UNKNOWN, "")

    data = client.get("/api/analytics/dashboard").json()

    assert data["total_applications"] == 7
    # 有效投递 = 总量减去「待确认」。
    assert data["valid_applications"] == 6
    # 面试数 = interview + offer。
    assert data["interview_count"] == 2
    assert data["interview_rate"] == round(2 / 6, 4)
    # 测评笔试数 = assessment + interview + offer；笔试通过率 = 面试数 / 测评笔试数。
    assert data["assessment_count"] == 3
    assert data["assessment_to_interview_count"] == 2
    assert data["assessment_pass_rate"] == round(2 / 3, 4)
    assert data["offer_count"] == 1

    # 漏斗顺序与 STATUSES 逐字一致，标签来自 STATUS_LABELS。
    funnel = data["funnel"]
    assert [stage["status"] for stage in funnel] == list(STATUSES)
    for stage in funnel:
        assert stage["label"] == STATUS_LABELS[stage["status"]]
    counts = {stage["status"]: stage["count"] for stage in funnel}
    for status in STATUSES:
        assert counts[status] == 1


def test_dashboard_empty_when_no_tracks(client):
    data = client.get("/api/analytics/dashboard").json()

    assert data["total_applications"] == 0
    assert data["valid_applications"] == 0
    assert data["interview_count"] == 0
    assert data["interview_rate"] == 0.0
    assert data["assessment_count"] == 0
    assert data["assessment_pass_rate"] == 0.0
    assert data["offer_count"] == 0
    assert [stage["count"] for stage in data["funnel"]] == [0] * len(STATUSES)
    assert all(point["count"] == 0 for point in data["trend"])


def test_trend_counts_applied_by_month(client, db_session):
    prefix = date.today().strftime("%Y-%m")
    _track(db_session, "本月", "t", STATUS_APPLIED, f"{prefix}-15")
    _track(db_session, "本月2", "t", STATUS_APPLIED, f"{prefix}-20")

    data = client.get("/api/analytics/dashboard").json()
    # 趋势按自然月聚合，当月应是最后一个点且计数 >= 2。
    assert data["trend"][-1]["month"] == prefix
    assert data["trend"][-1]["count"] == 2


def test_trend_months_controls_trend_length(client):
    # 接口新增 ?trend_months= 之后，趋势点数随参数变化，默认仍是 6。
    assert len(client.get("/api/analytics/dashboard", params={"trend_months": 3}).json()["trend"]) == 3
    assert len(client.get("/api/analytics/dashboard", params={"trend_months": 12}).json()["trend"]) == 12
    assert len(client.get("/api/analytics/dashboard").json()["trend"]) == 6


def test_trend_months_out_of_range_rejected(client):
    assert client.get("/api/analytics/dashboard", params={"trend_months": 0}).status_code == 422
    assert client.get("/api/analytics/dashboard", params={"trend_months": 25}).status_code == 422


# ===== 以下是四主题区块新增指标的口径守卫 =====


def test_is_stalled_boundaries():
    """``is_stalled`` 是纯谓词，边界不碰数据库就能钉死。"""
    now = datetime(2026, 9, 20, 12, 0, 0)

    # 恰好 7 天算"还没超"——与原 ``updated_at < now - 7d`` 的严格小于等价。
    assert is_stalled(STATUS_APPLIED, now - timedelta(days=7), now) is False
    assert is_stalled(STATUS_APPLIED, now - timedelta(days=7, seconds=1), now) is True
    # 刚更新过的当然不算。
    assert is_stalled(STATUS_APPLIED, now, now) is False
    # 终态不叫卡住：流程走完了，再久没动也只是归档。
    assert is_stalled(STATUS_REJECTED, now - timedelta(days=365), now) is False
    assert is_stalled(STATUS_OFFER, now - timedelta(days=365), now) is False
    # 没有时间戳就不该被点名。
    assert is_stalled(STATUS_APPLIED, None, now) is False


def test_stalled_count_matches_stats_endpoint(client, db_session):
    """看板的 ``stalled_count`` 与首页 ``/api/stats`` 必须给出同一个数。

    **这是本轮最重要的不变量**：两处读同一份阈值与判定（``models/tracker`` 的
    ``STALLED_DAYS`` / ``is_stalled``）。谁再把规则内联一遍、或把两边的阈值改岔，
    这条用例立刻红——否则用户会看到卡片标红而统计不计数。
    """
    stalled = _track(db_session, "卡住", "t", STATUS_APPLIED)
    stalled.updated_at = utcnow() - timedelta(days=10)
    _track(db_session, "在推进", "t", STATUS_SCREENING)
    finished = _track(db_session, "已结束", "t", STATUS_REJECTED)
    finished.updated_at = utcnow() - timedelta(days=30)
    db_session.commit()

    dashboard = client.get("/api/analytics/dashboard").json()
    stats = client.get("/api/stats").json()

    # 只有"进行中且超 7 天没更新"的那一条：终态的已结束不算。
    assert dashboard["stalled_count"] == 1
    assert stats["stalled_application_count"] == dashboard["stalled_count"]


def test_active_and_no_next_action_counts(client, db_session):
    _track(db_session, "A", "t", STATUS_APPLIED)  # 进行中、没有下一步
    _track(db_session, "B", "t", STATUS_SCREENING)
    _track(db_session, "C", "t", STATUS_OFFER)
    _track(db_session, "D", "t", STATUS_REJECTED)
    with_action = _track(db_session, "E", "t", STATUS_INTERVIEW)
    with_action.next_action = "确认面试时间"
    db_session.commit()

    data = client.get("/api/analytics/dashboard").json()

    # 进行中 = applied / screening / interview 三条；Offer 与已结束是终态，不算"在流程中"。
    assert data["active_count"] == 3
    # 「没有下一步」只在进行中里数：A、B 没有，E 有。
    assert data["no_next_action_count"] == 2


def test_offer_rate_shares_denominator_with_interview_rate(client, db_session):
    _track(db_session, "A", "t", STATUS_OFFER)
    _track(db_session, "B", "t", STATUS_REJECTED)
    _track(db_session, "C", "t", STATUS_UNKNOWN)  # 待确认不进分母

    data = client.get("/api/analytics/dashboard").json()

    assert data["valid_applications"] == 2
    assert data["offer_rate"] == round(1 / 2, 4)
    assert data["interview_rate"] == round(1 / 2, 4)


def test_applied_date_gap_agrees_with_trend_and_weekday(client, db_session):
    """缺口计数与两张图必须自洽——这是"不许说谎的零"的落地。

    没有这组数字，一张全零的趋势图会被读成"这几个月真的一份没投"，而事实是那些记录
    根本没填日期。
    """
    prefix = date.today().strftime("%Y-%m")
    _track(db_session, "有日期一", "t", STATUS_APPLIED, f"{prefix}-10")
    _track(db_session, "有日期二", "t", STATUS_APPLIED, f"{prefix}-11")
    _track(db_session, "没填", "t", STATUS_APPLIED, "")
    _track(db_session, "写坏了", "t", STATUS_APPLIED, "不是日期")

    data = client.get("/api/analytics/dashboard").json()

    gap = data["applied_date_gap"]
    assert (gap["dated"], gap["undated"], gap["total"]) == (2, 2, 4)
    # 趋势与周内分布只落有日期的记录，且两张图加起来正好等于 dated。
    assert data["trend"][-1]["count"] == gap["dated"]
    assert sum(bucket["count"] for bucket in data["weekday"]) == gap["dated"]


def test_weekday_buckets_use_the_applied_weekday(client, db_session):
    # 2026-09-21 是周一；固定日期而不是 date.today()，结果与运行日期无关。
    _track(db_session, "周一", "t", STATUS_APPLIED, "2026-09-21")
    _track(db_session, "也是周一", "t", STATUS_APPLIED, "2026-09-28")
    _track(db_session, "周三", "t", STATUS_APPLIED, "2026-09-23")

    weekday = client.get("/api/analytics/dashboard").json()["weekday"]

    assert len(weekday) == 7
    assert [bucket["label"] for bucket in weekday] == [
        "周一",
        "周二",
        "周三",
        "周四",
        "周五",
        "周六",
        "周日",
    ]
    counts = {bucket["label"]: bucket["count"] for bucket in weekday}
    assert counts["周一"] == 2
    assert counts["周三"] == 1
    assert counts["周二"] == 0


def test_top_companies_group_by_normalized_key(client, db_session):
    """归并键是 ``company_key``（去空白/全角半角统一），不是 ``company`` 原文。"""
    _track(db_session, "腾讯", "岗位一", STATUS_APPLIED)
    _track(db_session, " 腾讯 ", "岗位二", STATUS_APPLIED)  # 归一化后同一个 key
    _track(db_session, "字节", "岗位三", STATUS_APPLIED)

    data = client.get("/api/analytics/dashboard").json()

    ranking = {item["label"]: item["count"] for item in data["top_companies"]}
    assert ranking == {"腾讯": 2, "字节": 1}
    assert data["other_company_count"] == 0


def test_top_companies_marks_garbage_as_unknown(client, db_session):
    """明显非公司名（纯数字 ID、单字垃圾、空）归并到「未填写公司」，不展示脏数据。

    这是"渠道与去向"里之前把 ``2112`` ``23432`` ``它`` 当公司名展示的修复：历史脏数据
    不强制回填，但只读聚合时按同一规则兜底，宁可少显示真公司也不把垃圾当公司名。
    """
    _track(db_session, "2112", "t", STATUS_APPLIED)  # 纯数字，识别导入残留的 ID
    _track(db_session, "它", "t", STATUS_APPLIED)  # 单字垃圾
    _track(db_session, "", "t", STATUS_APPLIED)  # 没填公司
    _track(db_session, "腾讯", "t", STATUS_APPLIED)

    data = client.get("/api/analytics/dashboard").json()

    ranking = {item["label"]: item["count"] for item in data["top_companies"]}
    # 三条脏数据 + 一条空，全部归并到中性占位；真公司单独成行。
    assert ranking.get("未填写公司") == 3
    assert ranking.get("腾讯") == 1
    # 脏数据不再以原值（"2112"/"它"）出现。
    assert "2112" not in ranking
    assert "它" not in ranking


def test_top_companies_fold_the_tail_into_other(client, db_session):
    for index in range(TOP_COMPANY_LIMIT + 3):
        _track(db_session, f"公司{index:02d}", "t", STATUS_APPLIED)

    data = client.get("/api/analytics/dashboard").json()

    assert len(data["top_companies"]) == TOP_COMPANY_LIMIT
    assert data["other_company_count"] == 3
    # 长尾没有被丢掉：榜内 + 其他 == 全部有公司键的记录。
    assert sum(item["count"] for item in data["top_companies"]) + data["other_company_count"] == (
        TOP_COMPANY_LIMIT + 3
    )


def test_record_sources_use_the_shared_vocabulary(client, db_session):
    _track(db_session, "A", "t", STATUS_APPLIED)
    data = client.get("/api/analytics/dashboard").json()

    assert [item["key"] for item in data["record_sources"]] == list(SOURCES)
    assert {item["key"]: item["label"] for item in data["record_sources"]} == dict(SOURCE_LABELS)


def test_referral_block_equals_referral_service_stats(client, db_session):
    """内推块直接搬运 ``referral_stats``，不自己算第二份转化率。"""
    client.post("/api/referrals", json={"company": "甲", "job_title": "后端"})
    client.post("/api/referrals", json={"company": "乙", "job_title": "前端"})

    data = client.get("/api/analytics/dashboard").json()
    expected = referral_stats(db_session)

    assert data["referral"]["total"] == expected.total
    assert data["referral"]["converted"] == expected.converted
    assert data["referral"]["rate"] == expected.rate
    # 内推状态只回键与计数，中文名归前端，后端不写第二份。
    assert [item["key"] for item in data["referral_status"]] == list(REFERRAL_STATUSES)


def test_reminder_counts_reuse_shared_urgency(client, db_session):
    """已逾期的必须进 ``overdue`` 而不是 ``soon``——四档阈值只有一处实现。"""
    now = utcnow()
    for remind_at in (now - timedelta(days=2), now + timedelta(hours=3), now + timedelta(days=2)):
        db_session.add(Reminder(title="提醒", remind_at=remind_at))
    db_session.commit()

    data = client.get("/api/analytics/dashboard").json()

    assert data["reminder_counts"]["overdue"] == 1
    assert data["reminder_counts"]["soon"] == 1
    assert data["reminder_counts"]["upcoming"] == 1
    assert data["reminder_counts"]["later"] == 0
    assert data["reminder_counts"]["total"] == 3


def test_soft_deleted_rows_are_excluded_from_new_metrics(client, db_session):
    _track(db_session, "留着", "t", STATUS_APPLIED, "2026-09-21")
    doomed = _track(db_session, "删掉", "t", STATUS_APPLIED, "2026-09-21")
    doomed.updated_at = utcnow() - timedelta(days=30)
    db_session.commit()

    before = client.get("/api/analytics/dashboard").json()
    trash.soft_delete(db_session, "application_track", doomed)
    db_session.commit()
    after = client.get("/api/analytics/dashboard").json()

    assert after["total_applications"] == before["total_applications"] - 1
    assert after["stalled_count"] == 0
    assert after["applied_date_gap"]["total"] == 1
    assert sum(item["count"] for item in after["top_companies"]) == 1


def test_dashboard_empty_state_is_zero_not_none(client):
    """空库时每个新键都有明确零值——前端据此渲染空态，不必到处判空。"""
    data = client.get("/api/analytics/dashboard").json()

    for key in (
        "active_count",
        "stalled_count",
        "no_next_action_count",
        "offer_rate",
        "recent_7d_count",
        "recent_30d_count",
        "other_company_count",
        "resume_count",
        "unverified_claim_count",
        "track_resume_linked_count",
    ):
        assert data[key] == 0, key
    assert data["applied_date_gap"] == {"dated": 0, "undated": 0, "total": 0}
    assert len(data["weekday"]) == 7
    assert all(bucket["count"] == 0 for bucket in data["weekday"])
    assert data["top_companies"] == []
    assert data["record_sources"]
    assert data["referral"] == {"total": 0, "converted": 0, "rate": 0.0}
    assert data["reminder_counts"] == {
        "overdue": 0,
        "soon": 0,
        "upcoming": 0,
        "later": 0,
        "total": 0,
    }


def test_resume_health_counts_and_survives_dirty_content(client, db_session):
    """一份 content 解析不了的简历不能让整个看板 500，也不能被算成"完好的"。"""
    db_session.add(ResumeRecord(title="好简历", content={}))
    db_session.add(ResumeRecord(title="有提醒", content={}, warnings=["项目经历缺量化"]))
    db_session.add(ResumeRecord(title="脏数据", content={"education": "不是列表"}))
    db_session.commit()

    response = client.get("/api/analytics/dashboard")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["resume_count"] == 3
    assert data["resume_scanned_count"] == 3
    assert data["resume_with_warnings_count"] == 1


def test_resume_health_scan_is_capped_and_still_reports_the_real_total(
    client, db_session, monkeypatch
):
    for index in range(3):
        db_session.add(ResumeRecord(title=f"简历{index}", content={}))
    db_session.commit()
    # 把扫描窗口压到 2：总数必须仍是真实值，扫描数如实回报——这样前端能说明
    # "这个待补数是最近扫过的那批里的"，而不是让一个抽样值冒充全量。
    monkeypatch.setattr(resume_health_service, "MAX_RESUME_SCAN", 2)

    data = client.get("/api/analytics/dashboard").json()

    assert data["resume_count"] == 3
    assert data["resume_scanned_count"] == 2


def test_dashboard_brief_keeps_scalars_and_drops_long_arrays(client, db_session):
    """助手拿到的是摘要视图：标量一个不少，长数组不塞进上下文。"""
    _track(db_session, "A", "t", STATUS_APPLIED, "2026-09-21")
    dashboard = build_dashboard(db_session)
    brief = dashboard_brief(dashboard)

    for key in ("total_applications", "offer_count", "funnel", "stalled_count", "referral"):
        assert key in brief
    for key in ("trend", "weekday", "referral_status"):
        assert key not in brief
    assert len(brief["top_companies"]) <= 5
