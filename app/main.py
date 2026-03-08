from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.executor.dispatcher import dispatch
from app.feishu.message import reply_text, reply_card
from app.memory.database import init_db, close_db
from app.prompt.manager import PromptManager
from app.router.router import Router
from app.scheduler.scheduler import init_scheduler, stop_scheduler

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
PROMPTS_DIR = BASE_DIR / "prompts"

prompt_manager: PromptManager | None = None
router: Router | None = None

# Dedup: track recently processed message_ids
_processed_messages: set[str] = set()
_MSG_CACHE_LIMIT = 1000


# ─── Feishu long-connection event handler ───


def _on_im_message_receive(data: P2ImMessageReceiveV1) -> None:
    """Sync callback invoked by lark.ws inside its event loop."""
    print("[Claw] Received message event!", flush=True)
    logger.info("Received message event via long-connection")

    event = data.event
    if not event or not event.message:
        logger.warning("Empty event data")
        return

    msg = event.message
    sender = event.sender
    message_id = msg.message_id or ""

    # Dedup
    if message_id in _processed_messages:
        logger.info("Duplicate message_id: %s, skipping", message_id)
        return
    _processed_messages.add(message_id)
    if len(_processed_messages) > _MSG_CACHE_LIMIT:
        to_remove = list(_processed_messages)[: _MSG_CACHE_LIMIT // 2]
        for m in to_remove:
            _processed_messages.discard(m)

    # We are called inside the ws event-loop context; get the running loop.
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_handle_message_from_event(msg, sender))
    except RuntimeError:
        logger.error("No running event loop, cannot process message")


async def _handle_message_from_event(msg, sender) -> None:
    """Process a message received via long-connection."""
    try:
        chat_id = msg.chat_id or ""
        message_id = msg.message_id or ""
        msg_type = msg.message_type or ""
        user_id = ""
        if sender and sender.sender_id:
            user_id = sender.sender_id.open_id or ""

        logger.info(
            "Processing message: id=%s chat=%s user=%s type=%s",
            message_id, chat_id, user_id, msg_type,
        )

        if msg_type != "text":
            logger.info("Non-text message, skipping: %s", msg_type)
            await reply_text(message_id, "暂时只支持文本消息哦~")
            return

        content_str = msg.content or "{}"
        logger.debug("Raw content: %s", content_str)
        content = json.loads(content_str)
        text = content.get("text", "").strip()
        logger.info("Message text: %r", text)

        if not text:
            return

        # Remove @bot mentions — SDK v2 uses @_user_1 placeholders
        if msg.mentions:
            for mention in msg.mentions:
                key = mention.key or ""
                if key:
                    text = text.replace(key, "").strip()
            if not text:
                logger.info("Only @mention, no content, skipping")
                return
            logger.info("After stripping mentions: %r", text)

        route_result = await router.route(chat_id, user_id, text)
        logger.info("Route result: type=%s domain=%s", route_result.type, route_result.domain_id)

        reply = await dispatch(route_result, chat_id, user_id, prompt_manager)
        logger.info("Reply length=%d, preview: %s", len(reply) if reply else 0, (reply or "")[:100])

        if not reply:
            return

        if len(reply) > 200 or "\n" in reply:
            title = "Claw"
            if reply.startswith("[") and "]" in reply:
                tag_end = reply.index("]")
                title = reply[1:tag_end]
                body = reply[tag_end + 2:]
            else:
                body = reply
            ok = await reply_card(message_id, title, body)
            logger.info("Sent card reply: ok=%s", ok)
        else:
            ok = await reply_text(message_id, reply)
            logger.info("Sent text reply: ok=%s", ok)

    except Exception:
        logger.exception("Error handling message")
        try:
            mid = msg.message_id or ""
            if mid:
                await reply_text(mid, "处理消息时出错，请稍后重试。")
        except Exception:
            logger.exception("Error sending error reply")


# ─── FastAPI (webhook mode + test endpoint) ───


