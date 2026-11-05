"""initial

Revision ID: 0001
Revises:
Create Date: 2026-11-05 09:37:56.435557
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('app_settings',
    sa.Column('key', sa.String(), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('login_attempts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('email', sa.String(), nullable=False),
    sa.Column('ip', sa.String(), nullable=False),
    sa.Column('success', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_login_attempts_created_at'), 'login_attempts', ['created_at'], unique=False)
    op.create_index(op.f('ix_login_attempts_email'), 'login_attempts', ['email'], unique=False)
    op.create_index(op.f('ix_login_attempts_ip'), 'login_attempts', ['ip'], unique=False)
    op.create_table('payment_methods',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('type', sa.Enum('credit_card', 'upi', 'other', name='payment_method_type'), nullable=False),
    sa.Column('bank', sa.String(), nullable=True),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('network', sa.Enum('visa', 'mastercard', 'rupay', name='card_network'), nullable=True),
    sa.Column('image', sa.LargeBinary(), nullable=True),
    sa.Column('image_mime', sa.String(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('push_subscriptions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('endpoint', sa.String(), nullable=False),
    sa.Column('p256dh', sa.String(), nullable=False),
    sa.Column('auth', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('endpoint')
    )
    op.create_table('users',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('email', sa.String(), nullable=False),
    sa.Column('password_hash', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_table('refresh_tokens',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('family_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('replaced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_refresh_tokens_family_id'), 'refresh_tokens', ['family_id'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_user_id'), 'refresh_tokens', ['user_id'], unique=False)
    op.create_table('subscriptions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('merchant_name', sa.String(), nullable=False),
    sa.Column('merchant_domain', sa.String(), nullable=True),
    sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('currency', sa.Enum('INR', 'USD', name='currency'), nullable=False),
    sa.Column('billing_cycle', sa.Enum('monthly', 'quarterly', 'half_yearly', 'yearly', name='billing_cycle'), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('payment_method_id', sa.Uuid(), nullable=True),
    sa.Column('category', sa.String(), server_default='Other', nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('status', sa.Enum('active', 'paused', 'cancelled', name='subscription_status'), server_default='active', nullable=False),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('amount > 0', name='ck_subscriptions_amount_positive'),
    sa.ForeignKeyConstraint(['payment_method_id'], ['payment_methods.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_subscriptions_payment_method_id'), 'subscriptions', ['payment_method_id'], unique=False)
    op.create_table('reminder_log',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('subscription_id', sa.Uuid(), nullable=False),
    sa.Column('renewal_date', sa.Date(), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('subscription_id', 'renewal_date', name='uq_reminder_log_sub_renewal')
    )


def downgrade() -> None:
    op.drop_table('reminder_log')
    op.drop_index(op.f('ix_subscriptions_payment_method_id'), table_name='subscriptions')
    op.drop_table('subscriptions')
    op.drop_index(op.f('ix_refresh_tokens_user_id'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_family_id'), table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_table('users')
    op.drop_table('push_subscriptions')
    op.drop_table('payment_methods')
    op.drop_index(op.f('ix_login_attempts_ip'), table_name='login_attempts')
    op.drop_index(op.f('ix_login_attempts_email'), table_name='login_attempts')
    op.drop_index(op.f('ix_login_attempts_created_at'), table_name='login_attempts')
    op.drop_table('login_attempts')
    op.drop_table('app_settings')
    for enum_name in ('subscription_status', 'billing_cycle', 'currency', 'card_network', 'payment_method_type'):
        op.execute(f'DROP TYPE {enum_name}')
