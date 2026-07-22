"""Skills subsystem — progressive loading of skill instructions and resources.

Design (Claude Code-inspired):
  - Always loaded: SkillMetadata (name, description, tools)
  - Lazy loaded: Skill (prompt content + resources)
  - Selective: SkillRetriever chooses what to load based on user intent
"""

from app.ai.skills.models import SkillMetadata, Skill
from app.ai.skills.registry import (
    SkillRegistry,
    get_skill_registry,
    reset_skill_registry,
)
from app.ai.skills.retriever import (
    SkillRetriever,
    get_skill_retriever,
    reset_skill_retriever,
)

__all__ = [
    "SkillMetadata",
    "Skill",
    "SkillRegistry",
    "get_skill_registry",
    "reset_skill_registry",
    "SkillRetriever",
    "get_skill_retriever",
    "reset_skill_retriever",
]
