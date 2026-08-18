"""简历生成核心流程测试（使用假 Provider，不发起真实网络请求）。"""
import json

import pytest
from pydantic import ValidationError

from app.schemas.job import JobOut
from app.schemas.profile import ProfileOut
from app.schemas.resume import GenerateOptions
from app.schemas.setting import LLMConfig
from app.services.llm.base import BaseLLMProvider, LLMError
from app.services.llm.openai_compat import OpenAICompatProvider
from app.services.resume_generator import (
    ResumeGenerator,
    build_profile_prompt_data,
    check_consistency,
    coerce_resume,
    extract_json,
    split_commas,
    split_lines,
)

PHOTO_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl2kAAAAASUVORK5CYII="
)

# 一份符合要求的模型输出示例
GOOD_RESUME = {
    "name": "张三",
    "gender": "男",
    "birth_year": "2004",
    "phone": "13800000000",
    "email": "zhangsan@example.com",
    "city": "天津",
    "job_intent": "后端开发工程师",
    "summary": "计算机专业应届生，具备扎实的工程能力。",
    "education": [
        {
            "school": "天津工业大学",
            "major": "软件工程",
            "degree": "本科",
            "start_date": "2022.09",
            "end_date": "2026.06",
            "gpa": "3.8/4.0",
            "courses": ["数据结构", "操作系统"],
            "achievements": ["获校级奖学金"],
        }
    ],
    "experience": [
        {
            "company": "某科技公司",
            "role": "后端实习生",
            "start_date": "2025.06",
            "end_date": "2025.09",
            "description": ["负责 XX 服务开发，性能提升 30%"],
        }
    ],
    "projects": [
        {
            "name": "简历通",
            "role": "核心开发",
            "start_date": "2025.09",
            "end_date": "2026.08",
            "tech_stack": ["Python", "FastAPI", "React"],
            "description": ["AI 定制化简历生成平台"],
            "highlights": ["开源项目，已开源"],
        }
    ],
    "skills": [{"name": "Python", "level": "熟练"}],
    "awards": [],
}


class FakeProvider(BaseLLMProvider):
    """按脚本回放的假模型：stream 文本可选分块，chat 依次返回队列内容。"""

    def __init__(self, stream_text: str = "", chat_replies: list[str] | None = None, chunk_size: int = 40):
        super().__init__(LLMConfig(base_url="http://fake", api_key="k", model="fake-model"))
        self.stream_text = stream_text
        self.chat_replies = chat_replies or []
        self.chunk_size = chunk_size
        self.messages: list[dict] = []

    async def chat(self, messages):
        if not self.chat_replies:
            raise AssertionError("FakeProvider 没有可用的 chat 回复")
        return self.chat_replies.pop(0)

    async def stream_chat(self, messages):
        self.messages = messages
        for i in range(0, len(self.stream_text), self.chunk_size):
            yield self.stream_text[i : i + self.chunk_size]


class QualityRetryProvider(FakeProvider):
    """记录质量重试对话，便于确认重试不会向前端追加第二份流式 JSON。"""

    def __init__(self, first_response: dict, retry_response: dict | str | Exception):
        first_text = json.dumps(first_response, ensure_ascii=False)
        super().__init__(stream_text=first_text, chunk_size=len(first_text))
        self.retry_response = retry_response
        self.chat_messages: list[list[dict]] = []

    async def chat(self, messages):
        self.chat_messages.append(messages)
        if isinstance(self.retry_response, Exception):
            raise self.retry_response
        if isinstance(self.retry_response, str):
            return self.retry_response
        return json.dumps(self.retry_response, ensure_ascii=False)


