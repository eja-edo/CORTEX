"""normalize uploadstatus enum labels to lowercase

Revision ID: 20260416_0006
Revises: 20260414_0005
Create Date: 2026-04-16 22:45:00
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "20260416_0006"
down_revision: Union[str, None] = "20260414_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _rename_enum_label_if_exists(type_name: str, old_label: str, new_label: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_type t
                JOIN pg_enum e ON e.enumtypid = t.oid
                WHERE t.typname = '{type_name}' AND e.enumlabel = '{old_label}'
            )
            AND NOT EXISTS (
                SELECT 1
                FROM pg_type t
                JOIN pg_enum e ON e.enumtypid = t.oid
                WHERE t.typname = '{type_name}' AND e.enumlabel = '{new_label}'
            ) THEN
                EXECUTE 'ALTER TYPE {type_name} RENAME VALUE ''{old_label}'' TO ''{new_label}''';
            END IF;
        END$$;
        """
    )


def upgrade() -> None:
    _rename_enum_label_if_exists("uploadstatus", "INITIATED", "initiated")
    _rename_enum_label_if_exists("uploadstatus", "UPLOADING", "uploading")
    _rename_enum_label_if_exists("uploadstatus", "COMPLETED", "completed")
    _rename_enum_label_if_exists("uploadstatus", "FAILED", "failed")


def downgrade() -> None:
    _rename_enum_label_if_exists("uploadstatus", "initiated", "INITIATED")
    _rename_enum_label_if_exists("uploadstatus", "uploading", "UPLOADING")
    _rename_enum_label_if_exists("uploadstatus", "completed", "COMPLETED")
    _rename_enum_label_if_exists("uploadstatus", "failed", "FAILED")
