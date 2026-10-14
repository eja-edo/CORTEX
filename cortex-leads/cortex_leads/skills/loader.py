"""SKILL.md parsing, lint and DB sync (DESIGN §5.8)."""
import hashlib
import re
from pathlib import Path
from uuid import UUID

import yaml
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.core.errors import CortexError
from cortex_leads.core.vocabulary import EVENT_TYPES, OUTPUT_KINDS
from cortex_leads.db.models import Sandbox, SkillVersion
from cortex_leads.domain.pack import DomainPack, load_pack
from cortex_leads.skills.manifest import SkillManifest, parse_duration
from cortex_leads.skills.profile import AgentProfile, load_profile

MAX_TOOLS = 8
MAX_FIELDS = 15
# Conversation fields a trigger may compare (DESIGN §5.7: equality only, names not expressions).
MATCH_FIELDS = {"intent", "channel_kind", "state"}


class _Loader(yaml.SafeLoader):
    """YAML 1.1 reads the key `on` as True, which would silently break `trigger.on`."""


_Loader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:bool"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Loader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$"), list("tf"))


class SkillError(CortexError):
    """Unparseable SKILL.md, failed lint, or a mutated immutable version."""


def load_yaml(raw: str) -> object:
    """The one safe YAML entry point (keeps `on` a string); also used for domain.yaml."""
    return yaml.load(raw, Loader=_Loader)


def parse_text(raw: str) -> tuple[SkillManifest, str]:
    if not raw.startswith("---"):
        raise SkillError("SKILL.md must start with YAML frontmatter")
    _, _, rest = raw.partition("---")
    front, sep, body = rest.partition("\n---")
    if not sep:
        raise SkillError("frontmatter is not closed with ---")
    try:
        data = load_yaml(front)
        if not isinstance(data, dict):
            raise SkillError("frontmatter must be a mapping")
        return SkillManifest(**data), body.strip()
    except (yaml.YAMLError, ValidationError) as e:
        raise SkillError(f"invalid frontmatter: {e}") from e


def parse_skill_md(path: Path) -> tuple[SkillManifest, str]:
    return parse_text(path.read_text(encoding="utf-8"))


def lint(manifest: SkillManifest, profile: AgentProfile, pack: DomainPack) -> list[str]:
    errs: list[str] = []
    tools = manifest.requires_tools
    if len(tools) > MAX_TOOLS:
        errs.append(f"requires_tools has {len(tools)} tools (max {MAX_TOOLS})")
    errs += [f"tool not in profile allowlist: {t}" for t in tools if t not in profile.tool_allowlist]
    if manifest.trigger.on not in EVENT_TYPES:
        errs.append(f"trigger.on not in vocabulary: {manifest.trigger.on}")
    for key, val in manifest.trigger.match.items():
        if key.startswith("$"):
            errs.append(f"match key {key!r}: operators are not allowed (equality only)")
        elif key not in MATCH_FIELDS:
            errs.append(f"match key not allowed: {key}")
        if not isinstance(val, str | int | bool):
            errs.append(f"match value for {key!r} must be a scalar")
        elif key == "intent" and val not in pack.intents:  # DESIGN A6: intents come from the pack
            errs.append(f"match intent {val!r} is not in the domain pack")
    for what, val in (("trigger.after", manifest.trigger.after), ("limits.min_gap", manifest.limits.get("min_gap"))):
        if val is not None:
            try:
                parse_duration(val)
            except ValueError as e:
                errs.append(f"{what}: {e}")
    if manifest.output_kind not in OUTPUT_KINDS:
        errs.append(f"output_kind not allowed: {manifest.output_kind}")
    sp = manifest.send_policy  # DESIGN §5.8: auto needs both the tool and the matching output kind
    if (sp and sp.mode == "auto" or manifest.output_kind == "send_to_customer") \
            and "send_message" not in tools:
        errs.append("send_policy auto / output_kind send_to_customer requires tool send_message")
    if sp and sp.mode == "auto" and manifest.output_kind != "send_to_customer":
        errs.append("send_policy.mode auto requires output_kind send_to_customer")
    if sp and (bad := set(sp.auto_when) - {"window", "max_per_contact_per_day"}):
        errs.append(f"send_policy.auto_when keys not allowed: {sorted(bad)}")
    if sp and sp.auto_when.get("window", "free") != "free":
        errs.append("send_policy.auto_when.window may only be 'free'")
    if manifest.field_count() > MAX_FIELDS:
        errs.append(f"frontmatter has {manifest.field_count()} fields (max {MAX_FIELDS})")
    return errs


async def sync_dir(
    session: AsyncSession, tenant_id: UUID, sandbox_id: UUID, directory: Path
) -> list[SkillVersion]:
    """Load every <dir>/<name>/SKILL.md. Idempotent by checksum; a version is immutable:
    same (name, version) with a different checksum is an error, never an overwrite."""
    sandbox = await session.get(Sandbox, sandbox_id)
    if sandbox is None:
        raise SkillError(f"sandbox not found: {sandbox_id}")
    profile, pack = load_profile(sandbox.profile_ref), load_pack(sandbox)
    out: list[SkillVersion] = []
    for path in sorted(directory.glob("*/SKILL.md")):
        raw = path.read_text(encoding="utf-8")
        manifest, body = parse_text(raw)
        errs = lint(manifest, profile, pack)
        if manifest.name != path.parent.name:
            errs.append(f"name {manifest.name!r} != directory {path.parent.name!r}")
        if errs:
            raise SkillError(f"{path.parent.name}: " + "; ".join(errs))
        checksum = hashlib.sha256(raw.encode()).hexdigest()
        row = (await session.execute(select(SkillVersion).where(
            SkillVersion.sandbox_id == sandbox_id, SkillVersion.name == manifest.name,
            SkillVersion.version == manifest.version))).scalar_one_or_none()
        if row is None:
            row = SkillVersion(
                tenant_id=tenant_id, sandbox_id=sandbox_id, name=manifest.name,
                version=manifest.version, status="draft", checksum=checksum, body=body,
                manifest=manifest.model_dump(mode="json"))
            session.add(row)
        elif row.checksum != checksum:
            raise SkillError(f"{manifest.name}@{manifest.version} changed; bump the version")
        out.append(row)
    await session.flush()
    return out
