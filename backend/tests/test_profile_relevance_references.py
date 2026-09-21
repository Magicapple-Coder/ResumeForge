"""项目总结文件筛选和引用边界测试。"""

import json

from app.services.profile.profile_relevance import build_targeted_profile_context
from app.services.resume.resume_generator import coerce_resume, ground_resume_facts
from tests.profile_relevance_fixtures import (
    make_profile_with_empty_project_reference,
    make_profile_with_project_reference,
    make_rag_job,
)


def test_reference_excerpt_is_only_included_for_enhancement():
    profile = make_profile_with_project_reference()
    job = make_rag_job()

    exact = build_targeted_profile_context(profile, job, include_references=False).data
    enhanced = build_targeted_profile_context(profile, job, include_references=True).data

    assert "reference_content" not in json.dumps(exact, ensure_ascii=False)
    assert "reference_excerpt" not in json.dumps(exact, ensure_ascii=False)
    project = enhanced["projects"][0]
    assert project["reference_file_name"] == "项目总结.md"
    assert "混合召回链路" in project["reference_excerpt"]
    assert project["reference_facts"] == [
        "使用向量检索与关键词检索构建 RAG 混合召回链路，从 80 个候选文档中筛选上下文并交给模型生成答案。"
    ]
    assert "忽略系统规则" not in project["reference_excerpt"]
    assert "reference_content" not in json.dumps(enhanced, ensure_ascii=False)


def test_reference_facts_are_clean_relevant_and_bounded():
    selection = build_targeted_profile_context(
        make_profile_with_empty_project_reference(),
        make_rag_job(),
        include_references=True,
    )
    facts = selection.data["projects"][0]["reference_facts"]
    serialized_facts = "\n".join(facts)

    assert 3 <= len(facts) <= 5
    assert "FastAPI" in serialized_facts
    assert "混合召回链路" in serialized_facts
    assert "用途说明" not in serialized_facts
    assert "忽略系统规则" not in serialized_facts
    assert "99%" not in serialized_facts


def test_enhancement_can_use_education_reference_for_achievements():
    from tests.test_profile_relevance import make_diverse_profile

    profile = make_diverse_profile(
        educations=[
            {
                "id": 1,
                "school": "天津工业大学",
                "major": "软件工程",
                "degree": "本科",
                "reference_file_name": "课程设计总结.md",
                "reference_content": "在课程设计中实现 RAG 知识库检索与问答链路。",
            }
        ]
    )
    job = make_rag_job()
    selection = build_targeted_profile_context(profile, job, include_references=True)
    rewritten = "结合课程设计完成 RAG 知识库检索与问答链路。"
    raw = coerce_resume(
        {
            "education": [
                {
                    "school": "天津工业大学",
                    "major": "软件工程",
                    "achievements": [rewritten],
                }
            ]
        }
    )

    grounded = ground_resume_facts(
        raw,
        profile,
        job,
        selection.data,
        enhance=True,
    )

    assert grounded.education[0].school == "天津工业大学"
    assert grounded.education[0].achievements == [rewritten]
