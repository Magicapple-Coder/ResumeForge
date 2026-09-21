"""多份招聘信息拆分：本地切分规则、摘录锚定与接口兜底。

这块最容易出的问题是**静默切错**：把一份拆成两半、或把 A 公司的字段写进 B 公司的
草稿。所以测试重点在"不该拆的时候不拆"和"字段必须出自它自己那段材料"。
"""
import json

import httpx
import pytest

from app.schemas.setting import LLMConfig
from app.services.job.job_multi_parser import (
    build_multi_job_extraction_messages,
    excerpt_is_grounded,
    extract_multiple_jobs,
    local_multi_drafts,
    split_job_text_local,
)
from app.services.llm.openai_compat import OpenAICompatProvider

TWO_JOBS = """公司：字节跳动
岗位：后端开发工程师
职位描述：
1. 负责服务端接口设计与开发
2. 参与系统性能优化
任职要求：
1. 熟悉 Go 或 Java
2. 有分布式系统经验

---
公司：美团
岗位：数据分析师
职位描述：
1. 负责业务数据指标体系搭建
任职要求：
1. 熟悉 SQL 与 Python
"""


def test_local_split_by_separator_and_company_label():
    parts = split_job_text_local(TWO_JOBS)
    assert len(parts) == 2
    assert parts[0].startswith("公司：字节跳动")
    assert parts[1].startswith("公司：美团")
    # 分隔线本身是噪声，不该留在草稿里。
    assert "---" not in parts[1]


def test_local_split_keeps_single_posting_intact():
    """一份招聘信息里出现一次公司标签时不能拆开。"""
    single = """公司：某公司
岗位：前端开发工程师
职位描述：
负责公司官网与后台系统开发。
任职要求：
熟悉 React 与 TypeScript，有良好的沟通能力。
"""
    assert split_job_text_local(single) == [single]


def test_local_split_requires_enough_content_before_splitting():
    """连续两行公司标签（招聘平台常见的重复字段）不该被当成两份。"""
    text = """公司：某公司
公司：某公司（总部）
岗位：测试工程师
职位描述：
负责自动化测试用例编写与维护。
任职要求：
熟悉 Python 与 Selenium。
"""
    assert len(split_job_text_local(text)) == 1


def test_local_split_by_index_marker():
    text = """岗位1：后端开发工程师
公司：A 公司
职位描述：
负责服务端开发与维护工作。
任职要求：
熟悉 Java。

岗位2：前端开发工程师
公司：B 公司
职位描述：
负责前端页面开发与维护工作。
任职要求：
熟悉 React。
"""
    parts = split_job_text_local(text)
    assert len(parts) == 2
    assert "后端开发工程师" in parts[0]
    assert "前端开发工程师" in parts[1]


def test_excerpt_must_be_grounded_in_source():
    source = "公司：某公司\n岗位：后端开发工程师\n任职要求：熟悉 Go 语言"
    assert excerpt_is_grounded("公司：某公司\n岗位：后端开发工程师", source)
    # 空白差异不影响判定（模型常会重排换行）。
    assert excerpt_is_grounded("公司：某公司 岗位：后端开发工程师", source)
    # 编造的段落不算数。
    assert not excerpt_is_grounded("公司：另一家公司\n岗位：首席技术官", source)
    # 太短的摘录不足以作为锚点（任何材料里都能找到几个字，那不叫锚定）。
    assert not excerpt_is_grounded("岗位", source)


def _config() -> LLMConfig:
    return LLMConfig(
        base_url="https://api.example.com/v1",
        api_key="sk-test",
        model="test-model",
    )


