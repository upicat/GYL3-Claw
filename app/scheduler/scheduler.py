from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.tools.shell import shell_execute
from app.feishu.message import send_text
from app.memory.database import get_db

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _run_command_task(name: str, target: str, payload: str | None) -> None:
    logger.info("Running scheduled command task: %s -> %s", name, target)
    result = await shell_execute(target)
    logger.info("Scheduled task %s result: %s", name, result[:200])


async def _run_message_task(name: str, target: str, payload: str | None) -> None:
    logger.info("Running scheduled message task: %s -> %s", name, target)
    text = payload or f"定时任务 [{name}] 触发"
    await send_text(target, text)


async def init_scheduler() -> AsyncIOScheduler:
    global _scheduler
    _scheduler = AsyncIOScheduler()

    db = get_db()
    cursor = await db.execute(
        "SELECT name, cron, type, target, payload FROM scheduled_tasks WHERE enabled = 1"
    )
    rows = await cursor.fetchall()
    for row in rows:
        _add_job(
            name=row["name"],
            cron=row["cron"],
            task_type=row["type"],
            target=row["target"],
            payload=row["payload"],
        )

    _scheduler.start()
    logger.info("Scheduler started with %d tasks", len(rows))
    return _scheduler


def _add_job(name: str, cron: str, task_type: str, target: str, payload: str | None) -> None:
    if _scheduler is None:
        return
    trigger = CronTrigger.from_crontab(cron)
    if task_type == "command":
        _scheduler.add_job(_run_command_task, trigger, args=[name, target, payload], id=name, replace_existing=True)
    elif task_type == "message":
        _scheduler.add_job(_run_message_task, trigger, args=[name, target, payload], id=name, replace_existing=True)
    else:
        logger.warning("Unknown task type: %s", task_type)


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None


async def add_scheduled_task(
    name: str, cron: str, task_type: str, target: str, payload: str | None = None
) -> None:
    db = get_db()
    await db.execute(
        "INSERT OR REPLACE INTO scheduled_tasks (name, cron, type, target, payload) VALUES (?, ?, ?, ?, ?)",
        (name, cron, task_type, target, payload),
    )
    await db.commit()
    _add_job(name, cron, task_type, target, payload)


async def remove_scheduled_task(name: str) -> bool:
    db = get_db()
    cursor = await db.execute("DELETE FROM scheduled_tasks WHERE name = ?", (name,))
    await db.commit()
    if _scheduler:
        try:
            _scheduler.remove_job(name)
        except Exception:
            pass
    return cursor.rowcount > 0


async def list_scheduled_tasks() -> list[dict]:
    db = get_db()
    cursor = await db.execute("SELECT name, cron, type, target, enabled FROM scheduled_tasks")
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]
