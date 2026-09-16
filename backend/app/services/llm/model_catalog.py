"""按用户配置拉取服务商可用模型列表（GET {base_url}/models）。

只做一件事：把 OpenAI 兼容的模型列表端点结果整理成字符串列表。所有常见服务商
（DeepSeek、豆包、Kimi、智谱、通义、OpenAI、Ollama 等）都提供该端点；不提供时
返回明确的提示，让用户手动填写模型名，而不是报一个看不懂的网络错误。
"""
from __future__ import annotations

import json
import logging

import httpx

from .base import LLMError
from .openai_compat import http_error_message, models_endpoint

logger = logging.getLogger(__name__)

_MAX_RESPONSE_BYTES = 1024 * 1024
_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=5.0)
_MAX_MODELS = 1000


async def list_available_models(base_url: str, api_key: str = "") -> list[str]:
    """返回服务商报告的模型 id 列表（去重、排序）。

    ``base_url`` 的合法性由 ``models_endpoint`` 复用 provider 的同一套校验，
    所以这里不会把请求发到非 HTTPS 的远程地址或带凭据的地址上。
    """
    url = models_endpoint(base_url)
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        raise LLMError("获取模型列表超时，请检查网络后重试") from exc
    except httpx.RequestError as exc:
        raise LLMError("无法连接模型服务，请检查 Base URL 与网络状态") from exc

    if response.status_code != 200:
        logger.warning("模型列表接口返回 status=%s", response.status_code)
        if response.status_code in {400, 404, 405, 501}:
            raise LLMError(
                "该服务商没有提供模型列表接口，请在「模型名称」里手动填写要用的模型"
            )
        raise LLMError(http_error_message(response.status_code))

    if len(response.content) > _MAX_RESPONSE_BYTES:
        raise LLMError("模型列表响应过大，已停止解析")
    try:
        payload = json.loads(response.content)
    except (ValueError, UnicodeError) as exc:
        raise LLMError("模型列表响应无法解析，请手动填写模型名称") from exc

    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise LLMError("模型列表响应格式不符合预期，请手动填写模型名称")

    models: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        identifier = item.get("id")
        if isinstance(identifier, str) and identifier.strip():
            models.append(identifier.strip())
    unique = sorted(dict.fromkeys(models))
    if not unique:
        raise LLMError("服务商没有返回任何可用模型，请在「模型名称」里手动填写")
    return unique[:_MAX_MODELS]


__all__ = ["list_available_models"]
