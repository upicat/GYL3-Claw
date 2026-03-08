"""Plugin: /web command + web_search executor."""
from __future__ import annotations

from app.executor.dispatcher import RouteResult
from app.executor.registry import register_command, register_executor


@register_command("/web")
def handle_web(cmd: str, arg: str) -> RouteResult | None:
    web_query = arg
    if cmd != "/web":
        web_query = cmd[4:] + (" " + arg if arg else "")
    if not web_query:
        return RouteResult(type="command", command_response="用法: /web <搜索关键词>\n示例: /web Python 最新版本")
    return RouteResult(type="web_search", message=web_query)


@register_executor("web_search")
async def execute_web_search(route, chat_id, user_id, prompt_manager) -> str:
    from app.utils.web_search_default import search, format_search_results

    response = search(route.message)
    return format_search_results(response)