@asynccontextmanager
async def lifespan(app_: FastAPI):
    global prompt_manager, router

    # In long-connection mode, components are already initialised on the ws loop;
    # only run lifespan init when prompt_manager has not been set up yet (webhook mode).
    if prompt_manager is None:
        await init_db()
        prompt_manager = PromptManager(PROMPTS_DIR)
        prompt_manager.start_watcher()
        router = Router(prompt_manager)
        await init_scheduler()

    logger.info("GYL3-Claw FastAPI started")
    yield

    if prompt_manager is not None:
        stop_scheduler()
        prompt_manager.stop_watcher()
        await close_db()
    logger.info("GYL3-Claw FastAPI stopped")


app = FastAPI(title="GYL3-Claw", lifespan=lifespan)


@app.get("/")
async def index():
    domains = prompt_manager.list_domains() if prompt_manager else []
    return {
        "name": "GYL3-Claw",
        "status": "running",
        "domains": [d["id"] for d in domains],
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook/test")
async def webhook_test(request: Request):
    """本地调试：模拟消息处理，同步返回结果（不调飞书 API）"""
    body = await request.json()
    text = body.get("text", "").strip()
    chat_id = body.get("chat_id", "test_chat")
    user_id = body.get("user_id", "test_user")

    if not text:
        return JSONResponse({"error": "text is required"}, status_code=400)

    route_result = await router.route(chat_id, user_id, text)
    reply = await dispatch(route_result, chat_id, user_id, prompt_manager)

    return {
        "route": {"type": route_result.type, "domain_id": route_result.domain_id},
        "reply": reply,
    }


# ─── Startup ───


def start_server(port: int | None = None, use_webhook: bool = False) -> None:
    """Main entry: long-connection (default) or webhook mode."""
    global prompt_manager, router

    from logging.handlers import TimedRotatingFileHandler

    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")

    # File handler: daily rotation, keep 30 days
    fh = TimedRotatingFileHandler(
        log_dir / "claw.log", when="midnight", backupCount=30, encoding="utf-8",
    )
    fh.setFormatter(fmt)
    fh.setLevel(logging.INFO)

    # Console handler: always output to stderr too
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    ch.setLevel(logging.INFO)

    logging.root.handlers.clear()
    logging.root.addHandler(fh)
    logging.root.addHandler(ch)
    logging.root.setLevel(logging.INFO)

    p = port or settings.server.port

    if use_webhook:
        # Webhook mode: plain FastAPI (needs public URL / ngrok)
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=p)
        return

    # ── Long-connection mode ──

    # The ws Client creates its own event loop (lark_oapi.ws.client.loop).
    # We initialise DB / prompt / scheduler on that loop so aiosqlite shares
    # the same loop that will later run our message-handling coroutines.
    from lark_oapi.ws import client as _ws_module
    ws_loop: asyncio.AbstractEventLoop = _ws_module.loop

    ws_loop.run_until_complete(init_db())
    prompt_manager = PromptManager(PROMPTS_DIR)
    prompt_manager.start_watcher()
    router = Router(prompt_manager)
    ws_loop.run_until_complete(init_scheduler())

    print("[Claw] Components initialised on ws event loop", flush=True)
    logger.info("Components initialised on ws event loop")

    # Start FastAPI in a background thread (for /health + /webhook/test)
    def _run_fastapi():
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=p, log_level="warning")

    api_thread = threading.Thread(target=_run_fastapi, daemon=True)
    api_thread.start()
    logger.info("FastAPI running on port %d (background thread)", p)

    # Build event handler
    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(_on_im_message_receive)
        .build()
    )

    # Start ws long-connection (blocks main thread)
    print("[Claw] Starting Feishu long-connection...", flush=True)
    logger.info("Starting Feishu long-connection...")
    ws_client = lark.ws.Client(
        settings.feishu.app_id,
        settings.feishu.app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.DEBUG,
    )
    ws_client.start()
