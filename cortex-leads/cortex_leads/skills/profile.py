"""Agent profile (DESIGN §5.5), loaded from sandboxes/*/profiles/<id>.yaml."""
from pathlib import Path

import yaml
from pydantic import BaseModel

from cortex_leads.core.errors import CortexError

SANDBOXES_DIR = Path(__file__).resolve().parents[2] / "sandboxes"


class AgentProfile(BaseModel):
    id: str
    version: int
    audience: str
    input_trust: str
    context_sources: list[str]
    tool_allowlist: list[str]
    effect_ceiling: str
    memory_scope: str
    output_schema: str
    model: str
    max_tool_calls: int
    timeout_s: int
    token_budget: int


def load_profile(ref: str, root: Path = SANDBOXES_DIR) -> AgentProfile:
    """`ref` looks like `customer_drafter@1`."""
    name, _, ver = ref.partition("@")
    for path in sorted(root.glob(f"*/profiles/{name}.yaml")):
        profile = AgentProfile(**yaml.safe_load(path.read_text(encoding="utf-8")))
        if not ver or profile.version == int(ver):
            return profile
    raise CortexError(f"profile not found: {ref}")
