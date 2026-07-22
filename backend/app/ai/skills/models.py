"""Skill data models for the progressive skill loading system."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SkillMetadata:
    """Lightweight skill metadata — loaded during scan, no prompt content."""

    name: str
    description: str
    tools: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)


@dataclass
class Skill:
    """Full skill with prompt content and resources — lazy-loaded."""

    metadata: SkillMetadata
    prompt: str
    resources: dict[str, str] = field(default_factory=dict)
    base_path: Optional[Path] = None
