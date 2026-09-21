"""简历增强质量门槛与重试策略测试。"""

import pytest

from app.schemas.resume import GenerateOptions
from app.services.llm.base import LLMError
from app.services.resume.resume_generator import ResumeGenerator
from tests.test_resume_generator import (
    QualityRetryProvider,
    collect_events,
    make_reference_job,
    make_profile_with_reference,
    rich_reference_response,
    sparse_reference_response,
)


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
