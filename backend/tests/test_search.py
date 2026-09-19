"""全局搜索扩域：六类新数据域命中 / 未命中 / 软删过滤 / scope 过滤 / 向后兼容。

六个新数据域统一放进 ``SearchResult.more``（``SearchHit``），旧的 ``jobs`` / ``resumes``
字段保持不变。这里钉住：每域能命中且 ``path`` 指向真实前端路由、软删除的不出现、
``scope`` 能按需收窄、旧字段依然在。
"""
from datetime import datetime

import pytest

from app.models.claim import ClaimRecord
from app.models.interview_experience import InterviewExperience
from app.models.job import Job
from app.models.material import Material
from app.models.profile import Skill, UserProfile
from app.models.referral import Referral
from app.models.reminder import Reminder
from app.models.resume import ResumeRecord
from app.services import trash


def _add(db_session, row):
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def _make_referral(db_session):
    return _add(
        db_session,
        Referral(
            job_title="后端内推",
            company="字节跳动",
            referrer_name="内推人老李",
            position="后端开发",
        ),
    )


def _make_reminder(db_session):
    return _add(
        db_session,
        Reminder(title="催HR回复", note="面试后一周", remind_at=datetime(2026, 9, 20, 9, 0)),
    )


def _make_experience(db_session):
    return _add(
        db_session,
        InterviewExperience(
            title="后端一面", company="字节跳动", position="后端", content="问了一道算法题"
        ),
    )


def _make_claim(db_session):
    return _add(
        db_session,
        ClaimRecord(
            title="负责服务端开发",
            subject="简历通",
            category="项目经历",
            source_fact="带队开发",
            candidate_wording="主导服务端开发",
        ),
    )


def _make_material(db_session):
    return _add(db_session, Material(title="获奖证书", category="证书", content="一等奖"))


def _make_skill(db_session):
    profile = _add(db_session, UserProfile(name="张三", job_intent="后端开发"))
    return _add(db_session, Skill(profile_id=profile.id, name="Python", level="熟练"))


MAKERS = {
    "referral": _make_referral,
    "reminder": _make_reminder,
    "experience": _make_experience,
    "claim": _make_claim,
    "material": _make_material,
    "skill": _make_skill,
}

CASES = [
    ("referral", "内推人老李", "/apply"),
    ("reminder", "催HR回复", "/tracker"),
    ("experience", "后端一面", "/interview"),
    ("claim", "服务端开发", "/claims"),
    ("material", "获奖证书", "/materials"),
    ("skill", "Python", "/skills"),
]


@pytest.mark.parametrize("type_key,keyword,path", CASES)
def test_more_search_hits_each_domain(client, db_session, type_key, keyword, path):
    row = MAKERS[type_key](db_session)

    data = client.get("/api/search", params={"q": keyword}).json()

    hits = [hit for hit in data["more"] if hit["type"] == type_key]
    assert [hit["id"] for hit in hits] == [row.id]
    assert hits[0]["path"] == path
    assert hits[0]["title"]
    # 扩展域命中不污染旧字段。
    assert data["jobs"] == []
    assert data["resumes"] == []


def test_more_search_returns_empty_for_no_match(client, db_session):
    _make_referral(db_session)

    data = client.get("/api/search", params={"q": "完全不存在的关键词"}).json()

    assert data == {"jobs": [], "resumes": [], "more": []}


def test_more_search_filters_soft_deleted(client, db_session):
    referral = _make_referral(db_session)
    material = _make_material(db_session)

    trash.soft_delete(db_session, "referral", referral)
    trash.soft_delete(db_session, "material", material)
    db_session.commit()

    assert client.get("/api/search", params={"q": "内推人老李"}).json()["more"] == []
    assert client.get("/api/search", params={"q": "获奖证书"}).json()["more"] == []


def test_scope_filters_which_domains_are_searched(client, db_session):
    _make_referral(db_session)
    _make_reminder(db_session)

    # jobs 只查岗位，不碰扩展域。
    jobs_only = client.get("/api/search", params={"q": "内推人老李", "scope": "jobs"}).json()
    assert jobs_only["jobs"] == []
    assert jobs_only["more"] == []

    # more 只查扩展域，不碰岗位/简历。
    more_only = client.get("/api/search", params={"q": "内推人老李", "scope": "more"}).json()
    assert more_only["jobs"] == []
    assert more_only["resumes"] == []
    assert [hit["type"] for hit in more_only["more"]] == ["referral"]

    # all 同时查两处。
    all_scope = client.get("/api/search", params={"q": "内推人老李"}).json()
    assert [hit["type"] for hit in all_scope["more"]] == ["referral"]


def test_legacy_fields_still_present(client, db_session):
    _add(db_session, Job(title="后端开发", company="字节跳动"))
    _add(db_session, ResumeRecord(title="后端简历", job_title="后端开发"))

    data = client.get("/api/search", params={"q": "后端"}).json()

    assert data["jobs"]
    assert data["resumes"]
    # 新增字段始终存在（即使为空），旧字段原样保留。
    assert "more" in data
    assert data["more"] == []


def test_invalid_scope_rejected(client):
    response = client.get("/api/search", params={"q": "x", "scope": "bogus"})
    assert response.status_code == 422
