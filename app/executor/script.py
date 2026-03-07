from __future__ import annotations

import asyncio
import logging
from pathlib import Path

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
