"""岗位定向资料筛选测试：不调用真实模型，也能验证候选事实是否正确。"""
import json
import re
from datetime import datetime

from app.schemas.job import JobOut
from app.schemas.profile import ProfileOut
from app.schemas.setting import LLMConfig
from app.services.llm.base import BaseLLMProvider
from app.services.profile_relevance import (
    build_job_focus,
    build_job_prompt_text,
    build_profile_prompt_data,
    build_targeted_profile_context,
    build_targeted_profile_prompt_data,
    serialize_profile_prompt_data,
)


def make_diverse_profile(**overrides) -> ProfileOut:
    data = {
        "id": 1,
        "name": "李明",
        "phone": "13800000000",
        "email": "liming@example.com",
        "city": "天津",
        "job_intent": "软件工程师",
        "educations": [
            {
                "id": 1,
                "school": "天津工业大学",
                "major": "软件工程",
                "degree": "本科",
                "courses": "数据结构\n操作系统\n软件工程",
            }
        ],
        "experiences": [
            {
                "id": 1,
                "company": "星云云服务",
                "role": "后端开发实习生",
                "start_date": "2025.03",
                "end_date": "2025.08",
                "description": "使用 Python 和 FastAPI 开发 RESTful API\n维护 MySQL、Redis 缓存与 Docker 部署",
            },
            {
                "id": 2,
                "company": "青年创新中心",
                "role": "产品运营实习生",
                "start_date": "2024.07",
                "end_date": "2024.12",
                "description": "开展用户研究并梳理反馈\n负责活动策划、内容运营和数据复盘",
            },
        ],
        "campus_experiences": [
            {
                "id": 1,
                "organization": "校学生会",
                "role": "宣传部部长",
                "start_date": "2023.09",
                "end_date": "2024.06",
                "description": "策划校园活动推广\n负责公众号内容排期与跨部门协作",
            }
        ],
        "projects": [
            {
                "id": 1,
                "name": "在线预约服务",
                "role": "后端开发",
                "start_date": "2025.01",
                "end_date": "2025.03",
                "tech_stack": "Python, FastAPI, MySQL, Redis, Docker",
                "description": "实现预约与排班 API\n设计 Redis 缓存和数据库查询",
                "highlights": "完成 Docker 化部署",
            },
            {
                "id": 2,
                "name": "校园活动增长项目",
                "role": "产品运营",
                "start_date": "2024.03",
                "end_date": "2024.06",
                "tech_stack": "Excel, Figma",
                "description": "访谈用户并整理需求\n制作活动页面原型和内容运营方案",
                "highlights": "复盘活动数据并迭代推广节奏",
            },
        ],
        "skills": [
            {"id": 1, "name": "Python", "level": "熟练"},
            {"id": 2, "name": "FastAPI", "level": "熟练"},
            {"id": 3, "name": "MySQL", "level": "掌握"},
            {"id": 4, "name": "Redis", "level": "掌握"},
            {"id": 5, "name": "Docker", "level": "掌握"},
            {"id": 6, "name": "用户研究", "level": "熟练"},
            {"id": 7, "name": "活动策划", "level": "熟练"},
            {"id": 8, "name": "内容运营", "level": "熟练"},
            {"id": 9, "name": "Excel", "level": "掌握"},
            {"id": 10, "name": "Figma", "level": "掌握"},
        ],
        "awards": [],
        **overrides,
    }
    return ProfileOut.model_validate(data)


def make_job(title: str, description: str, requirements: str = "") -> JobOut:
    now = datetime.now()
    return JobOut.model_validate(
        {
            "id": 1,
            "title": title,
            "company": "示例公司",
            "description": description,
            "requirements": requirements,
            "created_at": now,
            "updated_at": now,
        }
    )


def skill_names(data: dict) -> set[str]:
    return {item["name"] for item in data["skills"]}


class CapturingProvider(BaseLLMProvider):
    """回放固定模型 JSON，并记录生成器实际发送的 Prompt。"""

    def __init__(self, response: dict):
        super().__init__(LLMConfig(base_url="http://fake", api_key="fake", model="fake-model"))
        self.response = response
        self.messages: list[dict] = []

    async def chat(self, messages: list[dict]) -> str:
        raise AssertionError("本用例的模型输出应一次解析成功，不应进入修复流程")

    async def stream_chat(self, messages: list[dict]):
        self.messages = messages
        yield json.dumps(self.response, ensure_ascii=False)


def prompt_candidate_data(messages: list[dict]) -> dict:
    content = messages[1]["content"]
    match = re.search(r"## 候选个人资料.*?```json\n(.*?)\n```", content, re.DOTALL)
    assert match is not None
    return json.loads(match.group(1))


