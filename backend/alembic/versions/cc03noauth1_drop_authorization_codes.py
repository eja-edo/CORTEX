"""Xoá authorization_codes — login bỏ PKCE, dùng /auth/login trực tiếp

Luồng /auth/authorize + /auth/token (Authorization Code + PKCE) được viết
cho một client third-party đi qua redirect thật, nhưng frontend gọi cả hai
bước bằng fetch ngay trên cùng trang — không hề có redirect. PKCE chống lộ
authorization code qua redirect, nên không bảo vệ được gì ở đây; nó chỉ kéo
theo `window.crypto.subtle`, một API chỉ tồn tại trong secure context
(HTTPS/localhost), khiến login vỡ khi deploy qua HTTP thường.

Thay bằng /auth/login: email + password → token pair, không qua bảng
authorization_codes nữa.

Revision ID: cc03noauth1
Revises: bb02proc0dur1
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "cc03noauth1"
down_revision: Union[str, None] = "bb02proc0dur1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(op.f('ix_authorization_codes_user_id'), table_name='authorization_codes')
    op.drop_index(op.f('ix_authorization_codes_code_hash'), table_name='authorization_codes')
    op.drop_table('authorization_codes')


def downgrade() -> None:
    op.create_table(
        'authorization_codes',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('code_hash', sa.String(length=255), nullable=False),
        sa.Column('client_id', sa.String(length=255), nullable=False),
        sa.Column('redirect_uri', sa.String(length=1000), nullable=False),
        sa.Column('code_challenge', sa.String(length=255), nullable=False),
        sa.Column('code_challenge_method', sa.String(length=10), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_authorization_codes_code_hash'), 'authorization_codes', ['code_hash'], unique=True)
    op.create_index(op.f('ix_authorization_codes_user_id'), 'authorization_codes', ['user_id'], unique=False)
