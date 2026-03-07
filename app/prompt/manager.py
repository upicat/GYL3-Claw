from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

import yaml
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent, FileDeletedEvent
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


@dataclass
class ModelConfig:
    name: str = ""
    temperature: float | None = None
    max_tokens: int | None = None


@dataclass
class PromptConfig:
    id: str = ""
    name: str = ""
    description: str = ""
    version: str = ""
    commands: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    model: ModelConfig = field(default_factory=ModelConfig)
    system: list[dict[str, str]] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)


def _parse_prompt_file(path: Path) -> PromptConfig | None:
    try:
        with open(path) as f:
            raw = yaml.safe_load(f)
        if not raw or not isinstance(raw, dict):
            return None
        model_raw = raw.get("model", {}) or {}
        return PromptConfig(
            id=raw.get("id", path.stem),
            name=raw.get("name", ""),
            description=raw.get("description", ""),
            version=raw.get("version", ""),
            commands=raw.get("commands", []),
            keywords=raw.get("keywords", []),
            model=ModelConfig(
                name=model_raw.get("name", ""),
                temperature=model_raw.get("temperature"),
                max_tokens=model_raw.get("max_tokens"),
            ),
            system=raw.get("system", []),
            tools=raw.get("tools", []),
        )
    except Exception:
        logger.exception("Failed to parse prompt file: %s", path)
        return None


class _ReloadHandler(FileSystemEventHandler):
    def __init__(self, manager: PromptManager):
        self._manager = manager

    def on_modified(self, event: FileModifiedEvent):  # type: ignore[override]
        if isinstance(event.src_path, str) and event.src_path.endswith(".yaml"):
            logger.info("Prompt file changed: %s, reloading...", event.src_path)
            self._manager.reload()

    def on_created(self, event: FileCreatedEvent):  # type: ignore[override]
        if isinstance(event.src_path, str) and event.src_path.endswith(".yaml"):
            logger.info("Prompt file created: %s, reloading...", event.src_path)
            self._manager.reload()

    def on_deleted(self, event: FileDeletedEvent):  # type: ignore[override]
        if isinstance(event.src_path, str) and event.src_path.endswith(".yaml"):
            logger.info("Prompt file deleted: %s, reloading...", event.src_path)
            self._manager.reload()


class PromptManager:
    def __init__(self, prompt_dir: str | Path):
        self._prompt_dir = Path(prompt_dir)
        self._prompts: dict[str, PromptConfig] = {}
        self._router_raw: dict | None = None
        self._lock = Lock()
        self._observer: Observer | None = None
        self.reload()

    def reload(self) -> None:
        prompts: dict[str, PromptConfig] = {}
        router_raw: dict | None = None
        for path in self._prompt_dir.glob("*.yaml"):
            if path.stem == "_router":
                with open(path) as f:
                    router_raw = yaml.safe_load(f)
                continue
            cfg = _parse_prompt_file(path)
            if cfg:
                prompts[cfg.id] = cfg
        with self._lock:
            self._prompts = prompts
            self._router_raw = router_raw
        logger.info("Loaded %d prompt domains: %s", len(prompts), list(prompts.keys()))

    def start_watcher(self) -> None:
        if self._observer is not None:
            return
        self._observer = Observer()
        self._observer.schedule(_ReloadHandler(self), str(self._prompt_dir), recursive=False)
        self._observer.daemon = True
        self._observer.start()
        logger.info("Watching prompt dir: %s", self._prompt_dir)

    def stop_watcher(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=3)
            self._observer = None

    def get_prompt(self, domain_id: str) -> PromptConfig | None:
        with self._lock:
            return self._prompts.get(domain_id)

    def build_system_message(self, domain_id: str) -> str:
        cfg = self.get_prompt(domain_id)
        if not cfg:
            return ""
        parts: list[str] = []
        for block in cfg.system:
            for key, value in block.items():
                parts.append(f"## {key.upper()}\n{value.strip()}")
        return "\n\n".join(parts)

    def get_domain_list(self) -> str:
        with self._lock:
            prompts = dict(self._prompts)
        lines: list[str] = []
        for pid, cfg in sorted(prompts.items()):
            lines.append(f"- {pid}: {cfg.name} — {cfg.description}")
        return "\n".join(lines)

    def list_domains(self) -> list[dict]:
        with self._lock:
            prompts = dict(self._prompts)
        result = []
        for pid, cfg in sorted(prompts.items()):
            result.append({
                "id": pid,
                "name": cfg.name,
                "description": cfg.description,
                "version": cfg.version,
                "commands": cfg.commands,
            })
        return result

    def get_router_prompt(self) -> str:
        with self._lock:
            raw = self._router_raw
        if not raw:
            return ""
        system_parts: list[str] = []
        for block in raw.get("system", []):
            for key, value in block.items():
                system_parts.append(value.strip())
        text = "\n\n".join(system_parts)
        return text.replace("{{domain_list}}", self.get_domain_list())

    def get_router_model(self) -> ModelConfig:
        with self._lock:
            raw = self._router_raw
        if not raw:
            return ModelConfig()
        model_raw = raw.get("model", {}) or {}
        return ModelConfig(
            name=model_raw.get("name", ""),
            temperature=model_raw.get("temperature"),
            max_tokens=model_raw.get("max_tokens"),
        )

    def create_prompt(
        self,
        domain_id: str,
        name: str,
        description: str,
        role: str,
        keywords: list[str] | None = None,
    ) -> str | None:
        """Create a new prompt YAML file. Returns None on success, error message on failure."""
        path = self._prompt_dir / f"{domain_id}.yaml"
        if path.exists():
            return f"场景 '{domain_id}' 已存在，请换一个 id"

        data = {
            "id": domain_id,
            "name": name,
            "description": description,
            "version": "1.0",
            "commands": [f"/{domain_id}"],
            "keywords": keywords or [],
            "model": {"name": "", "temperature": 0.5},
            "system": [{"role": role}],
        }
        try:
            with open(path, "w") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            self.reload()
            return None
        except Exception:
            logger.exception("Failed to create prompt: %s", domain_id)
            return "创建 prompt 文件失败"

    def delete_prompt(self, domain_id: str) -> str | None:
        """Delete a prompt YAML file. Returns None on success, error message on failure."""
        if domain_id in ("general", "_router"):
            return f"不能删除内置场景 '{domain_id}'"
        path = self._prompt_dir / f"{domain_id}.yaml"
        if not path.exists():
            return f"场景 '{domain_id}' 不存在"
        try:
            path.unlink()
            self.reload()
            return None
        except Exception:
            logger.exception("Failed to delete prompt: %s", domain_id)
            return "删除 prompt 文件失败"

    @property
    def all_prompts(self) -> dict[str, PromptConfig]:
        with self._lock:
            return dict(self._prompts)
