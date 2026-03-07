from __future__ import annotations

from app.prompt.manager import PromptConfig


def match_by_command(
    message: str, prompts: dict[str, PromptConfig]
) -> tuple[str, str] | None:
    """Match by command prefix. Returns (domain_id, remaining_message) or None."""
    text = message.strip()
    for domain_id, cfg in prompts.items():
        for cmd in cfg.commands:
            if text.startswith(cmd + " "):
                remaining = text[len(cmd):].strip()
                return domain_id, remaining
            if text == cmd:
                return domain_id, ""
    return None


def match_by_keyword(
    message: str, prompts: dict[str, PromptConfig]
) -> str | None:
    """Match by keyword presence. Returns domain_id or None."""
    text = message.lower()
    best_id: str | None = None
    best_count = 0
    for domain_id, cfg in prompts.items():
        if not cfg.keywords:
            continue
        count = sum(1 for kw in cfg.keywords if kw.lower() in text)
        if count > best_count:
            best_count = count
            best_id = domain_id
    return best_id
