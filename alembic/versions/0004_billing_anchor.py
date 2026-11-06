"""split start_date into billing_anchor_date and nullable started_on

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-06 10:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('subscriptions', sa.Column('billing_anchor_date', sa.Date(), nullable=True))
    op.execute('UPDATE subscriptions SET billing_anchor_date = start_date')
    op.alter_column('subscriptions', 'billing_anchor_date', nullable=False)
    op.alter_column('subscriptions', 'start_date', new_column_name='started_on', nullable=True)


def downgrade() -> None:
    op.execute('UPDATE subscriptions SET started_on = billing_anchor_date')  # the anchor is what renewals used
    op.alter_column('subscriptions', 'started_on', new_column_name='start_date', nullable=False)
    op.drop_column('subscriptions', 'billing_anchor_date')
