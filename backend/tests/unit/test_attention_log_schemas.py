"""Unit tests for Milestone 2.9 — Attention Log.

Guards the decisions that are cheap now and expensive later:
  - the four enums, at exactly the agreed values (telegram/email declared
    ahead of Phase 5 so turning them on isn't an ALTER TYPE on live history);
  - the 10 columns, `item_id` polymorphic and therefore FK-free;
  - the dedup index, in the exact column order M1 specifies;
  - the dedup window read from config, never hardcoded.
"""

import ast
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.config import settings
from app.models import (
    AttentionChannel,
    AttentionItemType,
    AttentionLevel,
    AttentionLog,
    AttentionResponse,
)
from app.schemas import (
    AttentionLogResponse,
    AttentionResponseUpdate,
    AttentionSurfaceCreate,
    AttentionSurfaceResult,
)
from app.services.attention_log import AttentionLogService

BACKEND_ROOT = Path(__file__).resolve().parents[2]


# ============================================================================
# Enums
# ============================================================================

def test_item_type_values():
    # `user` was added in A1 for `day.review` — a per-user, not per-item,
    # digest (see AttentionItemType's docstring).
    assert {v.value for v in AttentionItemType} == {"task", "commitment", "schedule", "user"}


def test_level_values_are_the_five_intervention_levels():
    assert [v.value for v in AttentionLevel] == [
        "silent", "inform", "recommend", "ask", "act"
    ]


def test_channel_declares_future_channels_up_front():
    """Only `in_app` has an adapter today (app/services/delivery/); the rest
    are declared ahead of theirs.

    The original reasoning here — "so enabling one later is a code change,
    not a migration" — was half right: adding an enum *value* to PostgreSQL
    is itself a migration, so declaring them early saves one migration per
    channel rather than avoiding migrations altogether. What it does buy is
    real: `user_channels` and `notification_deliveries` both reference this
    type, and the delivery roadmap (web push → chat bot → email) is already
    known, so the values landed in one migration instead of three.

    A value with no adapter is a defined state, not a half-finished one —
    the dispatcher records `skipped/no_adapter` and the settings API
    refuses to register it (`registry.is_registerable`)."""
    assert {v.value for v in AttentionChannel} == {
        "in_app", "push", "telegram", "email", "slack", "mezon", "webhook",
    }


def test_response_values():
    assert {v.value for v in AttentionResponse} == {
        "accepted", "dismissed", "ignored", "no_response"
    }


# ============================================================================
# Table shape
# ============================================================================

def test_attention_log_has_exactly_the_ten_agreed_columns():
    assert {c.name for c in AttentionLog.__table__.columns} == {
        "id",
        "user_id",
        "item_type",
        "item_id",
        "reason_key",
        "surfaced_at",
        "level",
        "channel",
        "response",
        "responded_at",
    }


def test_item_id_has_no_foreign_key():
    """It points at tasks/commitments/schedules depending on
    item_type — polymorphic, so no single FK is possible. It also has to
    outlive its target: that Cortex nagged about something stays true after
    the something is deleted."""
    assert AttentionLog.__table__.columns["item_id"].foreign_keys == set()


def test_only_user_id_is_a_foreign_key():
    fk_columns = {fk.parent.name for fk in AttentionLog.__table__.foreign_keys}
    assert fk_columns == {"user_id"}


def test_dedup_index_exists_in_lookup_column_order():
    """M1 specifies (user_id, item_id, reason_key, surfaced_at) — order
    matters, it's what makes the dedup predicate an index scan."""
    index_columns = {tuple(c.name for c in idx.columns) for idx in AttentionLog.__table__.indexes}
    assert ("user_id", "item_id", "reason_key", "surfaced_at") in index_columns


def test_response_and_channel_are_not_nullable():
    """`no_response` is a value, not a NULL — "hasn't answered yet" is a
    state we assert, not an absence we infer."""
    assert AttentionLog.__table__.columns["response"].nullable is False
    assert AttentionLog.__table__.columns["channel"].nullable is False
    assert AttentionLog.__table__.columns["responded_at"].nullable is True


# ============================================================================
# Dedup window comes from config
# ============================================================================

def test_dedup_window_defaults_to_the_configured_24_hours():
    assert settings.ATTENTION_DEDUP_WINDOW_HOURS == 24
    service = AttentionLogService(session=None)
    assert service.dedup_window_hours == 24
    assert service.dedup_window == timedelta(hours=24)


def test_dedup_window_is_overridable_per_instance():
    assert AttentionLogService(session=None, dedup_window_hours=1).dedup_window == timedelta(hours=1)


def test_dedup_window_is_not_hardcoded_in_the_service():
    """The number 24 must not appear as a literal in the dedup path — it's a
    starting guess that 6.9 will argue with, so it has to be tunable without
    a deploy."""
    source = (BACKEND_ROOT / "app" / "services" / "attention_log.py").read_text()
    tree = ast.parse(source)

    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))

    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
        and id(node) not in docstrings
    ]
    assert 24 not in literals, "dedup window hardcoded — it must come from settings"
    assert "ATTENTION_DEDUP_WINDOW_HOURS" in source


# ============================================================================
# API schemas
# ============================================================================

def test_surface_create_accepts_silent():
    """Not an edge case: a decision not to speak is the point of this table."""
    payload = AttentionSurfaceCreate(
        item_type=AttentionItemType.TASK,
        item_id=uuid4(),
        reason_key="task.overdue",
        level=AttentionLevel.SILENT,
    )
    assert payload.level is AttentionLevel.SILENT
    assert payload.channel is AttentionChannel.IN_APP  # default


def test_surface_create_requires_reason_key():
    with pytest.raises(ValidationError):
        AttentionSurfaceCreate(
            item_type=AttentionItemType.TASK, item_id=uuid4(), level=AttentionLevel.INFORM
        )


def test_surface_create_rejects_blank_reason_key():
    with pytest.raises(ValidationError):
        AttentionSurfaceCreate(
            item_type=AttentionItemType.TASK,
            item_id=uuid4(),
            reason_key="   ",
            level=AttentionLevel.INFORM,
        )


def test_surface_create_rejects_unknown_level():
    with pytest.raises(ValidationError):
        AttentionSurfaceCreate(
            item_type=AttentionItemType.TASK,
            item_id=uuid4(),
            reason_key="task.overdue",
            level="shout",
        )


@pytest.mark.parametrize(
    "response",
    [AttentionResponse.ACCEPTED, AttentionResponse.DISMISSED, AttentionResponse.IGNORED],
)
def test_response_update_accepts_real_responses(response):
    assert AttentionResponseUpdate(response=response).response is response


def test_response_update_rejects_no_response():
    """`no_response` is the initial state, not something a user reports —
    accepting it would let a real answer be erased, and 6.9 would read that
    as "never answered"."""
    with pytest.raises(ValidationError):
        AttentionResponseUpdate(response=AttentionResponse.NO_RESPONSE)


def test_surface_result_reports_the_window_it_applied():
    """A suppressed caller should be able to see *which* window suppressed
    it without reading the server's config."""
    result = AttentionSurfaceResult(suppressed=True, reason="already surfaced", dedup_window_hours=24)
    assert result.log is None
    assert result.dedup_window_hours == 24


def test_log_response_exposes_the_reason():
    """M5 requires the reason to be queryable after the fact."""
    assert "reason_key" in AttentionLogResponse.model_fields
    assert "level" in AttentionLogResponse.model_fields
