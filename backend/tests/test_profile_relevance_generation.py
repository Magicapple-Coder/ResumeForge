"""岗位相关资料筛选后的简历生成与事实回填测试。"""

import json

from app.schemas.resume import GenerateOptions
from app.services.profile.profile_relevance import build_targeted_profile_context
from app.services.resume.resume_generator import (
    ResumeGenerator,
    check_consistency,
    coerce_resume,
    ground_resume_facts,
)
from tests.test_profile_relevance import (
    CapturingProvider,
    make_diverse_profile,
    make_job,
    prompt_candidate_data,
)


async def test_generator_uses_targeted_context_and_grounds_factual_fields():
    profile = make_diverse_profile()
    job = make_job(
        "后端开发工程师",
        "负责后端服务与 RESTful API 开发，维护数据库和缓存。",
        "熟悉 Python、FastAPI、MySQL、Redis 和 Docker。",
    )
    provider = CapturingProvider(
        {
            "name": "错误姓名",
            "phone": "00000000000",
            "email": "wrong@example.com",
            "city": "北京",
            "job_intent": "旧求职意向",
            "summary": "具备后端开发能力。",
            "experience": [
                {
                    "company": "星云云服务",
                    "role": "架构师",
                    "start_date": "2020.01",
                    "end_date": "2020.12",
                    "description": ["使用 Python 和 FastAPI 开发 RESTful API"],
                }
            ],
            "projects": [
                {
                    "name": "在线预约服务",
                    "role": "产品负责人",
                    "start_date": "2020.01",
                    "end_date": "2020.12",
                    "tech_stack": ["Python", "React"],
                    "description": ["实现预约与排班 API"],
                }
            ],
            "skills": [
                {"name": "Python", "level": "专家"},
                {"name": "Kubernetes", "level": "熟练"},
            ],
        }
    )

    events = [
        event
        async for event in ResumeGenerator(provider).generate(profile, job, GenerateOptions())
    ]
    done = next(event for event in events if event["type"] == "done")
    sent_data = prompt_candidate_data(provider.messages)

    assert [item["company"] for item in sent_data["experiences"]] == ["星云云服务"]
    assert [item["name"] for item in sent_data["projects"]] == ["在线预约服务"]
    assert "青年创新中心" not in json.dumps(sent_data, ensure_ascii=False)
    assert "校园活动增长项目" not in json.dumps(sent_data, ensure_ascii=False)

    resume = done["resume"]
    assert resume["name"] == profile.name
    assert resume["phone"] == profile.phone
    assert resume["email"] == profile.email
    assert resume["city"] == profile.city
    assert resume["job_intent"] == job.title
    assert resume["experience"][0]["role"] == "后端开发实习生"
    assert resume["experience"][0]["start_date"] == "2025.03"
    assert resume["projects"][0]["role"] == "后端开发"
    assert resume["projects"][0]["tech_stack"] == ["Python"]
    assert resume["skills"][0] == {"name": "Python", "level": "熟练"}
    assert "Kubernetes" not in [item["name"] for item in resume["skills"]]
    assert any("Kubernetes" in warning for warning in done["warnings"])


async def test_generator_restores_selected_facts_when_model_omits_sections():
    profile = make_diverse_profile()
    job = make_job(
        "后端开发工程师",
        "负责后端服务与 RESTful API 开发，维护数据库和缓存。",
        "熟悉 Python、FastAPI、MySQL、Redis 和 Docker。",
    )
    provider = CapturingProvider({"summary": "具备后端开发能力。"})

    events = [
        event
        async for event in ResumeGenerator(provider).generate(profile, job, GenerateOptions())
    ]
    done = next(event for event in events if event["type"] == "done")
    resume = done["resume"]

    assert [item["school"] for item in resume["education"]] == ["天津工业大学"]
    assert [item["company"] for item in resume["experience"]] == ["星云云服务"]
    assert [item["name"] for item in resume["projects"]] == ["在线预约服务"]
    assert {item["name"] for item in resume["skills"]} >= {
        "Python",
        "FastAPI",
        "MySQL",
        "Redis",
        "Docker",
    }


async def test_generator_reverts_unsupported_quantitative_claim_to_source_facts():
    profile = make_diverse_profile()
    job = make_job(
        "后端开发工程师",
        "负责后端服务与 RESTful API 开发，维护数据库和缓存。",
        "熟悉 Python、FastAPI、MySQL、Redis 和 Docker。",
    )
    provider = CapturingProvider(
        {
            "experience": [
                {
                    "company": "星云云服务",
                    "role": "后端开发实习生",
                    "start_date": "2025.03",
                    "end_date": "2025.08",
                    "description": ["通过缓存优化使接口性能提升 300%"],
                }
            ]
        }
    )

    events = [
        event
        async for event in ResumeGenerator(provider).generate(profile, job, GenerateOptions())
    ]
    done = next(event for event in events if event["type"] == "done")

    assert any("300%" in warning for warning in done["warnings"])
    assert done["resume"]["experience"][0]["description"] == [
        "使用 Python 和 FastAPI 开发 RESTful API",
        "维护 MySQL、Redis 缓存与 Docker 部署",
    ]


def test_grounding_rejects_unquantified_claims_and_mixed_skill_lists():
    profile = make_diverse_profile()
    job = make_job(
        "后端开发工程师",
        "负责后端服务与 RESTful API 开发，维护数据库和缓存。",
        "熟悉 Python、FastAPI、MySQL、Redis 和 Docker。",
    )
    selection = build_targeted_profile_context(profile, job)
    raw = coerce_resume(
        {
            "projects": [
                {
                    "name": "在线预约服务",
                    "role": "后端开发",
                    "tech_stack": ["Python, Kubernetes"],
                    "description": ["搭建高可用架构"],
                    "highlights": ["支撑海量请求"],
                }
            ]
        }
    )

    grounded = ground_resume_facts(raw, profile, job, selection.data)
    project = grounded.projects[0]
    source_project = selection.data["projects"][0]

    assert project.tech_stack == source_project["tech_stack"]
    assert project.description == source_project["description"]
    assert project.highlights == source_project["highlights"]


def test_grounding_ignores_blank_source_rows_and_filters_unselected_facts():
    profile = make_diverse_profile(
        educations=[
            {"id": 1, "school": ""},
            {
                "id": 2,
                "school": "天津工业大学",
                "major": "软件工程",
                "degree": "本科",
                "start_date": "2023.09",
                "end_date": "2027.06",
            },
        ]
    )
    job = make_job(
        "后端开发工程师",
        "负责后端服务和 API 开发。",
        "熟悉 Python、FastAPI、MySQL、Redis 和 Docker。",
    )
    selection = build_targeted_profile_context(profile, job)
    raw = coerce_resume(
        {
            "education": [{"school": "天津工业大学", "major": "错误专业"}],
            "projects": [{"name": "校园活动增长项目", "role": "产品运营"}],
            "awards": [{"name": "虚构奖项", "date": "2026.01"}],
        }
    )

    warnings = check_consistency(raw, profile, selection.data)
    grounded = ground_resume_facts(raw, profile, job, selection.data)

    assert grounded.education[0].school == "天津工业大学"
    assert grounded.education[0].major == "软件工程"
    assert grounded.projects == []
    assert grounded.awards == []
    assert any("校园活动增长项目" in warning for warning in warnings)
    assert any("虚构奖项" in warning for warning in warnings)
