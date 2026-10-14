"""wave 2: contact_fact, deal, outbox, sandbox domain pack/send mode, supervisor views

Written as explicit DDL (no create_all). 0001 builds from the current models, so on a fresh
database the altered columns/CHECKs already exist when this runs: every alteration is idempotent.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

RLS_USING = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
NEW_TABLES = ("contact_fact", "deal", "outbox")
VIEWS = {
    "supervisor_fact_view": (
        "contact_fact", "tenant_id, kind, source, status, created_at",
        ["tenant_id", "kind", "source", "status", "created_at"]),
    "supervisor_deal_view": (
        "deal", "tenant_id, status, value, currency, occurred_at, linked",
        ["tenant_id", "status", "value", "currency", "occurred_at", "linked"]),
    "supervisor_outbox_view": (
        "outbox", "tenant_id, status, reason, split_part(actor, ':', 1) AS actor_kind, "
        "created_at, sent_at", ["tenant_id", "status", "reason", "actor", "created_at", "sent_at"]),
}


def _check(table: str, name: str, col: str, *values: str) -> None:
    vals = ", ".join(f"'{v}'" for v in values)
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{table}_{name}")
    op.execute(f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_{name} CHECK ({col} in ({vals}))")


def upgrade() -> None:
    op.execute("""CREATE TABLE contact_fact (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
        contact_id uuid NOT NULL REFERENCES contact(id),
        conversation_id uuid REFERENCES conversation(id),
        kind text NOT NULL, value jsonb NOT NULL,
        evidence_msg_ids uuid[] NOT NULL DEFAULT '{}'::uuid[],
        source text, status text NOT NULL DEFAULT 'candidate',
        superseded_by uuid REFERENCES contact_fact(id),
        created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_contact_fact_status CHECK (status in ('candidate', 'active', 'superseded',
            'fulfilled', 'cancelled', 'done', 'rejected')))""")
    op.execute("CREATE INDEX ix_contact_fact_lookup ON contact_fact (tenant_id, contact_id, kind, status)")
    op.execute("""CREATE TABLE deal (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
        connector_id text NOT NULL REFERENCES connector(id), external_id text NOT NULL,
        contact_id uuid REFERENCES contact(id), conversation_id uuid REFERENCES conversation(id),
        status text NOT NULL, value numeric, currency text NOT NULL DEFAULT 'VND',
        occurred_at timestamptz NOT NULL, linked boolean NOT NULL DEFAULT false,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_deal_external UNIQUE (tenant_id, connector_id, external_id),
        CONSTRAINT ck_deal_status CHECK (status in ('booked', 'won', 'lost', 'cancelled')))""")
    op.execute("""CREATE TABLE outbox (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, action_id uuid NOT NULL UNIQUE,
        conversation_id uuid NOT NULL REFERENCES conversation(id),
        connector_id text NOT NULL REFERENCES connector(id),
        draft_id uuid REFERENCES draft(id), actor text NOT NULL, text text NOT NULL,
        disclosure text, "window" jsonb NOT NULL DEFAULT '{}'::jsonb,
        source jsonb NOT NULL DEFAULT '{}'::jsonb, status text NOT NULL DEFAULT 'queued',
        reason text, attempts integer NOT NULL DEFAULT 0, not_before timestamptz,
        external_message_id text, created_at timestamptz NOT NULL DEFAULT now(),
        sent_at timestamptz,
        CONSTRAINT ck_outbox_status CHECK (status in ('queued', 'sending', 'sent', 'refused',
            'error', 'cancelled')))""")
    op.execute("CREATE INDEX ix_outbox_pick ON outbox (tenant_id, status, not_before)")
    for t in NEW_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {t} TO cl_app")
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")  # DESIGN A1
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING ({RLS_USING}) WITH CHECK ({RLS_USING})")

    op.execute("ALTER TABLE sandbox ADD COLUMN IF NOT EXISTS send_mode text NOT NULL DEFAULT 'manual'")
    op.execute("ALTER TABLE sandbox ADD COLUMN IF NOT EXISTS domain_pack jsonb NOT NULL DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE sandbox ADD COLUMN IF NOT EXISTS business_hours jsonb NOT NULL "
               "DEFAULT '{\"start\":\"08:00\",\"end\":\"21:00\"}'::jsonb")
    op.execute("ALTER TABLE sandbox DROP CONSTRAINT IF EXISTS ck_sandbox_purpose")
    _check("sandbox", "send_mode", "send_mode", "auto", "manual")
    op.execute("ALTER TABLE connector ADD COLUMN IF NOT EXISTS outbound jsonb")
    _check("conversation", "state", "state", "open", "booked", "won", "lost", "opted_out")
    _check("draft", "status", "status", "proposed", "approved", "sent", "edited", "self",
           "skipped", "expired", "blocked", "failed")
    _check("staff_action", "action", "action", "approved", "sent", "edited", "self", "skipped")

    for view, (table, select, cols) in VIEWS.items():
        op.execute(f"CREATE VIEW {view} WITH (security_invoker = true) AS SELECT {select} FROM {table}")
        op.execute(f"GRANT SELECT ({', '.join(cols)}) ON {table} TO cl_supervisor")
        op.execute(f"GRANT SELECT ON {view} TO cl_supervisor")


def downgrade() -> None:
    for view in VIEWS:
        op.execute(f"DROP VIEW IF EXISTS {view}")
    for t in reversed(NEW_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t}")
    op.execute("ALTER TABLE connector DROP COLUMN IF EXISTS outbound")
    for col in ("business_hours", "domain_pack", "send_mode"):
        op.execute(f"ALTER TABLE sandbox DROP COLUMN IF EXISTS {col}")
    op.execute("UPDATE conversation SET state = 'open' WHERE state = 'booked'")
    op.execute("UPDATE draft SET status = 'blocked' WHERE status = 'failed'")
    op.execute("UPDATE draft SET status = 'proposed' WHERE status = 'approved'")
    op.execute("UPDATE staff_action SET action = 'sent' WHERE action = 'approved'")
    _check("conversation", "state", "state", "open", "won", "lost", "opted_out")
    _check("draft", "status", "status", "proposed", "sent", "edited", "self", "skipped",
           "expired", "blocked")
    _check("staff_action", "action", "action", "sent", "edited", "self", "skipped")
    op.execute("ALTER TABLE sandbox ADD CONSTRAINT ck_sandbox_purpose "
               "CHECK (purpose in ('customer_care', 'owner_digest'))")
