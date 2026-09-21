"""简历生成核心流程测试（使用假 Provider，不发起真实网络请求）。"""
import json

from app.schemas.job import JobOut
from app.schemas.profile import ProfileOut
from app.schemas.resume import GenerateOptions
from app.schemas.setting import LLMConfig
from app.services.llm.base import BaseLLMProvider
from app.services.llm.openai_compat import OpenAICompatProvider
from app.services.resume.resume_generator import (
    ResumeGenerator,
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
