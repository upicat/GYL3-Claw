from __future__ import annotations

import asyncio
import json
import os
import signal
from pathlib import Path

import click

BASE_DIR = Path(__file__).resolve().parent.parent
PROMPTS_DIR = BASE_DIR / "prompts"
SCRIPTS_DIR = BASE_DIR / "scripts"
EVAL_LOG = BASE_DIR / "data" / "prompt_eval.jsonl"
PID_FILE = BASE_DIR / "data" / "claw.pid"


@click.group()
def cli():
    """GYL3-Claw 飞书智能助手管理工具"""
    pass


@cli.command()
@click.option("--port", default=None, type=int, help="Server port")
@click.option("--webhook", is_flag=True, help="Use webhook mode instead of long-connection")
def start(port: int | None, webhook: bool):
    """启动服务（默认长连接模式）"""
    from app.main import start_server

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    try:
        start_server(port=port, use_webhook=webhook)
    finally:
        PID_FILE.unlink(missing_ok=True)


@cli.command()
def help():
    """查看使用帮助"""
    click.echo("""
GYL3-Claw 飞书个人智能助手

CLI 命令:
  claw start [--port N] [--webhook]  启动服务（默认长连接）
  claw stop                         停止服务
  claw help                         查看帮助

  claw prompt list                  列出所有 Prompt 场景
  claw prompt show <id>             查看 Prompt 详情
  claw prompt edit <id>             编辑 Prompt（$EDITOR）
  claw prompt add <id> <名称> <描述> <角色说明>  创建新场景
  claw prompt del <id>              删除场景

  claw script list                  列出可用脚本
  claw schedule list                列出定时任务
  claw schedule add <name> <cron> <type> <target>  添加定时任务
  claw schedule remove <name>       删除定时任务
  claw eval [domain]                查看评测统计

飞书命令:
  /help                 查看帮助
  /list                 列出所有可用场景
  /switch <id>          锁定场景（后续消息自动使用）
  /current              查看当前场景和版本
  /clear                清除上下文 + 解除锁定
  /reload               手动热加载 Prompt
  /eval <1-5> [备注]    对上一轮回答打分
  /prompt add/del/show  管理 Prompt 场景
  /run <script> [args]  执行本地脚本
  /<场景id> <问题>       用指定场景处理本条消息
""".strip())


@cli.command()
def stop():
    """停止服务"""
    if not PID_FILE.exists():
        click.echo("未找到运行中的服务（无 PID 文件）")
        return
    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        click.echo(f"已发送停止信号 (PID={pid})")
        PID_FILE.unlink(missing_ok=True)
    except ProcessLookupError:
        click.echo(f"进程 {pid} 不存在，清理 PID 文件")
        PID_FILE.unlink(missing_ok=True)
    except PermissionError:
        click.echo(f"无权限停止进程 {pid}")


# -- prompt subgroup --

@cli.group()
def prompt():
    """Prompt 管理"""
    pass


@prompt.command("list")
def prompt_list():
    """列出所有 prompt 配置"""
    import yaml

    for f in sorted(PROMPTS_DIR.glob("*.yaml")):
        with open(f) as fh:
            data = yaml.safe_load(fh) or {}
        pid = data.get("id", f.stem)
        name = data.get("name", "")
        ver = data.get("version", "")
        click.echo(f"  {pid:12s} {name:12s} v{ver}  ({f.name})")


@prompt.command("show")
@click.argument("domain_id")
def prompt_show(domain_id: str):
    """查看 prompt 详情"""
    path = PROMPTS_DIR / f"{domain_id}.yaml"
    if not path.exists():
        click.echo(f"Not found: {domain_id}")
        return
    click.echo(path.read_text())


@prompt.command("edit")
@click.argument("domain_id")
def prompt_edit(domain_id: str):
    """编辑 prompt（用 $EDITOR 打开）"""
    import os
    import subprocess

    path = PROMPTS_DIR / f"{domain_id}.yaml"
    if not path.exists():
        click.echo(f"Not found: {domain_id}")
        return
    editor = os.environ.get("EDITOR", "vim")
    subprocess.call([editor, str(path)])


