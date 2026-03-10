"""SkillLoader — scan skills/ directory, parse SKILL.md frontmatter, lazy-load full content."""
from __future__ import annotations

import logging
from pathlib import Path
from threading import Lock

import yaml
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent, FileDeletedEvent
from watchdog.observers import Observer

from app.agent.models import SkillMeta, SkillFull
from app.tools.registry import resolve_tool_references

logger = logging.getLogger(__name__)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split SKILL.md into YAML frontmatter dict and markdown body."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("---", 3)
    if end == -1:
        return {}, text
    fm_str = text[3:end].strip()
    body = text[end + 3:].strip()
    try:
        fm = yaml.safe_load(fm_str) or {}
    except yaml.YAMLError:
        logger.warning("Invalid YAML frontmatter, treating as plain markdown")
        fm = {}
    return fm, body


def _parse_skill_meta(skill_dir: Path) -> SkillMeta | None:
    """Parse SKILL.md frontmatter only (lightweight)."""
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        return None
    try:
        text = skill_file.read_text(encoding="utf-8")
    except Exception:
        logger.exception("Failed to read %s", skill_file)
        return None
    fm, _ = _parse_frontmatter(text)
    if not fm.get("name"):
        return None
    model_raw = fm.get("model") or {}
    return SkillMeta(
        name=fm["name"],
        description=fm.get("description", ""),
        tool_names=fm.get("tools") or [],
        commands=fm.get("commands") or [],
        model_overrides=model_raw if isinstance(model_raw, dict) else {},
        dir_path=skill_dir,
    )


class _SkillReloadHandler(FileSystemEventHandler):
    def __init__(self, loader: SkillLoader):
        self._loader = loader

    def _handle(self, event):
        src = getattr(event, "src_path", "")
        if isinstance(src, str) and src.endswith(".md"):
            logger.info("Skill file changed: %s, reloading...", src)
            self._loader.reload()

    def on_modified(self, event: FileModifiedEvent):  # type: ignore[override]
        self._handle(event)

    def on_created(self, event: FileCreatedEvent):  # type: ignore[override]
        self._handle(event)

    def on_deleted(self, event: FileDeletedEvent):  # type: ignore[override]
        self._handle(event)


class SkillLoader:
    """Manages skill discovery, metadata caching, and on-demand full loading."""

    def __init__(self, skills_dir: str | Path):
        self._skills_dir = Path(skills_dir)
        self._metas: dict[str, SkillMeta] = {}  # name -> SkillMeta
        self._cmd_map: dict[str, str] = {}       # "/web" -> "web-search"
        self._lock = Lock()
        self._observer: Observer | None = None
        self.reload()

    def reload(self) -> None:
        """Scan skills/ subdirectories, parse frontmatter only."""
        import app.tools  # noqa: F401 — trigger tool registration

        metas: dict[str, SkillMeta] = {}
        cmd_map: dict[str, str] = {}

        if not self._skills_dir.exists():
            logger.warning("Skills directory not found: %s", self._skills_dir)
            with self._lock:
                self._metas = metas
                self._cmd_map = cmd_map
            return

        for child in sorted(self._skills_dir.iterdir()):
            if not child.is_dir():
                continue
            meta = _parse_skill_meta(child)
            if meta:
                metas[meta.name] = meta
                for cmd in meta.commands:
                    cmd_map[cmd] = meta.name

        with self._lock:
            self._metas = metas
            self._cmd_map = cmd_map

        logger.info(
            "Loaded %d skills: %s", len(metas), list(metas.keys())
        )

    def load_full(self, name: str) -> SkillFull | None:
        """Load complete skill content (instructions + references + resolved tools)."""
        with self._lock:
            meta = self._metas.get(name)
        if not meta:
            return None

        skill_file = meta.dir_path / "SKILL.md"
        try:
            text = skill_file.read_text(encoding="utf-8")
        except Exception:
            logger.exception("Failed to read %s", skill_file)
            return None

        _, body = _parse_frontmatter(text)

        # Load references/*.md
        refs_dir = meta.dir_path / "references"
        ref_parts: list[str] = []
        if refs_dir.is_dir():
            for ref_file in sorted(refs_dir.glob("*.md")):
                try:
                    ref_parts.append(ref_file.read_text(encoding="utf-8"))
                except Exception:
                    logger.warning("Failed to read reference: %s", ref_file)

        # Resolve tool names to full OpenAI schemas
        tools = resolve_tool_references(meta.tool_names) if meta.tool_names else []

        return SkillFull(
            meta=meta,
            instructions=body,
            references="\n\n---\n\n".join(ref_parts),
            tools=tools,
        )

    def resolve_command(self, cmd: str) -> str | None:
        """Map a slash command to skill name. Returns None if not found."""
        with self._lock:
            return self._cmd_map.get(cmd)

    def get_all_tools(self) -> list[dict]:
        """Collect all tools declared across all skills (deduplicated)."""
        seen: set[str] = set()
        tools: list[dict] = []
        with self._lock:
            all_tool_names = []
            for meta in self._metas.values():
                for tn in meta.tool_names:
                    if tn not in seen:
                        seen.add(tn)
                        all_tool_names.append(tn)
        return resolve_tool_references(all_tool_names)

    def get_skills_summary(self) -> str:
        """Generate a summary of all skills for the Agent system prompt."""
        with self._lock:
            metas = list(self._metas.values())
        if not metas:
            return ""
        lines = ["# 可用技能\n"]
        for m in metas:
            cmds = " ".join(m.commands) if m.commands else ""
            line = f"- **{m.name}**: {m.description}"
            if cmds:
                line += f"  (命令: {cmds})"
            lines.append(line)
        return "\n".join(lines)

    def get_agent_persona(self) -> str:
        """Read skills/_agent.md as the base agent persona."""
        agent_file = self._skills_dir / "_agent.md"
        if agent_file.exists():
            try:
                return agent_file.read_text(encoding="utf-8").strip()
            except Exception:
                logger.warning("Failed to read _agent.md")
        return ""

    @property
    def all_metas(self) -> dict[str, SkillMeta]:
        with self._lock:
            return dict(self._metas)

    def start_watcher(self) -> None:
        if self._observer is not None:
            return
        self._observer = Observer()
        self._observer.schedule(
            _SkillReloadHandler(self), str(self._skills_dir), recursive=True
        )
        self._observer.daemon = True
        self._observer.start()
        logger.info("Watching skills dir: %s", self._skills_dir)

    def stop_watcher(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=3)
            self._observer = None
