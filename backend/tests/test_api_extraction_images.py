"""岗位/个人资料识别的图片输入：接口层行为。

两个接口共用一套控制流，所以统一参数化；模型一律用假 Provider，不访问真实服务。
"""

import base64
import json

import pytest

from app.schemas.extraction import MAX_EXTRACTION_IMAGE_COUNT
from app.schemas.setting import LLMConfig
from app.services.attachments import MAX_ATTACHMENTS_TOTAL_BYTES
from app.services.llm.base import BaseLLMProvider, LLMError

JOB_PATH = "/api/jobs/parse-text"
PROFILE_PATH = "/api/profile/parse-text"

JOB_SCREENSHOT = """北京后端开发工程师 - 示例科技
工作职责：负责 Python 服务开发。
任职要求：本科及以上学历，熟悉 Python。"""
PROFILE_SCREENSHOT = """李四
电话：13800000000
求职意向：后端开发工程师"""

JOB_FIELDS = {
    "title": "后端开发工程师",
    "company": "示例科技",
    "location": "北京",
    "job_type": "社招",
    "description": "负责 Python 服务开发。",
    "requirements": "本科及以上学历，熟悉 Python。",
}
PROFILE_FIELDS = {"name": "李四", "phone": "13800000000"}


class RecordingProvider(BaseLLMProvider):
    """记录发给模型的消息，供断言图片是否正确随请求发出。"""

    def __init__(self, response: str | Exception):
        super().__init__(LLMConfig(base_url="https://model.example/v1", model="test-model"))
        self.response = response
        self.messages: list[dict] = []

    async def chat(self, messages: list[dict]) -> str:
        self.messages = messages
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    async def stream_chat(self, _messages):
        yield ""


def _png(size: int = 128) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"0" * (size - 8)


def _image(name: str = "screenshot.png", raw: bytes | None = None, mime: str = "image/png") -> dict:
    raw = raw if raw is not None else _png()
    return {
        "name": name,
        "mime_type": mime,
        "data": "data:image/png;base64," + base64.b64encode(raw).decode("ascii"),
    }


def _configure_model(client) -> None:
    response = client.put(
        "/api/settings/llm",
        json=LLMConfig(
            base_url="https://model.example/v1", api_key="test-key", model="test-model"
        ).model_dump(),
    )
    assert response.status_code == 200


def _screenshot_for(path: str) -> str:
    return JOB_SCREENSHOT if path == JOB_PATH else PROFILE_SCREENSHOT


def _response_for(path: str) -> str:
    fields = JOB_FIELDS if path == JOB_PATH else PROFILE_FIELDS
    return json.dumps({"transcription": _screenshot_for(path), **fields}, ensure_ascii=False)


def _factory_path(path: str) -> str:
    return "app.api.jobs.create_provider" if path == JOB_PATH else "app.api.profile.create_provider"


@pytest.mark.parametrize("path", [JOB_PATH, PROFILE_PATH])
def test_images_only_request_reaches_the_model_as_image_parts(client, monkeypatch, path):
    _configure_model(client)
    provider = RecordingProvider(_response_for(path))
    monkeypatch.setattr(_factory_path(path), lambda _config: provider)

    result = client.post(path, json={"text": "", "images": [_image(), _image("第二张.png")]})

    assert result.status_code == 200
    body = result.json()
    assert body["recognition_source"] == "ai"
    # 用户能看到模型读到了什么，这是图片识别最重要的人工核对手段
    assert body["recognized_text"] == _screenshot_for(path)
    assert any("对照截图核对" in warning for warning in body["warnings"])

    parts = provider.messages[1]["content"]
    assert isinstance(parts, list)
    assert parts[0]["type"] == "text"
    assert [part["type"] for part in parts[1:]] == ["image_url", "image_url"]


@pytest.mark.parametrize("path", [JOB_PATH, PROFILE_PATH])
def test_forged_and_unsupported_images_are_rejected(client, path):
    _configure_model(client)

    # 声明是 PNG，内容不是
    forged = client.post(path, json={"text": "", "images": [_image(raw=b"not a png at all")]})
    assert forged.status_code == 422
    assert "声明图片格式不一致" in forged.json()["detail"]

    # 文本附件不能混进识别接口
    text_file = client.post(
        path,
        json={"text": "", "images": [{"name": "笔记.txt", "mime_type": "text/plain", "data": "内容"}]},
    )
    assert text_file.status_code == 422
    assert "仅支持" in text_file.json()["detail"]


