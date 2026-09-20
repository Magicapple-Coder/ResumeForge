"""候选岗位导入岗位广场：逐条如实反馈、不造重复、不覆盖已有岗位。

这条链路是"采集 → 挑选 → 入库"的最后一步，也是最容易出错的一步：判重写松了会在岗位广场
留下重复岗位，写紧了会把用户真正想要的岗位当成"已存在"悄悄丢掉（而界面上只显示"导入 7 条"，
用户根本不知道少了哪 3 条）。所以这里把四种结果逐一钉住。
"""
from app.models.job import Job
from app.models.material import CANDIDATE_JOB_IMPORTED, CANDIDATE_JOB_PENDING, CandidateJob
from app.schemas.material import CandidateJobCreate
from app.services.candidate_jobs import (
    create_candidate_job,
    import_candidates,
    stage_candidate_job,
)


def _stage(db_session, **overrides) -> CandidateJob:
    data = {
        "title": "后端开发",
        "company": "A公司",
        "location": "天津",
        "salary": "20-30K",
        "source_url": "https://example.com/1",
        "description": "岗位职责：负责后端服务的设计与开发。",
        "requirements": "任职要求：三年以上经验。",
        "source": "示例站点",
        "task_id": 7,
    }
    data.update(overrides)
    candidate = stage_candidate_job(db_session, **data)
    db_session.commit()
    return candidate


def test_import_creates_a_job_and_marks_the_candidate_imported(db_session):
    candidate = _stage(db_session)

    outcome = import_candidates(db_session, [candidate.id])

    assert outcome["imported"] == 1
    assert outcome["results"][0]["outcome"] == "imported"

    job = db_session.query(Job).one()
    assert job.title == "后端开发"
    assert job.company == "A公司"
    assert job.location == "天津"
    assert job.salary == "20-30K"
    assert job.source_url == "https://example.com/1"
    # 采集已经切好的两段各归各位——不要在导入时又混回一段。
    assert job.description == "岗位职责：负责后端服务的设计与开发。"
    assert job.requirements == "任职要求：三年以上经验。"
    # 来源标注（沿用既有约定：写进备注便于溯源）。
    assert "来源：岗位采集" in job.note

    db_session.refresh(candidate)
    assert candidate.status == CANDIDATE_JOB_IMPORTED
    assert candidate.imported_job_id == job.id


def test_manual_candidate_is_recorded_with_the_candidate_source(db_session):
    """手动粘贴来的候选（没有采集批次）来源应是「备选岗位导入」，不是「岗位采集」。"""
    # 走真实的手动链路（``create_candidate_job``）：粘贴文本进 raw_text，没有采集批次。
    candidate = create_candidate_job(
        db_session,
        CandidateJobCreate(title="后端开发", company="A公司", raw_text="粘贴来的招聘原文"),
    )

    import_candidates(db_session, [candidate.id])

    job = db_session.query(Job).one()
    assert "来源：备选岗位导入" in job.note
    # 没有 description 的候选退回用原文填描述（与改版前的导入行为一致）。
    assert job.description == "粘贴来的招聘原文"
    # 手动候选的 source 与"手动录入"保持一致（不传就会落到默认值「手动添加」）。
    assert job.source == "手动添加"


def test_import_parses_skill_keywords_from_the_jd(db_session):
    """导入时必须算技能标签——写入路径走 ``create_job_record``（内部 ``refresh_job_keywords``）。

    回归：早期采集器有一条自己直写 ``job`` 表的老路径，只写正文、从不解析标签，于是库里
    留下了一批 ``keywords='[]'`` 的采集岗位（列表页标签栏空白、搜索与匹配按空标签走）。
    这条断言就是防它回归的——此前本文件一条 keywords 断言都没有，正是这个 bug 能长期存在的原因。
    """
    candidate = _stage(
        db_session,
        title="后端开发工程师",
        source_url="https://example.com/jd-with-skills",
        description="岗位职责：负责服务端接口开发。技术栈：Java、Spring Boot、MySQL、Redis。",
        requirements="任职要求：熟悉 JavaScript 与 Docker。",
    )

    import_candidates(db_session, [candidate.id])

    job = db_session.query(Job).one()
    names = {tag["name"] for tag in job.keywords}
    assert names, "导入后技能标签不该为空"
    assert {"Java", "Spring Boot", "MySQL", "Redis", "JavaScript", "Docker"} <= names