def _provider_with(payload: dict) -> OpenAICompatProvider:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]},
        )

    return OpenAICompatProvider(_config(), transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_extract_multiple_jobs_uses_per_item_excerpt_as_anchor():
    """每份草稿的字段要在**它自己那段摘录**里找得到，不能跨段。"""
    first_excerpt = "公司：字节跳动\n岗位：后端开发工程师\n任职要求：熟悉 Go"
    second_excerpt = "公司：美团\n岗位：数据分析师\n任职要求：熟悉 SQL"
    provider = _provider_with(
        {
            "jobs": [
                {
                    "source_excerpt": first_excerpt,
                    "title": "后端开发工程师",
                    "company": "字节跳动",
                    "requirements": "熟悉 Go",
                },
                {
                    "source_excerpt": second_excerpt,
                    "title": "数据分析师",
                    "company": "美团",
                    # 这一段里没有 Go：字段不在自己的摘录中，必须被丢掉。
                    "requirements": "熟悉 Go",
                },
            ]
        }
    )

    results = await extract_multiple_jobs(provider, f"{first_excerpt}\n\n{second_excerpt}")

    assert len(results) == 2
    assert results[0].company == "字节跳动"
    assert results[0].requirements == "熟悉 Go"
    assert results[1].company == "美团"
    # 关键约束：第二份里不能出现属于第一份的内容（"Go" 只写在第一段里）。
    # 它自己的要求由本地规则从第二段补出，那部分是正确的。
    assert "Go" not in f"{results[1].requirements}{results[1].description}"
    assert "SQL" in results[1].requirements
    # 每份要带回**它自己**那段摘录，确认面板才有的可核对（此前只当锚点用完就丢）。
    assert results[0].recognized_text == first_excerpt
    assert results[1].recognized_text == second_excerpt


@pytest.mark.asyncio
async def test_extract_multiple_jobs_falls_back_when_excerpt_is_fabricated():
    """摘录对不上原文时不能整条作废，但也不能让编造的内容混进字段。"""
    provider = _provider_with(
        {
            "jobs": [
                {
                    "source_excerpt": "这段文字在原文里根本不存在，是模型自己编的段落内容",
                    "title": "后端开发工程师",
                    "company": "字节跳动",
                }
            ]
        }
    )
    results = await extract_multiple_jobs(provider, "公司：字节跳动\n岗位：后端开发工程师")
    assert len(results) == 1
    # 标题与公司在整段材料里能找到，因此仍然保留；锚点退回整段原文。
    assert results[0].company == "字节跳动"
    assert results[0].parse_engine == "ai"


@pytest.mark.asyncio
async def test_extract_multiple_jobs_rejects_empty_result():
    from app.services.llm.base import LLMError

    provider = _provider_with({"jobs": []})
    with pytest.raises(LLMError):
        await extract_multiple_jobs(provider, "这里没有任何招聘信息")


def test_multi_prompt_requires_excerpt():
    messages = build_multi_job_extraction_messages("公司：A\n岗位：B")
    system = messages[0]["content"]
    assert "source_excerpt" in system
    assert "原样复制" in system


def test_parse_multiple_endpoint_falls_back_to_local_without_model(client, monkeypatch):
    """没有可用模型时：按本地切分返回多份草稿，并说明用了本地规则。"""
    monkeypatch.setattr(
        "app.api.jobs.get_llm_config",
        lambda _db: LLMConfig(base_url="", api_key="", model=""),
    )
    response = client.post("/api/jobs/parse-multiple", json={"text": TWO_JOBS})

    assert response.status_code == 200
    body = response.json()
    assert body["parse_engine"] == "local"
    assert [item["company"] for item in body["items"]] == ["字节跳动", "美团"]
    assert any("本地规则" in warning for warning in body["items"][0]["warnings"])


def test_parse_multiple_endpoint_requires_input(client):
    response = client.post("/api/jobs/parse-multiple", json={"text": "   "})
    assert response.status_code == 422


def test_each_draft_carries_the_excerpt_the_confirm_panel_shows():
    """每份草稿要带上自己的原文摘录——确认面板逐份显示"原文：…"，用户才能核对拆分。

    此前这段摘录只被当作字段锚点用完就丢，前端读的 `recognized_text` 一直是空串：
    拆分结果看起来每份都没有原文可核对。
    """
    # 用本地切分认得的那种序号小标题（「岗位N：」）写样例，保证这段材料确实会拆成两份。
    source = (
        "岗位1：后端开发工程师\n公司：甲公司\n职责：负责服务端接口开发与维护，熟悉 Python。\n"
        "岗位2：前端开发工程师\n公司：乙公司\n职责：负责页面开发与性能优化，熟悉 TypeScript。"
    )
    drafts = local_multi_drafts(source)

    assert len(drafts) == 2
    for draft in drafts:
        assert draft.recognized_text.strip()
        # 带回来的必须是这段材料的原文，而不是别处的内容。
        assert draft.recognized_text.strip() in source
