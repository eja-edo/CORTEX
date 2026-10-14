"""initial schema: tables, RLS, grants, supervisor view

Revision ID: 0001
Revises:
"""
from alembic import op

from cortex_leads.db.models import NO_RLS, SUPERVISOR_RUN_COLUMNS, WAVE2_TABLES, Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# The schema is created from the models of this exact commit; later changes must be new revisions.
# DELETE is granted only where the flow needs it.
DELETABLE = {"followup_job", "catalog_item"}


def upgrade() -> None:
    bind = op.get_bind()
    # Dev compose creates the roles with passwords; elsewhere make sure they exist (no login).
    for role in ("cl_app", "cl_supervisor"):
        op.execute(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') "
            f"THEN CREATE ROLE {role} NOLOGIN NOSUPERUSER NOBYPASSRLS; END IF; END $$"
        )
    # Wave-2 tables belong to 0002 (explicit DDL); the columns/CHECKs 0002 alters are idempotent there.
    v0 = [t for t in Base.metadata.sorted_tables if t.name not in WAVE2_TABLES]
    Base.metadata.create_all(bind, tables=v0)

    for table in v0:
        name = table.name
        privs = "SELECT, INSERT, UPDATE" + (", DELETE" if name in DELETABLE else "")
        op.execute(f"GRANT {privs} ON {name} TO cl_app")
        if name in NO_RLS:
            continue
        op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")  # DESIGN A1
        op.execute(
            f"CREATE POLICY tenant_isolation ON {name} "
            "USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
        )

    # Supervisor: column grants only (no free text) + security_invoker view so RLS still applies.
    cols = ", ".join(f"r.{c}" for c in SUPERVISOR_RUN_COLUMNS)
    op.execute(
        f"CREATE VIEW supervisor_run_view WITH (security_invoker = true) AS "
        f"SELECT {cols}, s.name AS sandbox_name FROM trigger_run r JOIN sandbox s ON s.id = r.sandbox_id"
    )
    op.execute(f"GRANT SELECT ({', '.join(SUPERVISOR_RUN_COLUMNS)}) ON trigger_run TO cl_supervisor")
    op.execute("GRANT SELECT (id, tenant_id, name) ON sandbox TO cl_supervisor")
    op.execute("GRANT SELECT ON supervisor_run_view TO cl_supervisor")
    op.execute("GRANT cl_supervisor TO cl_app")  # lets cl_app `SET ROLE cl_supervisor`


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS supervisor_run_view")
    Base.metadata.drop_all(op.get_bind())
