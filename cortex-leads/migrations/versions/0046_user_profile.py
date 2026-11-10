"""Basic details of a person on an account: phone, date of birth, national ID number

The ID number is encrypted (Fernet, the same key as the connector secrets) so a copy of the database does not read as a list of ID
numbers. Phone and date of birth are plain. None of the three is ever sent to a model or written into the audit trail as a value.

Revision ID: 0046
Revises: 0045
"""
from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE app_user ADD COLUMN phone text, ADD COLUMN birth_date date, ADD COLUMN national_id_enc text")


def downgrade() -> None:
    op.execute("ALTER TABLE app_user DROP COLUMN phone, DROP COLUMN birth_date, DROP COLUMN national_id_enc")