def make_profile(**overrides) -> ProfileOut:
    data = {
        "id": 1,
        "name": "张三",
        "email": "zhangsan@example.com",
        "educations": [{"id": 1, "school": "天津工业大学", "major": "软件工程", "degree": "本科"}],
        "experiences": [
            {
                "id": 1,
                "company": "某科技公司",
                "role": "后端实习生",
                "start_date": "2025.06",
                "end_date": "2025.09",
                "description": "负责 XX 服务开发，性能提升 30%",
            }
        ],
        "projects": [
            {
                "id": 1,
                "name": "简历通",
                "role": "核心开发",
                "start_date": "2025.09",
                "end_date": "2026.08",
                "tech_stack": "Python, FastAPI, React",
                "description": "AI 定制化简历生成平台",
                "highlights": "开源项目，已开源",
            }
        ],
        "skills": [{"id": 1, "name": "Python", "level": "熟练"}],
        "awards": [{"id": 1, "name": "校级奖学金", "date": "2024.10"}],
        **overrides,
    }
    return ProfileOut.model_validate(data)


def make_job() -> JobOut:
    from datetime import datetime

    now = datetime.now()
    return JobOut.model_validate(
        {
            "id": 1,
            "title": "后端开发工程师",
            "company": "示例公司",
            "location": "北京",
            "description": "负责后端服务开发与 API 设计",
            "requirements": "熟悉 Python、FastAPI 和 React。",
            "created_at": now,
            "updated_at": now,
        }
    )


def make_profile_with_reference(*, empty_details: bool = False) -> ProfileOut:
    """构造带岗位相关总结文件的资料，覆盖质量门槛的真实输入形态。"""
    return make_profile(
        experiences=[],
        projects=[
            {
                "id": 1,
                "name": "知识库问答服务",
                "role": "后端开发",
                "start_date": "2025.01",
                "end_date": "2025.04",
                "tech_stack": "Python, FastAPI, RAG",
                "description": "" if empty_details else "实现知识库问答接口",
                "highlights": "" if empty_details else "完成基础检索链路",
                "reference_file_name": "项目总结.md",
                "reference_content": (
                    "# 项目总结\n\n"
                    "- 使用 Python 与 FastAPI 开发知识库问答 API\n"
                    "- 结合 RAG 与向量检索构建混合召回链路\n"
                    "- 使用 Python 异步任务保存生成进度并支持失败重试\n"
                    "- 在 RAG 检索链路中校验文档 ID，过滤无效结果\n"
                    "- 按 RAG 相关度筛选上下文，控制 Prompt 长度\n"
                ),
            }
        ],
        skills=[
            {"id": 1, "name": "Python", "level": "熟练"},
            {"id": 2, "name": "FastAPI", "level": "熟练"},
            {"id": 3, "name": "RAG", "level": "掌握"},
        ],
    )


def make_reference_job() -> JobOut:
    return make_job().model_copy(
        update={
            "title": "RAG 应用开发工程师",
            "description": "负责知识库问答、异步任务与检索增强生成链路开发。",
            "requirements": "熟悉 Python、FastAPI、RAG、向量检索与 Prompt 工程。",
        }
    )


def sparse_reference_response() -> dict:
    return {
        "summary": "后端开发工程师，具备相关项目经历。",
        "projects": [
            {
                "name": "知识库问答服务",
                "role": "后端开发",
                "description": ["使用 Python 与 FastAPI 开发知识库问答 API"],
                "highlights": [],
            }
        ],
    }


def rich_reference_response() -> dict:
    return {
        "summary": "具备 Python 后端与 RAG 检索实践，能够围绕岗位需求设计并交付可靠的知识库问答服务。",
        "projects": [
            {
                "name": "知识库问答服务",
                "role": "后端开发",
                "description": [
                    "使用 Python 与 FastAPI 开发知识库问答 API，拆分检索与生成职责。",
                    "结合 RAG 与向量检索构建混合召回链路，围绕岗位场景组织上下文。",
                ],
                "highlights": [
                    "通过异步任务保存生成进度并支持失败重试，提升服务处理长任务的稳定性。",
                ],
            }
        ],
    }


async def collect_events(generator):
    return [event async for event in generator]


