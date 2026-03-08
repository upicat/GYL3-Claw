"""Plugin: /url command + url_fetch executor."""
from __future__ import annotations

from app.executor.dispatcher import RouteResult
from app.executor.registry import register_command, register_executor


@register_command("/url")
def handle_url(cmd: str, arg: str) -> RouteResult | None:
    url_text = arg
    if cmd != "/url":
        url_text = cmd[4:] + (" " + arg if arg else "")
    if not url_text:
        return RouteResult(type="command", command_response="用法: /url <网页链接>\n示例: /url https://example.com")
    return RouteResult(type="url_fetch", message=url_text.strip())


@register_executor("url_fetch")
async def execute_url_fetch(route, chat_id, user_id, prompt_manager) -> str:
    from app.utils.url_fetcher import summarize_url

    return await summarize_url(route.message, prompt_manager)
