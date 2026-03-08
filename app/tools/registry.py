"""Tool registration center for OpenAI function calling tools."""
from __future__ import annotations

import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

# name -> {"definition": openai_schema_dict, "execute": async_fn(arguments: str) -> str}
TOOLS: dict[str, dict] = {}


def register_tool(name: str, definition: dict):
    """Decorator that registers a tool definition and its async executor.

    Usage::

        @register_tool("web_search", definition={...openai schema...})
        async def execute_web_search(arguments: str) -> str:
            ...
    """
    def decorator(fn: Callable[[str], Awaitable[str]]):
        TOOLS[name] = {"definition": definition, "execute": fn}
        logger.debug("Registered tool: %s", name)
        return fn
    return decorator


def get_tool_definition(name: str) -> dict | None:
    """Get OpenAI tool schema by name."""
    entry = TOOLS.get(name)
    return entry["definition"] if entry else None


def get_tool_executor(name: str) -> Callable[[str], Awaitable[str]] | None:
    """Get async executor function by name."""
    entry = TOOLS.get(name)
    return entry["execute"] if entry else None


def resolve_tool_references(tools: list) -> list[dict]:
    """Resolve a mixed list of tool references.

    - If an item is a string, look it up in the registry and substitute the schema.
    - If an item is a dict, pass it through as-is (backward compatible).
    """
    resolved: list[dict] = []
    for item in tools:
        if isinstance(item, str):
            defn = get_tool_definition(item)
            if defn:
                resolved.append(defn)
            else:
                logger.warning("Tool reference '%s' not found in registry, skipping", item)
        elif isinstance(item, dict):
            resolved.append(item)
    return resolved
