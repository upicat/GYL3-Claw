from __future__ import annotations

import asyncio
import logging

from app.executor.dispatcher import RouteResult
from app.executor.registry import register_command, register_executor

logger = logging.getLogger(__name__)

DANGEROUS_PATTERNS = [
    "rm -rf", "sudo ", "shutdown", "reboot", "mkfs", "dd if=",
    "> /dev", ":(){", "chmod -R 777", "mv / ", "rm -r /",
]

_MAX_OUTPUT = 4000  # keep first + last chars when output is too long
_TIMEOUT = 30


async def shell_execute(command: str, timeout: int = _TIMEOUT) -> str:
    command = command.strip()
    if not command:
        return "用法: /cmd <命令>\n示例: /cmd ls -la"

    # Safety check
    lower = command.lower()
    for pat in DANGEROUS_PATTERNS:
        if pat in lower:
            return f"拒绝执行: 命令包含危险操作 `{pat}`"

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        return f"命令执行超时（{timeout}秒）: `{command}`"
    except Exception as e:
        logger.exception("Shell execute error")
        return f"命令执行失败: {e}"

    output = (stdout or b"").decode(errors="replace")
    if stderr:
        err_text = stderr.decode(errors="replace")
        if err_text.strip():
            output = output + "\n[stderr]\n" + err_text

    output = output.strip()
    if not output:
        return f"命令执行完成（exit {proc.returncode}），无输出。"

    # Truncate if too long
    if len(output) > _MAX_OUTPUT:
        half = _MAX_OUTPUT // 2
        output = output[:half] + f"\n\n... 省略 {len(output) - _MAX_OUTPUT} 字符 ...\n\n" + output[-half:]

    prefix = f"$ {command}\n"
    if proc.returncode != 0:
        prefix += f"[exit {proc.returncode}]\n"
    return prefix + output


# --- Plugin registration ---


@register_command("/cmd")
def handle_cmd(cmd: str, arg: str) -> RouteResult | None:
    cmd_text = arg
    if cmd != "/cmd":
        cmd_text = cmd[4:] + (" " + arg if arg else "")
    if not cmd_text:
        return RouteResult(type="command", command_response="用法: /cmd <命令>\n示例: /cmd ls -la")
    return RouteResult(type="shell_cmd", message=cmd_text)


@register_command("/claude")
def handle_claude(cmd: str, arg: str) -> RouteResult | None:
    claude_text = arg
    if cmd != "/claude":
        claude_text = cmd[7:] + (" " + arg if arg else "")
    if not claude_text:
        return RouteResult(type="command", command_response="用法: /claude <问题>\n示例: /claude 用Python写一个快排")
    return RouteResult(type="claude_cmd", message=claude_text)


@register_executor("shell_cmd")
async def execute_shell_cmd(route, chat_id, user_id, prompt_manager) -> str:
    return await shell_execute(route.message)


@register_executor("claude_cmd")
async def execute_claude_cmd(route, chat_id, user_id, prompt_manager) -> str:
    import shlex

    cmd = f"claude -p {shlex.quote(route.message)}"
    return await shell_execute(cmd, timeout=300)
