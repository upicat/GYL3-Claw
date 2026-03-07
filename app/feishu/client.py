from __future__ import annotations

import lark_oapi as lark

from app.config import settings

_client: lark.Client | None = None


def get_feishu_client() -> lark.Client:
    global _client
    if _client is None:
        _client = (
            lark.Client.builder()
            .app_id(settings.feishu.app_id)
            .app_secret(settings.feishu.app_secret)
            .log_level(lark.LogLevel.WARNING)
            .build()
        )
    return _client
