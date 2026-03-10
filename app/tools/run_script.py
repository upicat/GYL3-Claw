"""run_script tool: execute scripts from the scripts/ directory."""
from __future__ import annotations

import json
import logging

from app.tools.registry import register_tool

logger = logging.getLogger(__name__)

_DEFINITION = {
    "type": "function",
    "function": {
        "name": "run_script",
        "description": "执行 scripts/ 目录下的脚本（.sh 或 .py）。用于运行预定义的自动化任务。",
        "parameters": {
            "type": "object",
            "properties": {
                "script_name": {
                    "type": "string",
                    "description": "脚本文件名，例如 daily_report.sh",
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "传递给脚本的参数列表（可选）",
                },
            },
            "required": ["script_name"],
        },
    },
}


@register_tool("run_script", definition=_DEFINITION)
async def execute_run_script(arguments: str) -> str:
    from app.executor.script import script_execute, list_scripts

    try:
        args = json.loads(arguments)
        script_name = args.get("script_name", "")
        script_args = args.get("args")
    except (json.JSONDecodeError, AttributeError):
        script_name = arguments.strip()
        script_args = None

    if not script_name:
        scripts = list_scripts()
        if scripts:
            return f"请指定脚本名。可用脚本: {', '.join(scripts)}"
        return "没有可用的脚本。"

    logger.info("Tool call: run_script(%r, %r)", script_name, script_args)
    return await script_execute(script_name, script_args)
