"""Vision LLM client — OpenAI-compatible multimodal chat/completions."""

from __future__ import annotations

import logging
import mimetypes
import re
from typing import Any, Dict, List, Optional

import httpx

from services.generation.llm_response_cleaner import strip_model_reasoning

logger = logging.getLogger(__name__)

TEXT_ONLY_MODEL_PATTERNS = (
    r"qwen3\.7-max",
    r"qwen3\.6-max",
    r"deepseek-v\d",
    r"deepseek-r\d",
)

VISION_MODEL_HINTS = (
    r"vl",
    r"vision",
    r"ocr",
    r"qvq",
    r"qwen3\.7-plus",
    r"qwen3\.6-plus",
    r"qwen3\.5-plus",
    r"qwen-vl",
    r"qwen3-vl",
    r"doubao.*seed",
    r"gpt-4o",
    r"gpt-4\.1",
    r"gemini.*pro-vision",
)


def image_to_data_url(image_path: str) -> str:
    """Encode a local image as a data URL with the correct MIME type."""
    import base64

    mime, _ = mimetypes.guess_type(image_path)
    if not mime or not mime.startswith("image/"):
        mime = "image/jpeg"
    with open(image_path, "rb") as handle:
        encoded = base64.b64encode(handle.read()).decode("utf-8")
    return f"data:{mime};base64,{encoded}"


def validate_vision_model_config(config: Dict[str, Any]) -> None:
    """Raise a user-friendly error when the configured model cannot accept images."""
    model = str(config.get("model") or "").strip()
    if not model:
        raise ValueError("图片分析模型未配置 model 字段")

    lowered = model.lower()
    for pattern in TEXT_ONLY_MODEL_PATTERNS:
        if re.search(pattern, lowered):
            raise ValueError(
                f"模型「{model}」不支持图片输入。"
                "请在「模型配置 → 图片分析模型」中改用视觉模型，"
                "例如 qwen-vl-max、qwen3-vl-plus 或 qwen3.5-plus。"
            )

    if not any(re.search(pattern, lowered) for pattern in VISION_MODEL_HINTS):
        logger.warning("模型 %s 可能不支持图片，建议使用 VL/多模态系列模型", model)


def build_multimodal_user_content(prompt: str, image_paths: List[str]) -> List[Dict[str, Any]]:
    """Build OpenAI-compatible multimodal content blocks."""
    content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
    for image_path in image_paths:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": image_to_data_url(image_path)},
            }
        )
    return content


def call_vision_chat(
    config: Dict[str, Any],
    messages: List[Dict[str, Any]],
    *,
    temperature: Optional[float] = None,
    timeout: int = 600,
) -> str:
    """Call a vision-capable chat/completions endpoint."""
    validate_vision_model_config(config)

    api_key = str(config.get("api_key") or "").strip()
    base_url = str(config.get("base_url") or "").strip().rstrip("/")
    model = str(config.get("model") or "").strip()
    if not api_key or not base_url or not model:
        raise ValueError("图片分析模型配置不完整，请检查 api_key、base_url 和 model")

    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": float(temperature if temperature is not None else config.get("temperature") or 0.3),
    }
    max_tokens = config.get("max_tokens")
    if max_tokens:
        body["max_tokens"] = int(max_tokens)

    url = f"{base_url}/chat/completions"
    with httpx.Client(timeout=timeout, trust_env=False) as client:
        response = client.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )

    if response.status_code >= 400:
        detail = response.text[:1000]
        if "Unexpected item type in content" in detail or "InvalidParameter" in detail:
            raise RuntimeError(
                f"图片分析模型「{model}」不支持当前多模态输入。"
                "请改用视觉模型，例如 qwen-vl-max 或 qwen3-vl-plus。"
                f" 原始错误: {detail[:300]}"
            )
        raise RuntimeError(f"图片分析请求失败 HTTP {response.status_code}: {detail}")

    payload = response.json()
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return strip_model_reasoning(str(message.get("content") or "").strip())
