"""Static catalogue of models the chat UI can switch between.

Kept as code rather than a DB table: adding a model always requires a
deploy anyway (matching provider/base_url config), so a reviewable list
here is simpler than an admin UI. The `tier` field is a placeholder gate
for future account-plan-based access (free/pro/premium) — there is no
subscription system yet, so it is currently unused by any access check.

**The first entry is the default**: `ModelClient` runs a request on the
model it was asked for, or on this one when it was asked for nothing (or
for something not listed). Order therefore matters here in a way it did
not while the client rotated through the list.

Per-model rate limits used to live here too, feeding a local budget that
skipped a model before calling it. That went with the rotation it
existed to serve — the numbers were a guess about someone else's quota,
and enforcing a guess meant refusing requests the provider would have
served. Rate limiting is the LLM service's to report, and a 429 from it
is surfaced rather than predicted.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import settings


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    tier: str = "free"  # "free" | "pro" | "premium" — reserved, not enforced yet
    enabled: bool = True


# Ids verified against the configured OPENAI_BASE_URL proxy's live
# /v1/models roster (2026-08-13) — the previous "models/gemma-4-*-it"
# placeholders didn't match anything the proxy actually serves.
MODEL_CATALOG: list[ModelSpec] = [
    ModelSpec(
        id=settings.OPENAI_DEFAULT_MODEL,
        label="Auto (default)",
        tier="free",
    ),
    ModelSpec(
        id="gemini/gemma-4-31b-it",
        label="Gemma 4 31B",
        tier="free",
    ),
    ModelSpec(
        id="openrouter/google/gemma-4-26b-a4b-it:free",
        label="Gemma 4 26B",
        tier="free",
    ),
]

_CATALOG_BY_ID: dict[str, ModelSpec] = {m.id: m for m in MODEL_CATALOG}


def enabled_models() -> list[ModelSpec]:
    return [m for m in MODEL_CATALOG if m.enabled]


def enabled_model_ids() -> list[str]:
    return [m.id for m in enabled_models()]


def get_model_spec(model_id: str) -> ModelSpec | None:
    return _CATALOG_BY_ID.get(model_id)
