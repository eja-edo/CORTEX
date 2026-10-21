"""WP17 notify_target + notification, WP18 booking

Explicit DDL like 0002: 0001 skips these tables (they are in models.WAVE2_TABLES), so this creates
them on every database.

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

RLS_USING = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
TABLES = ("notify_target", "notification", "booking")


def upgrade() -> None:
    op.execute("""CREATE TABLE notify_target (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, kind text NOT NULL DEFAULT 'telegram',
        address text NOT NULL, label text, active boolean NOT NULL DEFAULT true,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_notify_target_tenant_id_kind_address UNIQUE (tenant_id, kind, address),
        CONSTRAINT ck_notify_target_kind CHECK (kind in ('telegram')))""")
    op.execute("""CREATE TABLE notification (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, kind text NOT NULL, ref_id uuid NOT NULL,
        status text NOT NULL DEFAULT 'queued', attempts integer NOT NULL DEFAULT 0,
        not_before timestamptz, created_at timestamptz NOT NULL DEFAULT now(), sent_at timestamptz,
        CONSTRAINT uq_notification_tenant_id_kind_ref_id UNIQUE (tenant_id, kind, ref_id),
        CONSTRAINT ck_notification_kind CHECK (kind in ('handoff', 'booking')),
        CONSTRAINT ck_notification_status CHECK (status in ('queued', 'sent', 'failed', 'skipped')))""")
    op.execute("CREATE INDEX ix_notification_pick ON notification (tenant_id, status, not_before)")
    op.execute("""CREATE TABLE booking (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
        sandbox_id uuid NOT NULL REFERENCES sandbox(id),
        conversation_id uuid NOT NULL REFERENCES conversation(id),
        contact_id uuid NOT NULL REFERENCES contact(id),
        slot_code text NOT NULL, starts_at timestamptz NOT NULL,
        status text NOT NULL DEFAULT 'confirmed', actor text NOT NULL, run_id uuid,
        created_at timestamptz NOT NULL DEFAULT now(), cancelled_at timestamptz, cancelled_by text,
        CONSTRAINT ck_booking_status CHECK (status in ('confirmed', 'cancelled')))""")
    op.execute("CREATE INDEX ix_booking_slot ON booking (tenant_id, slot_code, status)")
    op.execute("CREATE UNIQUE INDEX uq_booking_one_live ON booking (tenant_id, conversation_id) "
               "WHERE status = 'confirmed'")
    for t in TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {t} TO cl_app")
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")  # DESIGN A1
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING ({RLS_USING}) WITH CHECK ({RLS_USING})")


def downgrade() -> None:
    for t in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t}")