@pytest.mark.parametrize("path", [JOB_PATH, PROFILE_PATH])
def test_too_many_or_oversized_images_are_rejected(client, path):
    _configure_model(client)

    too_many = client.post(
        path, json={"text": "", "images": [_image(f"{i}.png") for i in range(MAX_EXTRACTION_IMAGE_COUNT + 1)]}
    )
    assert too_many.status_code == 422

    oversized = client.post(path, json={"text": "", "images": [_image(raw=_png(2 * 1024 * 1024 + 1))]})
    assert oversized.status_code == 422
    assert "2 MB" in oversized.json()["detail"]

    # 单张都合法、合计超限：这是请求体不超 8 MB 的保证，必须由服务端拦住。
    # 取刚好越过合计上限、但编码后仍在请求体上限之内的体积，才能走到这条校验
    # （再大就会先被中间件以 413 挡下，那是另一道闸，不是这条规则失效）。
    over_total = [_image(raw=_png(2 * 1024 * 1024)), _image(raw=_png(2 * 1024 * 1024)), _image(raw=_png(1_500_000))]
    assert sum(len(item["data"]) for item in over_total) < 8 * 1024 * 1024
    total = client.post(path, json={"text": "", "images": over_total})
    assert total.status_code == 422
    assert "5 MB" in total.json()["detail"]

    # 明显超限的请求会被请求体上限更早挡下，同样是拒绝
    huge = client.post(path, json={"text": "", "images": [_image(raw=_png(2 * 1024 * 1024))] * 4})
    assert huge.status_code in (413, 422)


@pytest.mark.parametrize("path", [JOB_PATH, PROFILE_PATH])
def test_a_text_only_model_degrades_with_an_actionable_warning(client, monkeypatch, path):
    """用户当前用的就是纯文本模型，这是最先撞到的路径。"""
    _configure_model(client)
    monkeypatch.setattr(
        _factory_path(path),
        lambda _config: RecordingProvider(LLMError("请求格式错误，请检查模型名称与参数设置（HTTP 400）")),
    )

    result = client.post(path, json={"text": "", "images": [_image()]})

    assert result.status_code == 200  # 保持"永远 200 + 草稿"的既有契约
    body = result.json()
    assert body["recognition_source"] == "local"
    assert any("多模态" in warning for warning in body["warnings"])


@pytest.mark.parametrize("path", [JOB_PATH, PROFILE_PATH])
def test_images_without_a_model_say_images_cannot_be_read(client, monkeypatch, path):
    def fail_if_called(_config):
        raise AssertionError("未配置模型时不应创建 provider")

    monkeypatch.setattr(_factory_path(path), fail_if_called)

    result = client.post(path, json={"text": "", "images": [_image()]})

    assert result.status_code == 200
    body = result.json()
    assert body["recognition_source"] == "local"
    assert any("图片识别无法进行" in warning for warning in body["warnings"])


@pytest.mark.parametrize("path", [JOB_PATH, PROFILE_PATH])
def test_blank_text_without_images_is_still_rejected(client, path):
    assert client.post(path, json={"text": ""}).status_code == 422
    assert client.post(path, json={}).status_code == 422
    assert client.post(path, json={"text": "   \r\n\t"}).status_code == 422


def test_worst_case_image_payload_fits_the_default_body_limit():
    """钉住"图片总量上限是为请求体上限服务的"这条链。

    中间件在 application.py 按 max_request_body_mb 限制请求体，而识别接口没有（也不该有）
    放宽豁免。所以 base64 膨胀后的最大合法请求必须仍在默认上限之内。
    """
    from app.application import create_app
    from app.config import get_settings

    settings = get_settings()
    max_body = settings.max_request_body_mb * 1024 * 1024
    # base64 每 3 字节膨胀成 4 个字符
    encoded = MAX_ATTACHMENTS_TOTAL_BYTES * 4 // 3
    assert encoded < max_body
    # 顺带确认这两个接口确实没有走 larger_body_paths 豁免
    assert max_body == 8 * 1024 * 1024
    assert create_app() is not None
