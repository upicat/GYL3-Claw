"""Data models for Skill system."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SkillMeta:
    """Lightweight metadata parsed from SKILL.md frontmatter.

    Loaded eagerly at startup for all skills.
    """
    name: str               # e.g. "web-search"
    description: str        # one-line summary (shown to Agent)
    tool_names: list[str] = field(default_factory=list)   # e.g. ["web_search"]
    commands: list[str] = field(default_factory=list)      # e.g. ["/web"]
    model_overrides: dict = field(default_factory=dict)    # e.g. {"temperature": 0.3}
    dir_path: Path = field(default_factory=Path)


@dataclass
class SkillFull:
    """Fully loaded skill: meta + instructions + resolved tools.

    Loaded on demand when a skill is activated.
    """
    meta: SkillMeta
    instructions: str       # SKILL.md markdown body (after frontmatter)
    references: str         # concatenated references/*.md content
    tools: list[dict] = field(default_factory=list)  # resolved OpenAI tool schemas
