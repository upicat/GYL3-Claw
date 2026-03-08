from __future__ import annotations

from app.executor.registry import register_executor


async def rag_execute(query: str) -> str:
    return "RAG 功能开发中，敬请期待。"


# --- Plugin registration ---


@register_executor("rag")
async def execute_rag(route, chat_id, user_id, prompt_manager) -> str:
    return await rag_execute(route.message)
