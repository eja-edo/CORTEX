from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class CustomerPrincipal:
    contact_id: UUID


@dataclass(frozen=True)
class StaffPrincipal:
    staff_ref: str


@dataclass(frozen=True)
class SystemPrincipal:
    job: str


Principal = CustomerPrincipal | StaffPrincipal | SystemPrincipal


@dataclass(frozen=True)
class Scope:
    conversation_id: UUID | None = None
    job_id: UUID | None = None


@dataclass(frozen=True)
class RunContext:
    """Filled by the server only, never from request bodies or LLM args (DESIGN A3)."""

    run_id: UUID
    tenant_id: UUID
    sandbox_id: UUID
    profile: str
    profile_version: int
    principal: Principal
    scope: Scope
    trigger_event_id: str | None = None

    @property
    def actor(self) -> str:
        p = self.principal
        if isinstance(p, StaffPrincipal):
            return f"staff:{p.staff_ref}"
        if isinstance(p, SystemPrincipal):
            return f"system:{p.job}"
        return f"ai:{self.profile}@{self.profile_version}"
