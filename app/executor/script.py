from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.executor.dispatcher import RouteResult
from app.executor.registry import register_command, register_executor

logger = logging.getLogger(__name__)

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
TIMEOUT = 30


async def script_execute(script_name: str, args: list[str] | None = None) -> str:
    script_path = SCRIPTS_DIR / script_name

    if not script_path.exists():
        return f"脚本不存在: {script_name}"

    if not script_path.suffix in (".sh", ".py"):
        return f"不支持的脚本类型: {script_path.suffix}（仅支持 .sh / .py）"

    cmd: list[str] = []
    if script_path.suffix == ".sh":
        cmd = ["bash", str(script_path)]
    elif script_path.suffix == ".py":
        cmd = ["python3", str(script_path)]

    if args:
        cmd.extend(args)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(SCRIPTS_DIR),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
        output = stdout.decode().strip()
        err = stderr.decode().strip()
        if proc.returncode != 0:
            return f"脚本执行失败 (exit={proc.returncode}):\n{err or output}"
        return output or "(无输出)"
    except asyncio.TimeoutError:
        proc.kill()  # type: ignore[union-attr]
        return f"脚本执行超时（{TIMEOUT}秒）"
    except Exception:
        logger.exception("Script execution error")
        return "脚本执行异常"


def list_scripts() -> list[str]:
    if not SCRIPTS_DIR.exists():
        return []
    return [
        f.name
        for f in SCRIPTS_DIR.iterdir()
        if f.is_file() and f.suffix in (".sh", ".py")
    ]


# --- Plugin registration ---


@register_command("/run")
def handle_run(cmd: str, arg: str) -> RouteResult | None:
    if not arg:
        scripts = list_scripts()
        if not scripts:
            return RouteResult(type="command", command_response="没有可用的脚本。")
        return RouteResult(type="command", command_response=f"可用脚本: {', '.join(scripts)}\n用法: /run <script> [args]")
    parts = arg.split()
    script_name = parts[0]
    script_args = parts[1:] if len(parts) > 1 else None
    return RouteResult(type="script", script_name=script_name, script_args=script_args)


@register_executor("script")
async def execute_script(route, chat_id, user_id, prompt_manager) -> str:
    return await script_execute(route.script_name, route.script_args)
