"""简历风险扫描：五类风险、只提示不改写、强主张台账联动、LLM 降级与提示词登记。"""
import json

from app import preflight
from app.models.claim import (
    RESPONSIBILITY_LED,
    RESPONSIBILITY_OWNER,
    RESPONSIBILITY_PARTICIPATED,
    VERIFICATION_CONFIRMED,
    VERIFICATION_REJECTED,
    ClaimRecord,
)
from app.models.resume import ResumeRecord
from app.schemas.resume import ResumeContent, ResumeProject
from app.schemas.setting import LLMConfig
from app.services.llm.base import BaseLLMProvider, LLMError
from app.services.resume.resume_risk import scan_local, scan_resume_risks


class RiskProvider(BaseLLMProvider):
    """返回预设 JSON 的假模型，用于可选增强路径。"""

    def __init__(self, payload):
        super().__init__(LLMConfig(base_url="http://fake", api_key="fake", model="fake-model"))
        self.payload = payload

    async def chat(self, messages):
        return json.dumps(self.payload, ensure_ascii=False)

    async def stream_chat(self, messages):
        yield ""


class BrokenProvider(RiskProvider):
    async def chat(self, messages):
        raise LLMError("模型调用失败")


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


def _strong_claim(**overrides):
    values = {
        "id": 42,
        "title": "主导交易系统",
        "subject": "交易系统",
        "candidate_wording": "主导交易系统从0到1建设",
        "responsibility_level": RESPONSIBILITY_LED,
        "verification_status": VERIFICATION_CONFIRMED,
        "boundary": "团队负责整体架构，我负责撮合引擎",
        "risk_notes": ["撮合延迟数据需现场核对"],
        "interview_details": {
            "decisions": ["放弃一致性哈希改用分段撮合"],
            "result": "P99 延迟降至 12ms",
        },
    }
    values.update(overrides)
    return ClaimRecord(**values)


def test_duplicate_points_are_detected():
    resume = ResumeContent(
        projects=[
            ResumeProject(name="项目A", description=["负责后端服务开发"]),
            ResumeProject(name="项目B", description=["负责后端服务开发"]),
        ]
    )
    points = scan_local(resume, [])
    duplicates = [p for p in points if p.category == "duplicate"]
    assert duplicates
    assert any("项目A" in p.location and "项目B" in p.location for p in duplicates)


def test_no_duplicate_when_points_are_unique():
    resume = ResumeContent(
        projects=[
            ResumeProject(name="项目A", description=["负责后端服务开发"]),
            ResumeProject(name="项目B", description=["负责前端页面开发"]),
        ]
    )
    points = scan_local(resume, [])
    assert not [p for p in points if p.category == "duplicate"]


def test_sensitive_risk_detected():
    resume = ResumeContent(summary="身份证号 110101199001011234，请勿泄露")
    points = scan_local(resume, [])
    sensitive = [p for p in points if p.category == "sensitive"]
    assert sensitive
    assert any(p.text == "110101199001011234" for p in sensitive)


def test_exaggeration_risk_detected():
    resume = ResumeContent(summary="精通后端开发，性能提升 300%")
    points = scan_local(resume, [])
    exaggerations = [p for p in points if p.category == "exaggeration"]
    assert any(p.text == "精通" for p in exaggerations)
    assert any(p.text == "300%" for p in exaggerations)


def test_compliance_risk_detected():
    resume = ResumeContent(summary="参与保密协议约束的核心项目")
    points = scan_local(resume, [])
    compliance = [p for p in points if p.category == "compliance"]
    assert any(p.text == "保密协议" for p in compliance)


def test_compliance_no_hit_when_clean():
    resume = ResumeContent(summary="负责后端服务开发")
    points = scan_local(resume, [])
    assert not [p for p in points if p.category == "compliance"]


def test_scan_never_mutates_resume():
    resume = ResumeContent(
        summary="精通后端开发，身份证 110101199001011234",
        projects=[
            ResumeProject(name="项目A", description=["负责后端服务开发", "负责后端服务开发"]),
        ],
    )
    snapshot = resume.model_dump()
    scan_local(resume, [])
    assert resume.model_dump() == snapshot


def test_strong_claim_linking_injects_follow_up():
    claim = _strong_claim()
    points = scan_local(ResumeContent(), [claim])
    linked = [p for p in points if p.category == "deep_dive" and p.claim_id == 42]
    assert linked
    point = linked[0]
    assert "个人边界：团队负责整体架构，我负责撮合引擎" in point.follow_up
    assert "风险备注：撮合延迟数据需现场核对" in point.follow_up
    assert any(item.startswith("关键决策：") for item in point.follow_up)
    assert any(item.startswith("结果：") for item in point.follow_up)


def test_non_strong_claim_is_not_linked():
    claim = _strong_claim(id=1, responsibility_level=RESPONSIBILITY_PARTICIPATED)
    points = scan_local(ResumeContent(), [claim])
    assert not [p for p in points if p.claim_id == 1]


def test_rejected_claim_is_not_linked():
    claim = _strong_claim(id=2, verification_status=VERIFICATION_REJECTED)
    points = scan_local(ResumeContent(), [claim])
    assert not [p for p in points if p.claim_id == 2]


def test_owner_level_is_also_a_strong_claim():
    claim = _strong_claim(id=7, responsibility_level=RESPONSIBILITY_OWNER)
    points = scan_local(ResumeContent(), [claim])
    assert [p for p in points if p.claim_id == 7]


async def test_llm_enhancement_marks_llm_used_and_merges_points():
    provider = RiskProvider(
        {
            "points": [
                {
                    "severity": "medium",
                    "text": "模型补充的深挖点",
                    "location": "正文",
                    "suggestion": "补充依据",
                    "follow_up": ["怎么验证"],
                }
            ]
        }
    )
    result = await scan_resume_risks(ResumeContent(summary="负责后端服务开发"), [], provider=provider, resume_id=1)
    assert result.llm_used is True
    assert any(p.text == "模型补充的深挖点" for p in result.points)


async def test_llm_error_degrades_to_local():
    resume = ResumeContent(summary="精通后端开发")
    result = await scan_resume_risks(resume, [], provider=BrokenProvider({}), resume_id=1)
    assert result.llm_used is False
    assert any("本地规则" in note for note in result.notes)
    assert any(p.category == "exaggeration" for p in result.points)


def test_risk_scan_endpoint_degrades_without_llm(client, db_session):
    record = _resume_record(db_session, content={"name": "张三", "summary": "精通后端开发"})
    response = client.post(f"/api/resumes/{record.id}/risk-scan")
    assert response.status_code == 200
    data = response.json()
    assert data["llm_used"] is False
    assert data["resume_id"] == record.id
    assert any(p["category"] == "exaggeration" for p in data["points"])


def test_risk_scan_endpoint_404s_for_missing_resume(client):
    response = client.post("/api/resumes/9999/risk-scan")
    assert response.status_code == 404


def test_risk_prompt_registered_in_preflight():
    covered = {relative for relative, _ in preflight._REQUIRED_FILES}
    assert "app/prompts/resume_risk.md" in covered
