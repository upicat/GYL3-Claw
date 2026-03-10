from __future__ import annotations

import asyncio
import json
import os
import signal
from pathlib import Path

import click

BASE_DIR = Path(__file__).resolve().parent.parent
SKILLS_DIR = BASE_DIR / "skills"
SCRIPTS_DIR = BASE_DIR / "scripts"
EVAL_LOG = BASE_DIR / "data" / "prompt_eval.jsonl"
PID_FILE = BASE_DIR / "data" / "claw.pid"


@click.group()
def cli():
    """GYL3-Claw 飞书智能助手管理工具"""
    pass


# ─── _run: hidden command, actual blocking entry point for launchd ───


@cli.command("_run", hidden=True)
@click.option("--port", default=None, type=int, help="Server port")
@click.option("--webhook", is_flag=True, help="Use webhook mode instead of long-connection")
def run_server(port: int | None, webhook: bool):
    """内部命令：launchd 实际调用的阻塞入口"""
    from app.main import start_server

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    try:
        start_server(port=port, use_webhook=webhook)
    finally:
        PID_FILE.unlink(missing_ok=True)


# ─── start ───


@cli.command()
@click.option("--port", default=None, type=int, help="Server port")
@click.option("--webhook", is_flag=True, help="Use webhook mode instead of long-connection")
@click.option("--foreground", "-f", is_flag=True, help="前台运行（调试用）")
def start(port: int | None, webhook: bool, foreground: bool):
    """启动服务（默认后台常驻，被 kill 自动拉起）"""
    if foreground:
        # Foreground mode: same as old start, blocking
        from app.main import start_server

        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()))
        try:
            start_server(port=port, use_webhook=webhook)
        finally:
            PID_FILE.unlink(missing_ok=True)
        return

    from app.daemon import is_running, install_and_start

    if is_running():
        click.echo("服务已在运行中。如需重启请用 claw restart")
        return

    install_and_start(port=port, webhook=webhook)
    click.echo("服务已启动（launchd 后台常驻，被 kill 会自动拉起）")
    click.echo("查看日志: claw logs -f")
    click.echo("停止服务: claw stop")


# ─── stop ───


@cli.command()
def stop():
    """停止服务"""
    from app.daemon import is_running, stop_and_uninstall

    if is_running():
        stop_and_uninstall()
        click.echo("服务已停止（launchd 已卸载）")
        return

    # Fallback: PID file (foreground mode)
    if PID_FILE.exists():
        pid = int(PID_FILE.read_text().strip())
        try:
            os.kill(pid, signal.SIGTERM)
            click.echo(f"已发送停止信号 (PID={pid})")
        except ProcessLookupError:
            click.echo(f"进程 {pid} 不存在，清理 PID 文件")
        except PermissionError:
            click.echo(f"无权限停止进程 {pid}")
        PID_FILE.unlink(missing_ok=True)
        return

    click.echo("未找到运行中的服务")


# ─── status ───


@cli.command()
def status():
    """查看服务运行状态"""
    from app.daemon import is_running

    if is_running():
        pid = "unknown"
        if PID_FILE.exists():
            pid = PID_FILE.read_text().strip()
        click.echo(f"服务运行中 (PID={pid})")
    elif PID_FILE.exists():
        pid = PID_FILE.read_text().strip()
        try:
            os.kill(int(pid), 0)
            click.echo(f"服务运行中（前台模式, PID={pid}）")
        except (ProcessLookupError, ValueError):
            click.echo("服务未运行（PID 文件残留，已清理）")
            PID_FILE.unlink(missing_ok=True)
    else:
        click.echo("服务未运行")


# ─── logs ───

LOG_DIR = BASE_DIR / "logs"


@cli.command()
@click.option("-f", "--follow", is_flag=True, help="持续输出新日志（类似 tail -f）")
@click.option("-n", "--lines", default=50, help="显示最后 N 行")
def logs(follow: bool, lines: int):
    """查看服务日志"""
    import subprocess

    log_file = LOG_DIR / "claw.log"
    if not log_file.exists():
        click.echo("暂无日志文件")
        return

    cmd = ["tail", f"-n{lines}"]
    if follow:
        cmd.append("-f")
    cmd.append(str(log_file))

    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        pass


