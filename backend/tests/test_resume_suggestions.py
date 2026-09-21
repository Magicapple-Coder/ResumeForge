import json
import re

from app.services.resume.resume_record import save_record
from app.models.job import Job
from app.models.resume import ResumeRecord
from app.schemas.job import JobOut
from app.schemas.profile import ProfileOut
from app.schemas.resume import ResumeContent
from app.schemas.setting import LLMConfig
from app.services.llm.base import BaseLLMProvider
from app.services.llm.base import LLMError
from app.services.resume.resume_suggestions import (
    MAX_PROFILE_CHARS,
    MAX_RESUME_CHARS,
    _protect_existing_project_facts,
    generate_suggestions,
    parse_suggestions,
)


class SuggestionProvider(BaseLLMProvider):
    def __init__(self):
        super().__init__(LLMConfig(base_url="http://fake", api_key="fake", model="fake-model"))
        self.messages: list[list[dict]] = []

    async def chat(self, messages: list[dict]) -> str:
        self.messages.append(messages)
        return json.dumps(
            {
                "suggestions": [
                    {
                        "priority": "high",
                        "section": "项目经历",
                        "issue": "项目描述没有突出 FastAPI 与岗位要求的对应关系",
                        "suggestion": "在已有项目事实中补充 FastAPI 的具体职责和使用场景",
                        "evidence": ["FastAPI", "后端开发"],
                    }
                ]
            },
            ensure_ascii=False,
        )

    async def stream_chat(self, messages: list[dict]):
        yield ""


def _create_job_and_resume(db_session):
    job = Job(
        title="后端开发工程师",
        company="示例公司",
        description="负责 FastAPI 服务开发",
        requirements="熟悉 Python 和 FastAPI",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    record = ResumeRecord(
        title="张三-后端开发工程师",
        job_id=job.id,
        job_title=job.title,
        company=job.company,
        model="fake-model",
        content={"name": "张三", "projects": [{"name": "简历项目", "description": ["Python"]}]},
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    return job, record


def test_parse_suggestions_accepts_markdown_and_discards_invalid_items():
    raw = """```json
    {"suggestions": [
      {"priority": "urgent", "section": "技能", "issue": "缺少关键词", "suggestion": "补充已有技能", "evidence": "Python"},
      {"section": "项目经历", "issue": "只有问题没有建议"}
    ]}
    ```"""

    parsed = parse_suggestions(raw)

    assert len(parsed) == 1
    assert parsed[0].priority == "medium"
    assert parsed[0].evidence == ["Python"]


def test_parse_suggestions_rejects_non_json():
    try:
        parse_suggestions("模型暂时无法回答")
    except LLMError as exc:
        assert "有效的修改建议" in str(exc)
    else:  # pragma: no cover - 断言异常路径
        raise AssertionError("应拒绝非 JSON 建议")


def test_existing_project_is_not_reported_as_missing():
    profile = ProfileOut.model_validate(
        {
            "id": 1,
            "projects": [{"id": 1, "name": "简历通项目"}],
        }
    )
    suggestions = parse_suggestions(
        '{"suggestions":[{"section":"其他","issue":"没有项目经历","suggestion":"增加项目经验"}]}'
    )

    corrected = _protect_existing_project_facts(suggestions, profile)

    assert corrected[0].section == "项目经历"
    assert "已有项目经历" in corrected[0].issue
    assert "简历通项目" in corrected[0].evidence


def test_resume_list_exposes_job_id_and_filters_by_job(client, db_session):
    job, record = _create_job_and_resume(db_session)

    response = client.get("/api/resumes", params={"job_id": job.id})

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["job_id"] == job.id
    assert response.json()["items"][0]["id"] == record.id


def test_generated_resume_title_contains_company(db_session):
    job, _ = _create_job_and_resume(db_session)

    record = save_record(
        db_session,
        {"name": "张三"},
        [],
        JobOut.model_validate(job),
        "",
        "fake-model",
        False,
        "balanced",
    )

    assert job.company in record.title


def test_resume_suggestions_use_saved_resume_and_job(monkeypatch, client, db_session):
    job, record = _create_job_and_resume(db_session)
    provider = SuggestionProvider()
    monkeypatch.setattr("app.api.resumes.get_llm_config", lambda _db: provider.config)
    monkeypatch.setattr("app.api.resumes.create_provider", lambda _config: provider)

    response = client.post(f"/api/resumes/{record.id}/suggestions")

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == job.id
    assert body["suggestions"][0]["priority"] == "high"
    assert "FastAPI" in provider.messages[0][1]["content"]
    assert "示例公司" in provider.messages[0][1]["content"]
    assert "简历项目" in provider.messages[0][1]["content"]


def test_resume_suggestions_reject_unrelated_record(client, db_session):
    record = ResumeRecord(
        title="未关联简历",
        job_title="后端开发工程师",
        company="示例公司",
        content={"name": "张三"},
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)

    response = client.post(f"/api/resumes/{record.id}/suggestions")

    assert response.status_code == 400
    assert "没有关联" in response.json()["detail"]


async def test_suggestion_prompt_excludes_private_fields_and_keeps_valid_bounded_json():
    photo = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl2kAAAAASUVORK5CYII="
    )
    resume = ResumeContent.model_validate(
        {
            "name": "PRIVATE_NAME_TOKEN",
            "photo": photo,
            "gender": "PRIVATE_GENDER_TOKEN",
            "birth_year": "PRIVATE_BIRTH_TOKEN",
            "phone": "PRIVATE_PHONE_TOKEN",
            "email": "private-email-token@example.com",
            "city": "PRIVATE_CITY_TOKEN",
            "summary": "很长的个人总结" * 6_000,
            "projects": [
                {
                    "name": "RESUME_PROJECT_MARKER",
                    "description": ["项目事实" * 2_000 for _ in range(8)],
                }
            ],
        }
    )
    profile = ProfileOut.model_validate(
        {
            "id": 1,
            "name": "PROFILE_PRIVATE_NAME_TOKEN",
            "phone": "PROFILE_PRIVATE_PHONE_TOKEN",
            "email": "profile-private@example.com",
            "github": "https://example.com/private-github",
            "personal_website": "https://example.com/private-site",
            "projects": [
                {
                    "id": 1,
                    "name": "PROFILE_PROJECT_MARKER",
                    "description": "资料事实" * 20_000,
                }
            ],
        }
    )
    provider = SuggestionProvider()
    await generate_suggestions(provider, resume, _create_job_out(), profile)

    prompt = provider.messages[0][1]["content"]
    for private_value in (
        photo,
        resume.name,
        resume.gender,
        resume.birth_year,
        resume.phone,
        resume.email,
        resume.city,
        profile.name,
        profile.phone,
        profile.email,
        profile.github,
        profile.personal_website,
    ):
        assert private_value not in prompt

    json_blocks = re.findall(r"```json\s*(.*?)\s*```", prompt, re.DOTALL)
    assert len(json_blocks) == 2
    resume_data, profile_data = (json.loads(block) for block in json_blocks)
    assert len(json_blocks[0]) <= MAX_RESUME_CHARS
    assert len(json_blocks[1]) <= MAX_PROFILE_CHARS
    assert resume_data["projects"][0]["name"] == "RESUME_PROJECT_MARKER"
    assert profile_data["projects"][0]["name"] == "PROFILE_PROJECT_MARKER"


def _create_job_out() -> JobOut:
    from datetime import datetime

    now = datetime.now()
    return JobOut.model_validate(
        {
            "id": 1,
            "title": "后端开发工程师",
            "company": "示例公司",
            "created_at": now,
            "updated_at": now,
        }
    )
