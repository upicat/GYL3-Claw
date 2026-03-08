"""Executor registration center for commands and executors."""
from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

# "/web" -> handler(cmd: str, arg: str) -> RouteResult | None
COMMAND_HANDLERS: dict[str, Callable] = {}

# "web_search" -> async exec_fn(route, chat_id, user_id, prompt_manager) -> str
EXECUTORS: dict[str, Callable] = {}


def register_command(command: str, *aliases: str):
    """Decorator that registers a slash-command handler (and optional aliases).

    The handler signature: ``(cmd: str, arg: str) -> RouteResult | None``

    Usage::

        @register_command("/web")
        def handle_web(cmd, arg):
            ...
    """
    def decorator(fn: Callable):
        for c in (command, *aliases):
            COMMAND_HANDLERS[c] = fn
            logger.debug("Registered command: %s", c)
        return fn
    return decorator


def register_executor(route_type: str):
    """Decorator that registers an executor for a given route type.

    The executor signature:
    ``async (route, chat_id, user_id, prompt_manager) -> str``

    Usage::

        @register_executor("web_search")
        async def execute_web_search(route, chat_id, user_id, prompt_manager):
            ...
    """
    def decorator(fn: Callable):
        EXECUTORS[route_type] = fn
        logger.debug("Registered executor: %s", route_type)
        return fn
    return decorator
