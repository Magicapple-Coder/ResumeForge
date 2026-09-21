"""R-11 面试全流程辅助：题库三类分组、答题思路、反向优化只出建议不改正文。

重点验证三条硬约束：
1. 题库三类（基础/项目深挖/反问 HR）分组正确、即时生成不落库；
2. 未配置模型时接口返回清晰中文错误（不伪造结果）；
3. 反向优化只产出 ``ResumeSuggestion`` 建议列表，**不直接改写简历正文**。
"""
import json

import pytest

from app.models.job import Job
from app.models.resume import ResumeRecord
from app.schemas.resume import ResumeContent
from app.services.llm.base import LLMError
from app.services.interview.interview_questions import (
    analyze_question,
    generate_question_answer,
    generate_question_bank,
    optimize_resume,
    parse_analysis,
    parse_question_answer,
    parse_question_bank,
)

_BANK_JSON = json.dumps(
    {
        "基础题": [
            {"question": "请自我介绍", "purpose": "考察表达", "answer_hint": "按 STAR 展开"},
            {"question": "为什么想来", "purpose": "考察动机", "answer_hint": "结合 JD"},
        ],
        "项目深挖题": [
            {"question": "交易系统难点", "purpose": "考察取舍", "answer_hint": "说清个人边界"},
        ],
        "反问HR题": [
            {"question": "团队如何协作", "purpose": "了解团队", "answer_hint": "问成长路径"},
        ],
        "无关键": [{"question": "不该出现", "purpose": "x", "answer_hint": "y"}],
    },
    ensure_ascii=False,
)

_ANALYSIS_JSON = json.dumps(
    {
        "framework": "用 STAR 结构：先说结论，再讲行动与结果",
        "key_points": ["先明确指标", "拆解到个人贡献"],
        "follow_up": ["这个数字怎么来的"],
        "pitfalls": ["不要只讲团队成果"],
    },
    ensure_ascii=False,
)

_ANSWER_JSON = json.dumps(
    {
        "answer": "我会先介绍我在交易系统里负责的撮合引擎，再说明如何通过内存队列把吞吐提升 40%。",
        "key_points": ["先亮结论", "拆到个人贡献", "给出可验证的数字"],
        "sample_phrasing": "以我在 X 项目里的角色为例，我负责……最终把 Y 指标提升到 Z。",
    },
    ensure_ascii=False,
)


class _FakeProvider:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    async def chat(self, _messages):
        self.calls += 1
        return self.reply


def _resume_content() -> ResumeContent:
    return ResumeContent(
        name="张三",
        summary="3 年后端开发",
        projects=[
            {
                "name": "交易系统",
                "role": "主导",
                "tech_stack": ["Go", "MySQL"],
                "description": ["负责撮合引擎"],
                "highlights": ["吞吐提升 40%"],
            }
        ],
    )


# ===== 题库三类分组（纯解析） =====


def test_parse_question_bank_groups_three_types_and_drops_noise():
    groups = parse_question_bank(json.loads(_BANK_JSON))
    assert [group.type for group in groups] == ["基础题", "项目深挖题", "反问HR题"]
    by_type = {group.type: group.questions for group in groups}
    assert len(by_type["基础题"]) == 2
    assert len(by_type["项目深挖题"]) == 1
    assert len(by_type["反问HR题"]) == 1


def test_parse_question_bank_drops_items_without_question():
    groups = parse_question_bank({"基础题": [{"purpose": "没有题目"}]})
    assert groups[0].questions == []


# ===== 题库生成 =====


async def test_generate_question_bank_returns_three_groups():
    provider = _FakeProvider(_BANK_JSON)
    result = await generate_question_bank(
        provider, job_text="后端开发 JD", resume_json="{}", claims_json=""
    )
    assert [group.type for group in result["groups"]] == ["基础题", "项目深挖题", "反问HR题"]
    assert any(group.questions for group in result["groups"])


async def test_generate_question_bank_raises_when_empty():
    provider = _FakeProvider(json.dumps({}))
    with pytest.raises(LLMError):
        await generate_question_bank(provider, job_text="", resume_json="", claims_json="")


# ===== 答题思路 =====


async def test_analyze_question_returns_framework_and_points():
    provider = _FakeProvider(_ANALYSIS_JSON)
    result = await analyze_question(provider, question="这个指标怎么算的", context="")
    assert result.question == "这个指标怎么算的"
    assert "STAR" in result.framework
    assert result.key_points
    assert result.follow_up


def test_parse_analysis_rejects_empty_result():
    with pytest.raises(LLMError):
        parse_analysis({}, "空问题")


# ===== 单题参考答案 =====


async def test_generate_question_answer_returns_answer_key_points_and_phrasing():
    provider = _FakeProvider(_ANSWER_JSON)
    result = await generate_question_answer(
        provider,
        question="讲讲你的项目难点",
        job_payload="后端开发 JD",
        resume_text="交易系统",
    )
    assert result.question == "讲讲你的项目难点"
    assert "撮合引擎" in result.answer
    assert result.key_points
    assert result.sample_phrasing


