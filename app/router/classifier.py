from __future__ import annotations

import logging

from openai import AsyncOpenAI

from app.config import settings
from app.prompt.manager import PromptManager

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


async def classify_by_ai(message: str, prompt_manager: PromptManager) -> str:
    router_prompt = prompt_manager.get_router_prompt()
    if not router_prompt:
        return "general"

    router_model = prompt_manager.get_router_model()
    model = router_model.name or settings.defaults.model

    client = _get_client()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": router_prompt},
                {"role": "user", "content": message},
            ],
            temperature=router_model.temperature if router_model.temperature is not None else 0.0,
            max_tokens=router_model.max_tokens or 50,
        )
        domain_id = (resp.choices[0].message.content or "general").strip().lower()
        # Validate that the classified domain exists
        if prompt_manager.get_prompt(domain_id):
            return domain_id
        return "general"
    except Exception:
        logger.exception("AI classification failed")
        return "general"
