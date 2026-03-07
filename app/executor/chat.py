from __future__ import annotations

import json
import logging

from openai import AsyncOpenAI

from app.config import settings
from app.prompt.manager import PromptConfig

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None

MAX_TOOL_ROUNDS = 3


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.gateway.api_key,
            base_url=settings.gateway.base_url or None,
        )
    return _client


async def _execute_tool_call(name: str, arguments: str) -> str:
    """Execute a tool call and return the result as a string."""
    if name == "web_search":
        from app.utils.web_search_default import search_async, format_search_results
        try:
            args = json.loads(arguments)
            query = args.get("query", "")
        except (json.JSONDecodeError, AttributeError):
            query = arguments
        if not query:
            return "Error: empty search query"
        logger.info("Tool call: web_search(%r)", query)
        response = await search_async(query)
        return format_search_results(response)

    return f"Unknown tool: {name}"


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

    tools = prompt_config.tools or None

    try:
        kwargs: dict = dict(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if tools:
            kwargs["tools"] = tools

        for _ in range(MAX_TOOL_ROUNDS):
            resp = await client.chat.completions.create(**kwargs)
            msg = resp.choices[0].message

            # No tool calls — return content directly
            if not msg.tool_calls:
                return msg.content or ""

            # Append assistant message with tool_calls
            messages.append(msg.model_dump(exclude_none=True))

            # Execute each tool call and append results
            for tool_call in msg.tool_calls:
                result = await _execute_tool_call(
                    tool_call.function.name,
                    tool_call.function.arguments,
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

        # Exhausted rounds, do a final call without tools
        kwargs.pop("tools", None)
        resp = await client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    except Exception:
        logger.exception("AI chat failed")
        return "抱歉，AI 服务暂时不可用，请稍后重试。"