def test_parse_question_answer_rejects_empty_result():
    with pytest.raises(LLMError):
        parse_question_answer({}, "空问题")


# ===== 反向优化：只出建议、不改正文 =====


async def test_optimize_resume_returns_suggestions_without_mutating_body():
    resume = _resume_content()
    before = resume.model_dump(mode="json")
    suggestions_json = json.dumps(
        {
            "suggestions": [
                {
                    "priority": "high",
                    "section": "项目经历",
                    "issue": "难点说不清",
                    "suggestion": "补充量化结果与个人边界",
                    "evidence": ["吞吐提升 40%"],
                }
            ]
        },
        ensure_ascii=False,
    )
    provider = _FakeProvider(suggestions_json)
    suggestions = await optimize_resume(
        provider,
        resume=resume,
        job_text="后端开发 JD",
        weaknesses=["项目难点说不清"],
        follow_ups=["指标怎么算的"],
    )
    assert len(suggestions) == 1
    assert suggestions[0].priority == "high"
    assert suggestions[0].suggestion
    # 关键：输入简历正文原样未动。
    assert resume.model_dump(mode="json") == before


# ===== 接口层 =====


def _make_job_and_resume(db_session) -> tuple[Job, ResumeRecord]:
    job = Job(title="后端开发工程师", company="示例公司", description="负责高并发服务")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    resume = ResumeRecord(
        title="测试简历",
        job_id=job.id,
        job_title=job.title,
        company=job.company,
        content=_resume_content().model_dump(mode="json"),
    )
    db_session.add(resume)
    db_session.commit()
    db_session.refresh(resume)
    return job, resume


def _configure_provider(monkeypatch, reply: str) -> None:
    from app.api import interview as interview_api

    monkeypatch.setattr(
        interview_api, "_require_provider", lambda _db: (_FakeProvider(reply), "test-model")
    )


def test_question_bank_endpoint_requires_model(client):
    response = client.post("/api/interview/questions", json={"resume_id": 1})
    assert response.status_code == 400
    assert "配置大模型" in response.json()["detail"]


def test_question_bank_endpoint_requires_a_target(client):
    response = client.post("/api/interview/questions", json={})
    assert response.status_code == 422


def test_question_bank_endpoint_returns_three_groups(client, db_session, monkeypatch):
    _make_job_and_resume(db_session)
    _configure_provider(monkeypatch, _BANK_JSON)

    response = client.post("/api/interview/questions", json={"job_id": 1, "resume_id": 1})
    assert response.status_code == 200, response.text
    body = response.json()
    assert [group["type"] for group in body["groups"]] == ["基础题", "项目深挖题", "反问HR题"]
    assert body["job_title"] == "后端开发工程师"
    assert body["llm_used"] is True


def test_analyze_endpoint_returns_answer_ideas(client, monkeypatch):
    _configure_provider(monkeypatch, _ANALYSIS_JSON)
    response = client.post(
        "/api/interview/analyze", json={"question": "这个指标怎么算的", "context": "二面追问"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "STAR" in body["framework"]
    assert body["key_points"]


def test_question_answer_endpoint_requires_model(client):
    response = client.post(
        "/api/interview/questions/answer", json={"question": "讲讲项目难点"}
    )
    assert response.status_code == 400
    assert "配置大模型" in response.json()["detail"]


def test_question_answer_endpoint_requires_question(client):
    response = client.post("/api/interview/questions/answer", json={})
    assert response.status_code == 422


def test_question_answer_endpoint_returns_answer(client, monkeypatch):
    _configure_provider(monkeypatch, _ANSWER_JSON)
    response = client.post(
        "/api/interview/questions/answer", json={"question": "讲讲项目难点"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "撮合引擎" in body["answer"]
    assert body["key_points"]
    assert body["sample_phrasing"]


def test_optimize_endpoint_does_not_mutate_resume(client, db_session, monkeypatch):
    _job, resume = _make_job_and_resume(db_session)
    original = dict(resume.content)
    suggestions_json = json.dumps(
        {
            "suggestions": [
                {
                    "priority": "medium",
                    "section": "项目经历",
                    "issue": "被追问指标",
                    "suggestion": "补充指标口径",
                    "evidence": ["吞吐"],
                }
            ]
        },
        ensure_ascii=False,
    )
    _configure_provider(monkeypatch, suggestions_json)

    response = client.post(
        "/api/interview/optimize-resume",
        json={"resume_id": resume.id, "weaknesses": ["指标说不清"], "follow_ups": ["怎么算的"]},
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["suggestions"]) == 1

    # 反向优化只出建议，简历正文必须原样。
    db_session.refresh(resume)
    assert resume.content == original