def test_llm_default_temperature_and_request_payload_are_stable():
    default_config = LLMConfig()
    assert default_config.temperature == 0.1

    config = LLMConfig(model="test-model", temperature=0.3)
    payload = OpenAICompatProvider(config)._build_payload(
        [{"role": "user", "content": "测试"}],
        stream=False,
    )
    assert payload["temperature"] == 0.3


async def test_generate_success_stream_and_parse():
    provider = FakeProvider(stream_text=json.dumps(GOOD_RESUME, ensure_ascii=False), chunk_size=25)
    generator = ResumeGenerator(provider)
    events = await collect_events(generator.generate(make_profile(), make_job(), GenerateOptions()))
    types = [event["type"] for event in events]
    assert "progress" in types and "delta" in types and "done" in types
    done = next(event for event in events if event["type"] == "done")
    assert done["resume"]["name"] == "张三"
    assert done["resume"]["education"][0]["school"] == "天津工业大学"
    assert done["warnings"] == []


async def test_generate_injects_profile_photo_without_sending_it_to_llm():
    profile = make_profile(
        photo=PHOTO_DATA_URL,
        name="PRIVATE_NAME_TOKEN",
        gender="PRIVATE_GENDER_TOKEN",
        birth_year="PRIVATE_BIRTH_TOKEN",
        phone="PRIVATE_PHONE_TOKEN",
        email="private-email-token@example.com",
        city="PRIVATE_CITY_TOKEN",
        github="https://example.com/private-github-token",
        personal_website="https://example.com/private-site-token",
    )
    prompt_data = build_profile_prompt_data(profile)
    provider = FakeProvider(stream_text=json.dumps(GOOD_RESUME, ensure_ascii=False))

    events = await collect_events(ResumeGenerator(provider).generate(profile, make_job(), GenerateOptions()))
    done = next(event for event in events if event["type"] == "done")

    assert "photo" not in prompt_data
    assert PHOTO_DATA_URL not in json.dumps(prompt_data, ensure_ascii=False)
    sent_prompt = json.dumps(provider.messages, ensure_ascii=False)
    for private_value in (
        profile.name,
        profile.gender,
        profile.birth_year,
        profile.phone,
        profile.email,
        profile.city,
        profile.github,
        profile.personal_website,
    ):
        assert private_value not in sent_prompt
    assert done["resume"]["name"] == profile.name
    assert done["resume"]["phone"] == profile.phone
    assert done["resume"]["email"] == profile.email
    assert done["resume"]["photo"] == PHOTO_DATA_URL


async def test_generate_repairs_broken_json_once():
    # 首次流式输出不是 JSON，修复对话返回合法 JSON
    provider = FakeProvider(
        stream_text="抱歉，我无法生成：xxx",
        chat_replies=[json.dumps(GOOD_RESUME, ensure_ascii=False)],
    )
    events = await collect_events(ResumeGenerator(provider).generate(make_profile(), make_job(), GenerateOptions()))
    done = next(event for event in events if event["type"] == "done")
    assert done["resume"]["name"] == "张三"


async def test_generate_fails_gracefully():
    provider = FakeProvider(stream_text="彻底乱码", chat_replies=["仍然乱码"])
    events = await collect_events(ResumeGenerator(provider).generate(make_profile(), make_job(), GenerateOptions()))
    assert events[-1]["type"] == "error"
    assert "JSON" in events[-1]["message"]


@pytest.mark.parametrize(
    ("level", "instruction"),
    [
        ("light", "保持原有要点数量与职责边界"),
        ("balanced", "补足动作、方法和业务目的"),
        ("strong", "可以增加描述要点"),
    ],
)
async def test_generate_uses_explicit_enhancement_level_guide(level, instruction):
    provider = FakeProvider(stream_text=json.dumps(GOOD_RESUME, ensure_ascii=False))

    events = await collect_events(
        ResumeGenerator(provider).generate(
            make_profile(),
            make_job(),
            GenerateOptions(enhance=True, enhancement_level=level),
        )
    )

    assert events[-1]["type"] == "done"
    assert instruction in provider.messages[1]["content"]


