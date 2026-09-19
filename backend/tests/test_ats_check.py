"""ATS 本地检测：词库可加载、三类结论、免责声明、接口。"""
from app.models.resume import ResumeRecord
from app.schemas.resume import ResumeContent
from app.services.ats_check import ATS_DISCLAIMER, check_ats, load_keywords


def _resume_record(db_session, **kwargs):
    record = ResumeRecord(
        title=kwargs.get("title", "张三-后端开发工程师"),
        job_title="后端开发工程师",
        company="示例公司",
        content=kwargs.get("content", {"name": "张三"}),
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    return record


def test_keyword_library_is_loadable():
    words = load_keywords()
    assert words
    assert "Python" in words
    assert "MySQL" in words


def test_ats_check_includes_disclaimer():
    result = check_ats(ResumeContent())
    assert result.disclaimer == ATS_DISCLAIMER
    assert "不代表真实 ATS 解析结果" in result.disclaimer


def test_ats_check_reports_format_issue():
    resume = ResumeContent(name="", phone="", email="")
    result = check_ats(resume)
    titles = {issue.title for issue in result.issues if issue.category == "format"}
    assert "缺少姓名" in titles
    assert "缺少联系方式" in titles


def test_ats_check_reports_position_issue():
    resume = ResumeContent(name="张三", phone="13800138000", email="a@b.com")
    result = check_ats(resume)
    titles = {issue.title for issue in result.issues if issue.category == "position"}
    assert "缺少求职意向" in titles
    assert "缺少个人总结" in titles
    assert "缺少教育经历" in titles
    assert "缺少技能清单" in titles


def test_ats_check_keyword_coverage_with_jd():
    resume = ResumeContent(name="张三", phone="13800138000", email="a@b.com")
    result = check_ats(resume, jd_text="要求熟悉 Python 和 MySQL")
    assert "Python" in result.missing_keywords
    assert "MySQL" in result.missing_keywords


def test_ats_check_matched_keyword():
    resume = ResumeContent(
        name="张三", phone="13800138000", email="a@b.com", summary="熟悉 Python 后端开发"
    )
    result = check_ats(resume, jd_text="要求熟悉 Python")
    assert "Python" in result.matched_keywords


def test_ats_check_covers_all_three_categories_for_empty_resume():
    resume = ResumeContent()
    result = check_ats(resume)
    categories = {issue.category for issue in result.issues}
    assert categories == {"format", "keyword", "position"}


def test_ats_check_score_is_bounded():
    result = check_ats(ResumeContent())
    assert 0 <= result.score <= 100


def test_ats_check_endpoint_returns_result(client, db_session):
    record = _resume_record(db_session, content={"name": "张三", "summary": "熟悉 Python"})
    response = client.post(
        f"/api/resumes/{record.id}/ats-check", json={"jd_text": "要求熟悉 Python"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["disclaimer"] == ATS_DISCLAIMER
    assert "Python" in data["matched_keywords"]


def test_ats_check_endpoint_404s_for_missing_resume(client):
    response = client.post("/api/resumes/9999/ats-check", json={"jd_text": ""})
    assert response.status_code == 404
