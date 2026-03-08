"""web_search tool: definition + executor."""
from __future__ import annotations

import json
import logging

from app.tools.registry import register_tool

logger = logging.getLogger(__name__)

_DEFINITION = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "搜索互联网获取实时信息。当用户的问题涉及近期事件、实时数据、你不确定或知识截止日期之后的内容时，使用此工具进行网络搜索。返回相关网页的摘要信息。不要对你已经确信的常识性问题使用搜索",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询词，应简洁明确，使用与问题最相关的语言",
                }
            },
            "required": ["query"],
        },
    },
}


@register_tool("web_search", definition=_DEFINITION)
async def execute_web_search(arguments: str) -> str:
    from app.utils.web_search_default import search_async, format_search_results

    try:
        args = json.loads(arguments)
        query = args.get("query", "")
    except (json.JSONDecodeError, AttributeError):
        query = arguments
    if not query:
        return "Error: empty search query"

    logger.info("Tool call: web_search(%r)", query)
    response = await search_async(query)
    return format_search_results(response)
