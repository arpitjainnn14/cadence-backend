"""login attempt composite indexes

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-05 15:00:00
"""
from collections.abc import Sequence

from alembic import op


revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index('ix_login_attempts_email_created_at', 'login_attempts', ['email', 'created_at'], unique=False)
    op.create_index('ix_login_attempts_ip_created_at', 'login_attempts', ['ip', 'created_at'], unique=False)
    op.drop_index('ix_login_attempts_email', table_name='login_attempts')
    op.drop_index('ix_login_attempts_ip', table_name='login_attempts')


def downgrade() -> None:
    op.create_index('ix_login_attempts_ip', 'login_attempts', ['ip'], unique=False)
    op.create_index('ix_login_attempts_email', 'login_attempts', ['email'], unique=False)
    op.drop_index('ix_login_attempts_ip_created_at', table_name='login_attempts')
    op.drop_index('ix_login_attempts_email_created_at', table_name='login_attempts')
