from __future__ import annotations

import json
import logging

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)

from app.feishu.client import get_feishu_client

logger = logging.getLogger(__name__)


async def send_text(chat_id: str, text: str) -> bool:
    client = get_feishu_client()
    req = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("text")
            .content(json.dumps({"text": text}))
            .build()
        )
        .build()
    )
    resp = await client.im.v1.message.acreate(req)
    if not resp.success():
        logger.error("Failed to send text: %s %s", resp.code, resp.msg)
        return False
    return True


async def reply_text(message_id: str, text: str) -> bool:
    client = get_feishu_client()
    req = (
        ReplyMessageRequest.builder()
        .message_id(message_id)
        .request_body(
            ReplyMessageRequestBody.builder()
            .msg_type("text")
            .content(json.dumps({"text": text}))
            .build()
        )
        .build()
    )
    resp = await client.im.v1.message.areply(req)
    if not resp.success():
        logger.error("Failed to reply text: %s %s", resp.code, resp.msg)
        return False
    return True


async def send_card(chat_id: str, title: str, content: str, color: str = "blue") -> bool:
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": color,
        },
        "elements": [
            {"tag": "markdown", "content": content},
        ],
    }
    client = get_feishu_client()
    req = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("interactive")
            .content(json.dumps(card))
            .build()
        )
        .build()
    )
    resp = await client.im.v1.message.acreate(req)
    if not resp.success():
        logger.error("Failed to send card: %s %s", resp.code, resp.msg)
        return False
    return True


async def reply_card(message_id: str, title: str, content: str, color: str = "blue") -> bool:
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": color,
        },
        "elements": [
            {"tag": "markdown", "content": content},
        ],
    }
    client = get_feishu_client()
    req = (
        ReplyMessageRequest.builder()
        .message_id(message_id)
        .request_body(
            ReplyMessageRequestBody.builder()
            .msg_type("interactive")
            .content(json.dumps(card))
            .build()
        )
        .build()
    )
    resp = await client.im.v1.message.areply(req)
    if not resp.success():
        logger.error("Failed to reply card: %s %s", resp.code, resp.msg)
        return False
    return True
