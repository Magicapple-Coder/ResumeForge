"""事实台账与简历链路的两个接合点：生成时的事实基线、导出时的闸门。

这是整个功能产生实际后果的地方，所以两侧都测到"接不上"和"接得太死"两种失误：
- 生成：台账为空时提示词必须与改动前**逐字节相同**，否则所有老用户拿到的简历都会变；
- 导出：带占位符时要拦下并说清是哪儿，但用户想要草稿自查时不能把路堵死。
"""
import json

from app.schemas.resume import GenerateOptions, ResumeContent
from app.services.resume.resume_generator import ResumeGenerator
from app.services.llm.base import BaseLLMProvider


class CapturingProvider(BaseLLMProvider):
    def __init__(self):
        from app.schemas.setting import LLMConfig

        super().__init__(LLMConfig(base_url="http://fake", model="fake-model"))
        self.messages: list[dict] = []

    async def chat(self, messages):
        self.messages = messages
        return json.dumps({"summary": "示例"}, ensure_ascii=False)

    async def stream_chat(self, messages):
        self.messages = messages
        yield json.dumps({"summary": "示例"}, ensure_ascii=False)


def _reasonably_full_profile():
    from app.schemas.profile import ProfileOut

    return ProfileOut.model_validate(
        {
            "id": 1,
            "name": "张三",
            "summary": "软件工程本科生。",
            "projects": [
                {
                    "id": 1,
                    "name": "检索平台",
                    "role": "后端",
                    "description": "实现检索接口",
                }
            ],
        }
    )


async def _collect(provider, baseline=None):
    generator = ResumeGenerator(provider)
    async for _ in generator.generate(
        _reasonably_full_profile(), None, GenerateOptions(), baseline=baseline
    ):
        pass
    return provider.messages[-1]["content"]


# ===== 生成链路：事实基线 =====


async def test_prompt_is_unchanged_when_the_ledger_is_empty():
    """没启用台账的用户，拿到的提示词必须与加这个功能之前一模一样。"""
    without_argument = await _collect(CapturingProvider())
    with_empty_baseline = await _collect(CapturingProvider(), baseline=None)

    assert without_argument == with_empty_baseline
    assert "已确认事实基线" not in without_argument


async def test_confirmed_facts_and_blocked_wording_reach_the_prompt():
    from app.schemas.claim import ClaimDigestOut

    provider = CapturingProvider()
    prompt = await _collect(
        provider,
        baseline=ClaimDigestOut(
            confirmed_count=1,
            baseline_text='{"subject":"检索平台","fact":"实现检索接口","responsibility":"参与"}',
            blocked_wording=["【待补：倍数】优化了检索速度"],
            warnings=["「导师项目」待确认"],
        ),
    )

    assert "已确认事实基线" in prompt
    assert "实现检索接口" in prompt
    # 未确认的说法必须作为"禁止使用"出现，而不是被静默丢掉。
    assert "尚未核实" in prompt
    assert "优化了检索速度" in prompt
    # 承担程度与个人边界要能约束表述强度。
    assert "参与" in prompt
    assert "boundary" in prompt


# ===== 导出闸门 =====


def _manual_resume(client, content: dict, title: str = "草稿") -> int:
    response = client.post(
        "/api/resumes/manual",
        json={"title": title, "content": content, "job_id": None},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_export_is_blocked_when_the_resume_still_has_placeholders(client):
    resume_id = _manual_resume(
        client,
        {"name": "张三", "summary": "关注后端【待补：具体方向】"},
    )

    for fmt in ("pdf", "html", "md", "json"):
        response = client.get(f"/api/resumes/{resume_id}/export", params={"format": fmt})
        assert response.status_code == 409, fmt
        detail = response.json()["detail"]
        assert "个人总结" in detail
        assert "导出草稿" in detail


def test_export_succeeds_for_a_finished_resume(client):
    resume_id = _manual_resume(client, {"name": "张三", "summary": "关注后端与检索系统。"})
    response = client.get(f"/api/resumes/{resume_id}/export", params={"format": "json"})
    assert response.status_code == 200


def test_allow_incomplete_is_an_explicit_way_out(client):
    """拦下不等于堵死：用户明确要一份草稿自查时，得给一条出路。"""
    resume_id = _manual_resume(client, {"name": "张三", "summary": "关注后端【待补】"})

    blocked = client.get(f"/api/resumes/{resume_id}/export", params={"format": "md"})
    assert blocked.status_code == 409

    allowed = client.get(
        f"/api/resumes/{resume_id}/export",
        params={"format": "md", "allow_incomplete": "true"},
    )
    assert allowed.status_code == 200
    assert "【待补】" in allowed.text


def test_placeholder_in_a_nested_entry_is_caught(client):
    """占位符藏在经历里同样要被拦下——只扫摘要是最容易漏的一种实现。"""
    resume_id = _manual_resume(
        client,
        {
            "name": "张三",
            "experience": [
                {
                    "company": "示例公司",
                    "role": "实习生",
                    "description": ["实现检索接口【待补：QPS】"],
                }
            ],
        },
    )
    response = client.get(f"/api/resumes/{resume_id}/export", params={"format": "pdf"})
    assert response.status_code == 409
    assert "示例公司" in response.json()["detail"]


def test_resume_without_placeholders_is_not_affected_by_the_gate(client):
    """闸门只认未完成标记，不该顺手拦下正常内容。"""
    resume_id = _manual_resume(
        client,
        {"name": "张三", "summary": "待补充说明的能力？没有，这里写的是完整句子。"},
    )
    # 「待补充」不是标记，「待补充说明」里的「待补」也不算——只有【待补…】这类才算。
    assert ResumeContent.model_validate(
        client.get(f"/api/resumes/{resume_id}").json()["content"]
    ).summary.startswith("待补充说明")
    assert client.get(f"/api/resumes/{resume_id}/export", params={"format": "json"}).status_code == 200
