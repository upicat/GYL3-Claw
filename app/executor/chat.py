from __future__ import annotations

import logging

from openai import AsyncOpenAI

from app.config import settings
from app.prompt.manager import PromptConfig

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.gateway.api_key,
            base_url=settings.gateway.base_url or None,
        )
    return _client


async def chat_execute(
    prompt_config: PromptConfig,
    system_message: str,
    user_message: str,
    history: list[dict],
) -> str:
    client = _get_client()

    model = prompt_config.model.name or settings.defaults.model
    temperature = prompt_config.model.temperature if prompt_config.model.temperature is not None else settings.defaults.temperature
    max_tokens = prompt_config.model.max_tokens or settings.defaults.max_tokens

    messages: list[dict] = []
    if system_message:
        messages.append({"role": "system", "content": system_message})
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""
    except Exception:
        logger.exception("AI chat failed")
        return "抱歉，AI 服务暂时不可用，请稍后重试。"
