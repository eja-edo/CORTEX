"""Console API (WP27): the JSON the main UI (`web/`) speaks. Mounted at /api/v1. Every handler gets tenant, role and
actor from the session (A3), never from the body, and calls the same service functions the rest of the system uses:
there is no second way to approve a draft, move a skill or pause a sandbox."""
from fastapi import APIRouter

from cortex_leads.console import (
    assistant,
    audit,
    classes,
    customer_data,
    google,
    grading,
    inbox,
    lessons,
    onboarding,
    recovery,
    sandboxes,
    session,
    settings,
    skills,
    sources,
    team,
    tools,
)

router = APIRouter()
for part in (session, inbox, skills, sandboxes, assistant, audit, sources, team, tools, lessons, grading, google, classes, settings, recovery, customer_data, onboarding):
    router.include_router(part.router)
