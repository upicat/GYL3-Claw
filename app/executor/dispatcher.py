from __future__ import annotations

import logging
from dataclasses import dataclass

from app.executor.chat import chat_execute
from app.executor.script import script_execute
from app.executor.shell import shell_execute
from app.executor.rag import rag_execute
from app.memory.conversation import get_history, save_message
from app.prompt.manager import PromptManager
from app.utils.web_search_default import search, format_search_results

logger = logging.getLogger(__name__)


@dataclass
class RouteResult:
    type: str  # "chat" | "script" | "rag" | "command" | "web_search" | "shell_cmd" | "claude_cmd"
    domain_id: str = ""
    message: str = ""
    script_name: str = ""
    script_args: list[str] | None = None
    command_response: str = ""


async def dispatch(
    route: RouteResult,
    chat_id: str,
    user_id: str,
    prompt_manager: PromptManager,
) -> str:
    if route.type == "command":
        return route.command_response

    if route.type == "script":
        return await script_execute(route.script_name, route.script_args)

    if route.type == "shell_cmd":
        return await shell_execute(route.message)

    if route.type == "claude_cmd":
        import shlex
        cmd = f"claude -p {shlex.quote(route.message)}"
        return await shell_execute(cmd, timeout=300)

    if route.type == "web_search":
        response = search(route.message)
        return format_search_results(response)

    if route.type == "rag":
        return await rag_execute(route.message)

    # chat
    prompt_config = prompt_manager.get_prompt(route.domain_id)
    if not prompt_config:
        prompt_config = prompt_manager.get_prompt("general")
    if not prompt_config:
        return "没有找到可用的 prompt 配置。"

    system_msg = prompt_manager.build_system_message(prompt_config.id)
    history = await get_history(chat_id)

    await save_message(chat_id, user_id, "user", route.message, prompt_config.id)

    reply = await chat_execute(prompt_config, system_msg, route.message, history)

    await save_message(chat_id, user_id, "assistant", reply, prompt_config.id)

    return f"[{prompt_config.name}] {reply}"