async def test_strong_enhancement_retries_sparse_reference_project_once():
    provider = QualityRetryProvider(sparse_reference_response(), rich_reference_response())

    events = await collect_events(
        ResumeGenerator(provider).generate(
            make_profile_with_reference(),
            make_reference_job(),
            GenerateOptions(enhance=True, enhancement_level="strong"),
        )
    )
    done = next(event for event in events if event["type"] == "done")
    project = done["resume"]["projects"][0]

    assert len(provider.chat_messages) == 1
    assert len(provider.chat_messages[0]) == 3
    assert "reference_facts" in provider.chat_messages[0][-1]["content"]
    assert sum(event["type"] == "delta" for event in events) == 1
    assert sum(
        event["type"] == "progress" and "内容较简略" in event["message"]
        for event in events
    ) == 1
    assert done["resume"]["summary"] == rich_reference_response()["summary"]
    assert len(project["description"] + project["highlights"]) == 3


async def test_strong_enhancement_retries_when_output_only_copies_reference_facts():
    first = sparse_reference_response()
    first["projects"][0]["description"] = [
        "使用 Python 与 FastAPI 开发知识库问答 API",
        "结合 RAG 与向量检索构建混合召回链路",
        "使用 Python 异步任务保存生成进度并支持失败重试",
        "在 RAG 检索链路中校验文档 ID，过滤无效结果",
        "按 RAG 相关度筛选上下文，控制 Prompt 长度",
    ]
    provider = QualityRetryProvider(first, rich_reference_response())

    events = await collect_events(
        ResumeGenerator(provider).generate(
            make_profile_with_reference(empty_details=True),
            make_reference_job(),
            GenerateOptions(enhance=True, enhancement_level="strong"),
        )
    )

    assert events[-1]["type"] == "done"
    assert len(provider.chat_messages) == 1
    assert events[-1]["resume"]["projects"][0]["highlights"]


@pytest.mark.parametrize("retry_response", [LLMError("临时不可用"), "仍然不是 JSON"])
async def test_quality_retry_failure_keeps_first_result_and_finishes(retry_response):
    provider = QualityRetryProvider(
        sparse_reference_response(),
        retry_response,
    )

    events = await collect_events(
        ResumeGenerator(provider).generate(
            make_profile_with_reference(),
            make_reference_job(),
            GenerateOptions(enhance=True, enhancement_level="strong"),
        )
    )

    assert len(provider.chat_messages) == 1
    assert events[-1]["type"] == "done"
    assert events[-1]["resume"]["summary"] == sparse_reference_response()["summary"]


async def test_quality_retry_does_not_replace_first_result_with_another_sparse_result():
    first = sparse_reference_response()
    retry = sparse_reference_response()
    retry["summary"] = "这份仍然稀疏的结果不应被采用。"
    provider = QualityRetryProvider(first, retry)

    events = await collect_events(
        ResumeGenerator(provider).generate(
            make_profile_with_reference(),
            make_reference_job(),
            GenerateOptions(enhance=True, enhancement_level="strong"),
        )
    )

    assert len(provider.chat_messages) == 1
    assert events[-1]["type"] == "done"
    assert events[-1]["resume"]["summary"] == first["summary"]


async def test_rich_reference_project_does_not_trigger_quality_retry():
    provider = QualityRetryProvider(
        rich_reference_response(),
        AssertionError("质量合格时不应重试"),
    )

    events = await collect_events(
        ResumeGenerator(provider).generate(
            make_profile_with_reference(),
            make_reference_job(),
            GenerateOptions(enhance=True, enhancement_level="strong"),
        )
    )

    assert events[-1]["type"] == "done"
    assert provider.chat_messages == []