# ─── restart ───


@cli.command()
@click.option("--port", default=None, type=int, help="Server port")
@click.option("--webhook", is_flag=True, help="Use webhook mode instead of long-connection")
@click.pass_context
def restart(ctx, port: int | None, webhook: bool):
    """重启服务"""
    import time
    from app.daemon import install_and_start

    ctx.invoke(stop)
    click.echo("等待旧进程完全退出（约15秒）...")
    time.sleep(15)
    install_and_start(port=port, webhook=webhook)
    click.echo("服务已启动")
    click.echo("查看日志: claw logs -f")


# ─── help ───


@cli.command()
def help():
    """查看使用帮助"""
    click.echo("""
GYL3-Claw 飞书个人智能助手

CLI 命令:
  claw start [--port N] [--webhook]  启动后台服务（launchd 常驻）
  claw start -f [--port N] [--webhook]  前台启动（调试用）
  claw stop                         停止服务
  claw status                       查看服务状态
  claw restart [--port N] [--webhook]  重启服务
  claw logs [-f] [-n 50]            查看日志（-f 持续输出）
  claw help                         查看帮助

  claw skill list                   列出所有技能
  claw skill show <name>            查看技能详情
  claw skill edit <name>            编辑技能（$EDITOR）

  claw script list                  列出可用脚本
  claw schedule list                列出定时任务
  claw schedule add <name> <cron> <type> <target>  添加定时任务
  claw schedule remove <name>       删除定时任务
  claw eval [domain]                查看评测统计

飞书命令:
  /help                 查看帮助
  /list                 列出所有可用技能
  /clear                清除上下文
  /reload               重新加载技能配置
  /eval <1-5> [备注]    对上一轮回答打分
  /web <关键词>          搜索网络信息
  /url <链接>            解析网页内容并总结
  /cmd <命令>            执行本地 shell 命令
  /claude <问题>         调用 Claude Code 回答问题
  /run <script> [args]  执行本地脚本
  /code <问题>           代码助手
  /write <内容>          写作助手
  /schedule <描述>       用自然语言创建定时任务
  /schedule list        查看定时任务
  /schedule remove <名称> 删除定时任务""".strip())


# -- skill subgroup --

@cli.group()
def skill():
    """技能管理"""
    pass


@skill.command("list")
def skill_list():
    """列出所有技能"""
    import yaml

    for child in sorted(SKILLS_DIR.iterdir()):
        if not child.is_dir():
            continue
        skill_file = child / "SKILL.md"
        if not skill_file.exists():
            continue
        text = skill_file.read_text(encoding="utf-8")
        if text.startswith("---"):
            end = text.find("---", 3)
            if end != -1:
                fm = yaml.safe_load(text[3:end]) or {}
                name = fm.get("name", child.name)
                desc = fm.get("description", "")
                cmds = " ".join(fm.get("commands", []))
                tools = ", ".join(fm.get("tools", []))
                click.echo(f"  {name:18s} {desc:30s}  cmds={cmds}  tools={tools}")


@skill.command("show")
@click.argument("name")
def skill_show(name: str):
    """查看技能详情"""
    skill_file = SKILLS_DIR / name / "SKILL.md"
    if not skill_file.exists():
        click.echo(f"Not found: {name}")
        return
    click.echo(skill_file.read_text(encoding="utf-8"))


@skill.command("edit")
@click.argument("name")
def skill_edit(name: str):
    """编辑技能（用 $EDITOR 打开）"""
    import subprocess

    skill_file = SKILLS_DIR / name / "SKILL.md"
    if not skill_file.exists():
        click.echo(f"Not found: {name}")
        return
    editor = os.environ.get("EDITOR", "vim")
    subprocess.call([editor, str(skill_file)])


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