@prompt.command("add")
@click.argument("domain_id")
@click.argument("name")
@click.argument("description")
@click.argument("role")
@click.option("--keywords", default=None, help="逗号分隔的关键词列表")
def prompt_add(domain_id: str, name: str, description: str, role: str, keywords: str | None):
    """创建新的 prompt 场景"""
    from app.prompt.manager import PromptManager

    kw_list = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else None
    pm = PromptManager(PROMPTS_DIR)
    err = pm.create_prompt(domain_id, name, description, role, kw_list)
    if err:
        click.echo(f"Error: {err}")
    else:
        click.echo(f"Created: {domain_id} ({name})")


@prompt.command("del")
@click.argument("domain_id")
def prompt_del(domain_id: str):
    """删除 prompt 场景"""
    from app.prompt.manager import PromptManager

    pm = PromptManager(PROMPTS_DIR)
    err = pm.delete_prompt(domain_id)
    if err:
        click.echo(f"Error: {err}")
    else:
        click.echo(f"Deleted: {domain_id}")


# -- script subgroup --

@cli.group()
def script():
    """脚本管理"""
    pass


@script.command("list")
def script_list():
    """列出所有脚本"""
    if not SCRIPTS_DIR.exists():
        click.echo("No scripts directory.")
        return
    for f in sorted(SCRIPTS_DIR.iterdir()):
        if f.is_file() and f.suffix in (".sh", ".py"):
            click.echo(f"  {f.name}")


# -- schedule subgroup --

@cli.group()
def schedule():
    """定时任务管理"""
    pass


@schedule.command("list")
def schedule_list():
    """列出定时任务"""
    from app.memory.database import init_db, close_db

    async def _list():
        await init_db()
        from app.scheduler.scheduler import list_scheduled_tasks
        tasks = await list_scheduled_tasks()
        if not tasks:
            click.echo("No scheduled tasks.")
        for t in tasks:
            status = "ON" if t["enabled"] else "OFF"
            click.echo(f"  [{status}] {t['name']:20s} {t['cron']:15s} {t['type']}:{t['target']}")
        await close_db()

    asyncio.run(_list())


@schedule.command("add")
@click.argument("name")
@click.argument("cron")
@click.argument("task_type")
@click.argument("target")
@click.option("--payload", default=None)
def schedule_add(name: str, cron: str, task_type: str, target: str, payload: str | None):
    """添加定时任务"""
    from app.memory.database import init_db, close_db

    async def _add():
        await init_db()
        from app.scheduler.scheduler import add_scheduled_task
        await add_scheduled_task(name, cron, task_type, target, payload)
        click.echo(f"Added: {name}")
        await close_db()

    asyncio.run(_add())


@schedule.command("remove")
@click.argument("name")
def schedule_remove(name: str):
    """删除定时任务"""
    from app.memory.database import init_db, close_db

    async def _remove():
        await init_db()
        from app.scheduler.scheduler import remove_scheduled_task
        ok = await remove_scheduled_task(name)
        click.echo(f"{'Removed' if ok else 'Not found'}: {name}")
        await close_db()

    asyncio.run(_remove())


# -- eval command --

@cli.command("eval")
@click.argument("domain", required=False)
def eval_stats(domain: str | None):
    """查看 prompt 评测统计"""
    if not EVAL_LOG.exists():
        click.echo("No evaluation data yet.")
        return

    records: list[dict] = []
    with open(EVAL_LOG) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    if domain:
        records = [r for r in records if r.get("route_name") == domain]

    if not records:
        click.echo("No records found.")
        return

    scores = [r["score"] for r in records]
    avg = sum(scores) / len(scores)
    dist = {i: scores.count(i) for i in range(1, 6)}

    click.echo(f"Total: {len(scores)} evaluations, Avg: {avg:.2f}")
    for s in range(5, 0, -1):
        bar = "█" * dist.get(s, 0)
        click.echo(f"  {s}⭐ {dist.get(s, 0):3d} {bar}")


if __name__ == "__main__":
    cli()
