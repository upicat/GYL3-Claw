"""shell_cmd tool: execute shell commands locally."""
from __future__ import annotations

import json
import logging

from app.tools.registry import register_tool

logger = logging.getLogger(__name__)

_DEFINITION = {
    "type": "function",
    "function": {
        "name": "shell_cmd",
        "description": "在本地执行 Shell 命令并返回输出。可用于查看文件、系统状态、运行程序等。危险命令（rm -rf, sudo 等）会被自动拦截。",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的 Shell 命令",
                }
            },
            "required": ["command"],
        },
    },
}


@register_tool("shell_cmd", definition=_DEFINITION)
async def execute_shell_cmd(arguments: str) -> str:
    from app.tools.shell import shell_execute

    try:
        args = json.loads(arguments)
        command = args.get("command", "")
    except (json.JSONDecodeError, AttributeError):
        command = arguments.strip()

    if not command:
        return "Error: empty command"

    logger.info("Tool call: shell_cmd(%r)", command)
    return await shell_execute(command)
