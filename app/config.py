from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


@dataclass
class FeishuConfig:
    app_id: str = ""
    app_secret: str = ""
    encrypt_key: str = ""
    verification_token: str = ""


@dataclass
class GatewayConfig:
    base_url: str = ""
    api_key: str = ""


@dataclass
class DefaultsConfig:
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 4096
    temperature: float = 0.5


@dataclass
class SessionConfig:
    max_turns: int = 20
    timeout_minutes: int = 30


@dataclass
class ServerConfig:
    port: int = 3000


@dataclass
class Settings:
    feishu: FeishuConfig = field(default_factory=FeishuConfig)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    defaults: DefaultsConfig = field(default_factory=DefaultsConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    server: ServerConfig = field(default_factory=ServerConfig)


def _load_settings() -> Settings:
    config_path = BASE_DIR / "config.yaml"
    raw: dict = {}
    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}

    feishu_raw = raw.get("feishu", {})
    gateway_raw = raw.get("gateway", {})
    defaults_raw = raw.get("defaults", {})
    session_raw = raw.get("session", {})
    server_raw = raw.get("server", {})

    s = Settings(
        feishu=FeishuConfig(
            app_id=os.getenv("FEISHU_APP_ID", feishu_raw.get("app_id", "")),
            app_secret=os.getenv("FEISHU_APP_SECRET", feishu_raw.get("app_secret", "")),
            encrypt_key=feishu_raw.get("encrypt_key", ""),
            verification_token=feishu_raw.get("verification_token", ""),
        ),
        gateway=GatewayConfig(
            base_url=os.getenv("AI_BASE_URL", gateway_raw.get("base_url", "")),
            api_key=os.getenv("AI_API_KEY", gateway_raw.get("api_key", "")),
        ),
        defaults=DefaultsConfig(
            model=os.getenv("AI_MODEL") or defaults_raw.get("model") or "claude-sonnet-4-20250514",
            max_tokens=int(defaults_raw.get("max_tokens", 4096)),
            temperature=float(defaults_raw.get("temperature", 0.5)),
        ),
        session=SessionConfig(
            max_turns=int(session_raw.get("max_turns", 20)),
            timeout_minutes=int(session_raw.get("timeout_minutes", 30)),
        ),
        server=ServerConfig(
            port=int(server_raw.get("port", 3000)),
        ),
    )
    return s


settings = _load_settings()
