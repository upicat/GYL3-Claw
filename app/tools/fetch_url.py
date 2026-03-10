"""fetch_url tool: fetch web page content and return as text."""
from __future__ import annotations

import json
import logging

from app.tools.registry import register_tool

logger = logging.getLogger(__name__)

_DEFINITION = {
    "type": "function",
    "function": {
        "name": "fetch_url",
        "description": "抓取网页内容并返回文本。用于获取用户提供的 URL 页面内容。返回页面正文文本，可用于后续总结分析。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要抓取的网页 URL，必须以 http:// 或 https:// 开头",
                }
            },
            "required": ["url"],
        },
    },
}

_MAX_CONTENT_LENGTH = 100000


@register_tool("fetch_url", definition=_DEFINITION)
async def execute_fetch_url(arguments: str) -> str:
    from app.tools.url_fetcher import fetch_url

    try:
        args = json.loads(arguments)
        url = args.get("url", "")
    except (json.JSONDecodeError, AttributeError):
        url = arguments.strip()

    if not url:
        return "Error: empty URL"

    logger.info("Tool call: fetch_url(%r)", url)
    ok, content = await fetch_url(url)
    if not ok:
        return f"抓取失败: {content}"

    if len(content) > _MAX_CONTENT_LENGTH:
        content = content[:_MAX_CONTENT_LENGTH] + "\n\n[内容已截断...]"

    return content