@pytest.mark.parametrize(
    "options",
    [
        GenerateOptions(enhance=False),
        GenerateOptions(enhance=True, enhancement_level="balanced"),
    ],
)
async def test_quality_retry_only_runs_for_strong_enhancement(options):
    provider = QualityRetryProvider(
        sparse_reference_response(),
        AssertionError("非 strong 模式不应重试"),
    )

    events = await collect_events(
        ResumeGenerator(provider).generate(
            make_profile_with_reference(),
            make_reference_job(),
            options,
        )
    )

    assert events[-1]["type"] == "done"
    assert provider.chat_messages == []


async def test_generate_disables_expansion_by_default():
    provider = FakeProvider(stream_text=json.dumps(GOOD_RESUME, ensure_ascii=False))

    await collect_events(
        ResumeGenerator(provider).generate(make_profile(), make_job(), GenerateOptions())
    )

    assert "美化拓展已关闭" in provider.messages[1]["content"]


def test_generate_options_rejects_removed_tone_option():
    with pytest.raises(ValidationError):
        GenerateOptions.model_validate({"tone": "tech"})


def test_extract_json_tolerates_wrappers():
    assert extract_json("```json\n{\"a\": 1}\n```") == {"a": 1}
    assert extract_json("前置说明 {\"a\": 1} 后置说明") == {"a": 1}
    assert extract_json("{\"resume\": {\"a\": 1}}") == {"a": 1}
    assert extract_json("") is None
    assert extract_json("没有任何花括号") is None


def test_coerce_resume_fills_defaults():
    resume = coerce_resume({"name": "李四", "education": [{"school": "某大学", "courses": "数学\n英语"}]})
    assert resume.name == "李四"
    assert resume.summary == ""
    assert resume.education[0].courses == ["数学", "英语"]
    assert resume.projects == []
    assert coerce_resume({"photo": PHOTO_DATA_URL}).photo == ""  # 不信任模型回传的照片


def test_campus_experience_is_in_prompt_and_model_output():
    profile = make_profile(
        campus_experiences=[
            {
                "id": 1,
                "organization": "学生会",
                "role": "宣传部部长",
                "start_date": "2023.09",
                "end_date": "2024.06",
                "description": "策划校园活动\n管理宣传渠道",
            }
        ]
    )

    prompt_data = build_profile_prompt_data(profile)
    assert prompt_data["campus_experiences"] == [
        {
            "organization": "学生会",
            "role": "宣传部部长",
            "start_date": "2023.09",
            "end_date": "2024.06",
            "description": ["策划校园活动", "管理宣传渠道"],
        }
    ]

    resume = coerce_resume(
        {
            "campus_experience": {
                "organization": "学生会（校级）",
                "role": "宣传部部长",
                "description": "策划校园活动\n管理宣传渠道",
            }
        }
    )
    assert resume.campus_experience[0].description == ["策划校园活动", "管理宣传渠道"]
    assert check_consistency(resume, profile) == []


def test_check_consistency_detects_unknown_campus_organization():
    profile = make_profile(
        campus_experiences=[{"id": 1, "organization": "学生会"}]
    )
    resume = coerce_resume({"campus_experience": [{"organization": "青年志愿者协会"}]})

    warnings = check_consistency(resume, profile)
    assert len(warnings) == 1
    assert "青年志愿者协会" in warnings[0]


def test_coerce_resume_handles_garbage():
    resume = coerce_resume(None)
    assert resume.name == "" and resume.skills == []
    resume = coerce_resume({"education": "不是列表", "projects": [123]})
    assert resume.education == [] and resume.projects == []


def test_check_consistency_detects_hallucination():
    resume = coerce_resume(
        {
            "education": [{"school": "北京大学"}],  # 资料里没有
            "experience": [{"company": "某科技公司"}],  # 资料里有
            "projects": [{"name": "简历通（开源项目）"}],  # 轻度改写，应视为一致
        }
    )
    warnings = check_consistency(resume, make_profile())
    assert len(warnings) == 1
    assert "北京大学" in warnings[0]


def test_split_helpers():
    assert split_lines("第一行\n第二行\n\n第三行\n") == ["第一行", "第二行", "第三行"]
    assert split_commas("Python, FastAPI、React") == ["Python", "FastAPI", "React"]