def test_targeted_context_selects_different_evidence_for_different_jobs():
    profile = make_diverse_profile()
    backend_job = make_job(
        "后端开发工程师",
        "负责后端服务与 RESTful API 开发，维护数据库和缓存。",
        "熟悉 Python、FastAPI、MySQL、Redis 和 Docker。",
    )
    operations_job = make_job(
        "产品运营实习生",
        "参与用户研究、活动策划、内容运营和数据复盘。",
        "熟练使用 Excel、Figma，具备跨部门协作能力。",
    )

    backend = build_targeted_profile_prompt_data(profile, backend_job)
    operations = build_targeted_profile_prompt_data(profile, operations_job)

    assert [item["company"] for item in backend["experiences"]] == ["星云云服务"]
    assert [item["name"] for item in backend["projects"]] == ["在线预约服务"]
    assert {"Python", "FastAPI", "MySQL", "Redis", "Docker"} <= skill_names(backend)
    assert "内容运营" not in skill_names(backend)

    assert [item["company"] for item in operations["experiences"]] == ["青年创新中心"]
    assert [item["name"] for item in operations["projects"]] == ["校园活动增长项目"]
    assert [item["organization"] for item in operations["campus_experiences"]] == ["校学生会"]
    assert {"用户研究", "活动策划", "内容运营", "Excel", "Figma"} <= skill_names(operations)
    assert "Redis" not in skill_names(operations)


def test_large_profile_keeps_late_relevant_item_and_serializes_valid_json():
    unrelated_projects = [
        {
            "id": index,
            "name": f"无关项目 {index}",
            "role": "参与者",
            "description": "无关说明" * 1_000,
            "highlights": "无关亮点" * 500,
        }
        for index in range(1, 7)
    ]
    relevant_project = {
        "id": 99,
        "name": "Rust 异步服务",
        "role": "后端开发",
        "description": "使用 Rust 开发异步网络服务",
        "tech_stack": "Rust, Docker",
    }
    profile = make_diverse_profile(
        projects=unrelated_projects + [relevant_project],
        skills=[{"id": 1, "name": "Rust", "level": "掌握"}],
    )
    job = make_job("Rust 后端工程师", "负责异步服务开发", "熟悉 Rust 和 Docker")

    full = build_profile_prompt_data(profile)
    context = build_targeted_profile_context(profile, job, max_chars=12_000)
    serialized = context.serialized

    assert len(json.dumps(full, ensure_ascii=False)) > 12_000
    assert len(serialized) <= 12_000
    parsed = json.loads(serialized)
    assert [item["name"] for item in parsed["projects"]] == ["Rust 异步服务"]
    assert parsed == context.data


def test_context_preserves_tail_direct_match_when_compressing_details():
    profile = make_diverse_profile(
        educations=[],
        experiences=[],
        campus_experiences=[],
        projects=[
            {
                "id": 1,
                "name": "知识库问答服务",
                "role": "开发者",
                "tech_stack": "Python, RAG",
                "description": "\n".join(
                    ["无关项目背景" * 400 for _ in range(3)] + ["实现 RAG 检索与回答链路"]
                ),
            }
        ],
        skills=[{"id": 1, "name": "RAG", "level": "掌握"}],
    )
    job = make_job("RAG 开发工程师", "负责知识库问答服务开发", "熟悉 RAG")

    context = build_targeted_profile_context(profile, job, max_chars=1_000)

    assert context.data["projects"][0]["description"] == ["实现 RAG 检索与回答链路"]
    assert json.loads(context.serialized) == context.data


def test_context_does_not_fill_unrelated_entries_when_job_has_clear_signals():
    profile = make_diverse_profile()
    job = make_job("Kubernetes 运维工程师", "负责集群运维", "熟悉 Kubernetes")

    context = build_targeted_profile_prompt_data(profile, job)

    assert context["experiences"] == []
    assert context["projects"] == []
    assert context["skills"] == []
    assert context["educations"][0]["school"] == "天津工业大学"


def test_context_uses_current_job_intent_and_filters_stale_summary():
    profile = make_diverse_profile(
        job_intent="产品运营",
        summary="长期负责内容运营与活动推广。熟悉 FastAPI 服务开发。",
    )
    job = make_job("后端开发工程师", "负责后端服务开发", "熟悉 FastAPI")

    context = build_targeted_profile_prompt_data(profile, job)

    assert context["job_intent"] == "后端开发工程师"
    assert context["summary"] == "熟悉 FastAPI 服务开发。"


def test_context_budget_and_jd_budget_keep_valid_data_and_requirements():
    profile = make_diverse_profile(name="候选人" * 5_000)
    job = make_job(
        "后端开发工程师",
        "团队介绍" * 4_000,
        "必须满足的关键条件：MUST_KEEP_FASTAPI_AND_REDIS",
    )

    serialized = serialize_profile_prompt_data(build_profile_prompt_data(profile), 1_000)
    jd = build_job_prompt_text(job, 5_000)

    assert len(serialized) <= 1_000
    assert json.loads(serialized)
    assert len(jd) <= 5_000
    assert "MUST_KEEP_FASTAPI_AND_REDIS" in jd


def test_job_focus_and_prompt_include_additional_recruitment_information():
    job = make_job("数据分析师", "负责经营分析", "本科及以上学历").model_copy(
        update={"additional_info": "加分项：熟悉 Python；面试包含业务案例分析"}
    )

    focus = build_job_focus(job)
    jd = build_job_prompt_text(job, 5_000)

    assert "Python" in focus.skills
    assert "其他招聘信息" in jd
    assert "面试包含业务案例分析" in jd
