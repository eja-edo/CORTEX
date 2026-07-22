"""SkillRegistry — scans skills/ for SKILL.md, provides progressive loading.

Design (following Claude Code progressive disclosure pattern):
  - scan() loads only lightweight metadata (name, description, tools)
  - load() loads full prompt content + resources — only when needed
  - All skills live under backend/app/ai/skills/<name>/SKILL.md
"""

import re
from pathlib import Path
from typing import Optional

from app.utils.logger import get_logger
from app.ai.skills.models import SkillMetadata, Skill

logger = get_logger(__name__)

_SKILLS_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Frontmatter parser (simple YAML-like subset — no PyYAML dependency)
# ---------------------------------------------------------------------------

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


def _parse_frontmatter(text: str) -> dict:
    """Parse YAML-like frontmatter between --- markers.

    Supports:
      key: value
      key: |           (multi-line block — indented text until next key)
      key:
        - item1       (list items)
        - item2
    """
    m = _FM_RE.match(text)
    if not m:
        return {}

    fields: dict = {}
    current_key = None
    current_lines: list[str] = []
    in_block = False

    for raw_line in m.group(1).split("\n"):
        line = raw_line.rstrip()

        # A key at column 0 starts a new field — always flush current
        is_new_key = re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*:", line)
        if is_new_key:
            if current_key is not None:
                fields[current_key] = _finalise_value(current_lines)
            current_key, _, rest = line.partition(":")
            current_key = current_key.strip()
            rest = rest.strip()
            current_lines = []
            in_block = rest == "|"
            if not in_block and rest:
                current_lines = [rest]
            continue

        if current_key is None:
            continue

        if in_block:
            # Block content: only indented lines belong to the block
            if line.startswith(" "):
                current_lines.append(line.strip())
            # non-indented lines (blank or comments) are ignored inside block
        else:
            # Non-block: list items or continuation
            if line.strip().startswith("- "):
                current_lines.append(line.strip())
            elif line.strip() and not line.strip().startswith("#"):
                current_lines.append(line.strip())

    if current_key is not None:
        fields[current_key] = _finalise_value(current_lines)

    return fields


def _finalise_value(lines: list[str]) -> str | list[str]:
    """Coerce parsed lines into a string or list of strings."""
    stripped = [l for l in lines if l]
    if not stripped:
        return ""

    # YAML block list:  - item
    if all(l.startswith("- ") for l in stripped if l.strip()):
        return [re.sub(r"^- \s*", "", l).strip() for l in stripped]

    return "\n".join(stripped).strip()


def _extract_content(text: str) -> str:
    """Return everything after the frontmatter block."""
    m = _FM_RE.match(text)
    if m:
        return text[m.end():].strip()
    return text.strip()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class SkillRegistry:
    """Scans and loads skills with progressive disclosure."""

    def __init__(self, skills_dir: Optional[Path] = None) -> None:
        self._skills_dir = skills_dir or _SKILLS_DIR
        self._metadata: dict[str, SkillMetadata] = {}
        self._loaded: dict[str, Skill] = {}

    # -- discovery ----------------------------------------------------------

    def scan(self) -> list[SkillMetadata]:
        """Scan <skills_dir>/<name>/SKILL.md and load only metadata."""
        self._metadata = {}
        for child in sorted(self._skills_dir.iterdir()):
            if not child.is_dir() or child.name.startswith("_"):
                continue
            skill_file = child / "SKILL.md"
            if not skill_file.exists():
                logger.debug("SkillRegistry: %s has no SKILL.md, skipping", child.name)
                continue
            meta = self._parse_skill_metadata(skill_file)
            if meta is not None:
                self._metadata[meta.name] = meta
                logger.info("SkillRegistry: registered skill '%s' | desc: %s…", meta.name, meta.description[:60])
        return list(self._metadata.values())

    def list_metadata(self) -> list[SkillMetadata]:
        """Return all registered skill metadata (lightweight, always available)."""
        return list(self._metadata.values())

    def get_metadata(self, name: str) -> Optional[SkillMetadata]:
        return self._metadata.get(name)

    # -- loading (lazy) -----------------------------------------------------

    def is_loaded(self, name: str) -> bool:
        return name in self._loaded

    def load(self, name: str) -> Optional[Skill]:
        """Lazy-load a single skill (prompt content + resources)."""
        if name in self._loaded:
            return self._loaded[name]

        meta = self._metadata.get(name)
        if meta is None:
            logger.warning("SkillRegistry: '%s' not found in metadata (call scan() first?)", name)
            return None

        skill_dir = self._skills_dir / name
        skill_file = skill_dir / "SKILL.md"

        if not skill_file.exists():
            logger.warning("SkillRegistry: SKILL.md missing for '%s'", name)
            return None

        prompt = _extract_content(skill_file.read_text(encoding="utf-8"))

        resources: dict[str, str] = {}
        for f in skill_dir.iterdir():
            if f.name in ("SKILL.md", ".DS_Store") or not f.is_file():
                continue
            resources[f.name] = f.read_text(encoding="utf-8")

        skill = Skill(metadata=meta, prompt=prompt, resources=resources, base_path=skill_dir)
        self._loaded[name] = skill
        logger.info("SkillRegistry: loaded '%s' (%d chars, %d resources)", name, len(prompt), len(resources))
        return skill

    def load_all(self, names: list[str]) -> list[Skill]:
        """Batch lazy-load skills."""
        return [s for n in names if (s := self.load(n)) is not None]

    def unload(self, name: str) -> None:
        self._loaded.pop(name, None)
        logger.debug("SkillRegistry: unloaded '%s'", name)

    # -- internals ----------------------------------------------------------

    def _parse_skill_metadata(self, path: Path) -> Optional[SkillMetadata]:
        text = path.read_text(encoding="utf-8")
        fields = _parse_frontmatter(text)

        name = fields.get("name")
        description = fields.get("description")
        if not name or not description:
            logger.warning("SkillRegistry: %s missing name or description in frontmatter", path)
            return None

        return SkillMetadata(
            name=str(name),
            description=str(description),
            tools=[str(t) for t in (fields.get("tools") or [])],
            dependencies=[str(d) for d in (fields.get("dependencies") or [])],
        )


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_registry: Optional[SkillRegistry] = None


def get_skill_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
        _registry.scan()
    return _registry


def reset_skill_registry() -> None:
    """Reset singleton (for testing)."""
    global _registry
    _registry = None
