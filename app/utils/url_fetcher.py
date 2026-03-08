"""URL content fetcher and summarizer."""
from __future__ import annotations

import logging
import re
from typing import Optional

import aiohttp

from app.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 30
_MAX_CONTENT_LENGTH = 50000  # 截取前 50k 字符送给 AI


async def fetch_url(url: str, timeout: int = _TIMEOUT) -> tuple[bool, str]:
    """Fetch URL content and convert to text.

    Returns (success, content_or_error).
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    try:
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.get(url, headers=headers, allow_redirects=True) as resp:
                resp.raise_for_status()
                content_type = resp.headers.get("Content-Type", "")
                if "text" not in content_type and "json" not in content_type and "xml" not in content_type:
                    return False, f"不支持的内容类型: {content_type}"
                raw = await resp.text(errors="replace")
    except aiohttp.ClientError as e:
        logger.error("Fetch URL failed: %s", e)
        return False, f"请求失败: {e}"
    except Exception as e:
        logger.error("Fetch URL error: %s", e)
        return False, f"获取页面出错: {e}"

    # Extract main content from HTML
    text = _html_to_text(raw)
    if not text.strip():
        return False, "页面内容为空"
    return True, text


def _html_to_text(html: str) -> str:
    """Extract main content from HTML using trafilatura, with regex fallback."""
    try:
        import trafilatura
        text = trafilatura.extract(html, include_links=False, include_tables=True)
        if text and len(text) > 50:
            return text
    except Exception:
        logger.debug("trafilatura extraction failed, falling back to regex")

    return _html_to_text_regex(html)


def _html_to_text_regex(html: str) -> str:
    """Regex-based HTML to text fallback."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"<(?:br|p|div|h[1-6]|li|tr)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


async def summarize_url(url: str, prompt_manager) -> str:
    """Fetch a URL, then use AI to summarize its content.

    Uses the 'url_reader' prompt from PromptManager for system message,
    model, temperature, and max_tokens configuration.
    """
    ok, content = await fetch_url(url)
    if not ok:
        return f"无法获取页面内容: {content}"

    # Truncate for AI
    if len(content) > _MAX_CONTENT_LENGTH:
        content = content[:_MAX_CONTENT_LENGTH] + "\n\n[内容已截断...]"

    # Load prompt config
    prompt_config = prompt_manager.get_prompt("url_reader") if prompt_manager else None
    if prompt_config:
        system_msg = prompt_manager.build_system_message("url_reader")
        model = prompt_config.model.name or settings.defaults.model
        temperature = prompt_config.model.temperature if prompt_config.model.temperature is not None else 0.3
        max_tokens = prompt_config.model.max_tokens or 2048
    else:
        system_msg = "你是一个网页内容总结助手。请输出结构化的中文摘要。"
        model = settings.defaults.model
        temperature = 0.3
        max_tokens = 2048

    from app.executor.chat import _get_client
    client = _get_client()

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": f"请总结以下网页内容（来源: {url}）：\n\n{content}"},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        summary = resp.choices[0].message.content or ""
        return f"**网页摘要** — {url}\n\n{summary}"
    except Exception:
        logger.exception("AI summarize failed")
        return "AI 总结服务暂时不可用，请稍后重试。"


def is_url(text: str) -> Optional[str]:
    """Check if text is (or contains only) a URL. Returns the URL or None."""
    # Strip whitespace and common invisible chars (zero-width spaces etc.)
    text = text.strip().strip("\u200b\u200c\u200d\ufeff")
    if re.match(r"^https?://\S+$", text):
        return text
    return None
