from __future__ import annotations

import logging

from app.memory.database import get_db

logger = logging.getLogger(__name__)


async def save_message(
    chat_id: str, user_id: str, role: str, content: str, route_name: str = ""
) -> None:
    db = get_db()
    await db.execute(
        "INSERT INTO conversations (chat_id, user_id, role, content, route_name) VALUES (?, ?, ?, ?, ?)",
        (chat_id, user_id, role, content, route_name),
    )
    await db.commit()


async def get_history(chat_id: str, limit: int = 20) -> list[dict]:
    db = get_db()
    cursor = await db.execute(
        "SELECT role, content FROM conversations WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
        (chat_id, limit),
    )
    rows = await cursor.fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]


async def clear_history(chat_id: str) -> int:
    db = get_db()
    cursor = await db.execute("DELETE FROM conversations WHERE chat_id = ?", (chat_id,))
    await db.commit()
    return cursor.rowcount


async def get_last_exchange(chat_id: str) -> dict | None:
    db = get_db()
    cursor = await db.execute(
        "SELECT role, content, route_name, created_at FROM conversations WHERE chat_id = ? ORDER BY id DESC LIMIT 2",
        (chat_id,),
    )
    rows = await cursor.fetchall()
    if len(rows) < 2:
        return None
    # rows are [newer, older] => assistant then user
    assistant_row = None
    user_row = None
    for row in rows:
        if row["role"] == "assistant" and assistant_row is None:
            assistant_row = row
        elif row["role"] == "user" and user_row is None:
            user_row = row
    if not assistant_row or not user_row:
        return None
    return {
        "user_message": user_row["content"],
        "assistant_message": assistant_row["content"],
        "route_name": assistant_row["route_name"],
        "created_at": assistant_row["created_at"],
    }
