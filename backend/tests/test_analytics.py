"""R-14 求职数据看板：四指标口径与 STATUSES 一致、六阶段漏斗、月度趋势。

口径唯一来源 ``models/tracker.py``：投递总量 / 有效投递数 / 面试数 / 面试率 /
测评笔试数 / 笔试通过率 / Offer 数，全部由 ``STATUSES`` / ``STATUS_RANK`` 推导，
本测试钉住这些数字，防止看板另写一份枚举导致漂移。
"""
from datetime import date

from app.models.tracker import (
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
    normalize_key,
)


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