def test_import_keeps_the_candidate_source(db_session):
    """采集导入的岗位要带上真实来源（站点名），而不是落到默认的「手动添加」。

    回归：新导入路径曾漏传 ``source``，于是采集来的岗位全被标成「手动添加」，
    "区分手动添加与自动采集"这件事就基于错误数据。站点名口径与旧采集器写进
    ``job.source`` 的一致（如「BOSS直聘」）。
    """
    candidate = _stage(db_session, source="BOSS直聘")

    import_candidates(db_session, [candidate.id])

    job = db_session.query(Job).one()
    assert job.source == "BOSS直聘"


def test_import_writes_job_type_from_the_candidate(db_session):
    """采集透传的岗位类型要写进正式岗位（仅标注，不入去重判据）。"""
    candidate = _stage(db_session, job_type="实习")

    import_candidates(db_session, [candidate.id])

    assert db_session.query(Job).one().job_type == "实习"


def test_import_falls_back_to_default_job_type_when_candidate_has_none(db_session):
    """候选没标岗位类型（手动粘贴/历史数据）时回落「校招」。"""
    candidate = _stage(db_session)

    import_candidates(db_session, [candidate.id])

    assert db_session.query(Job).one().job_type == "校招"


def test_import_points_at_the_existing_job_instead_of_creating_a_duplicate(db_session):
    """岗位广场里已经有同一链接的岗位 → 直接指向它，**不**再建一条。"""
    existing = Job(title="后端开发（旧）", company="A公司", source_url="https://example.com/1")
    db_session.add(existing)
    db_session.commit()
    candidate = _stage(db_session)

    outcome = import_candidates(db_session, [candidate.id])

    assert outcome["imported"] == 0
    assert outcome["duplicate"] == 1
    assert outcome["results"][0]["job_id"] == existing.id
    assert db_session.query(Job).count() == 1
    db_session.refresh(candidate)
    assert candidate.imported_job_id == existing.id


def test_import_reports_invalid_when_the_candidate_has_no_title(db_session):
    """没有岗位名的候选成为不了一个正式岗位——如实说"这条导不了"，而不是硬塞个空标题。"""
    candidate = _stage(db_session, title="", company="", source_url="")

    outcome = import_candidates(db_session, [candidate.id])

    assert outcome["invalid"] == 1
    assert outcome["results"][0]["outcome"] == "invalid"
    assert db_session.query(Job).count() == 0
    db_session.refresh(candidate)
    # 没导入成功就不能标成"已导入"，否则用户再也找不到这条候选。
    assert candidate.status == CANDIDATE_JOB_PENDING


def test_import_reports_missing_for_unknown_ids(db_session):
    outcome = import_candidates(db_session, [999])

    assert outcome["missing"] == 1
    assert outcome["results"][0]["outcome"] == "missing"


def test_import_is_idempotent(db_session):
    """重复点"导入"不该在岗位广场里攒出第二份副本。"""
    candidate = _stage(db_session)

    first = import_candidates(db_session, [candidate.id])
    second = import_candidates(db_session, [candidate.id])

    assert first["imported"] == 1
    assert second["duplicate"] == 1
    assert db_session.query(Job).count() == 1


def test_import_ignores_a_repeated_id_in_one_request(db_session):
    candidate = _stage(db_session)

    outcome = import_candidates(db_session, [candidate.id, candidate.id])

    assert outcome["imported"] == 1
    assert db_session.query(Job).count() == 1


def test_import_endpoint_returns_per_candidate_outcomes(db_session, client):
    """接口层同样要**逐条**反馈：用户勾了 3 条、其中 1 条重复时，他需要知道是哪一条。"""
    db_session.add(Job(title="已存在的岗位", company="C公司", source_url="https://example.com/2"))
    db_session.commit()
    kept = _stage(db_session, title="新岗位", company="B公司", source_url="https://example.com/3")
    duplicate = _stage(db_session, title="已存在的岗位", company="C公司", source_url="https://example.com/2")

    response = client.post(
        "/api/candidate-jobs/import", json={"candidate_ids": [kept.id, duplicate.id]}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported"] == 1
    assert body["duplicate"] == 1
    outcomes = {item["candidate_id"]: item["outcome"] for item in body["results"]}
    assert outcomes == {kept.id: "imported", duplicate.id: "duplicate"}


def test_import_endpoint_rejects_an_empty_selection(client):
    response = client.post("/api/candidate-jobs/import", json={"candidate_ids": []})

    assert response.status_code == 422
