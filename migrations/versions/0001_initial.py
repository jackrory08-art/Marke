"""initial

Revision ID: 0001
Revises: 
"""
from alembic import op
import sqlalchemy as sa


revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('ai_usage_daily',
    sa.Column('day', sa.String(length=10), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('model', sa.String(length=64), nullable=False),
    sa.Column('calls', sa.Integer(), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('cost_usd', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('day', 'provider', 'model')
    )
    op.create_table('ai_verdicts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('cache_key', sa.String(length=80), nullable=False),
    sa.Column('pair_key', sa.String(length=255), nullable=False),
    sa.Column('platform_a', sa.String(length=32), nullable=False),
    sa.Column('market_a_id', sa.String(length=128), nullable=False),
    sa.Column('platform_b', sa.String(length=32), nullable=False),
    sa.Column('market_b_id', sa.String(length=128), nullable=False),
    sa.Column('status', sa.String(length=8), nullable=False),
    sa.Column('verdict', sa.String(length=32), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('differences', sa.JSON(), nullable=True),
    sa.Column('short_reason', sa.Text(), nullable=True),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('model', sa.String(length=64), nullable=False),
    sa.Column('prompt_version', sa.String(length=16), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('cost_usd', sa.Float(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('cache_key')
    )
    with op.batch_alter_table('ai_verdicts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ai_verdicts_pair_key'), ['pair_key'], unique=False)

    op.create_table('opportunity_history',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('opportunity_key', sa.String(length=255), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('pair_key', sa.String(length=255), nullable=True),
    sa.Column('platforms', sa.String(length=64), nullable=False),
    sa.Column('market_a_id', sa.String(length=128), nullable=True),
    sa.Column('market_b_id', sa.String(length=128), nullable=True),
    sa.Column('net_edge', sa.Float(), nullable=False),
    sa.Column('gross_edge', sa.Float(), nullable=True),
    sa.Column('fees', sa.JSON(), nullable=True),
    sa.Column('depth', sa.Float(), nullable=True),
    sa.Column('verification_status', sa.String(length=16), nullable=True),
    sa.Column('actionable', sa.Boolean(), nullable=False),
    sa.Column('first_seen_at', sa.DateTime(), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(), nullable=False),
    sa.Column('seen_count', sa.Integer(), nullable=False),
    sa.Column('max_net_edge', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('opportunity_key')
    )
    with op.batch_alter_table('opportunity_history', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_opportunity_history_pair_key'), ['pair_key'], unique=False)

    op.create_table('settings_overrides',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', sa.JSON(), nullable=True),
    sa.Column('updated_by', sa.String(length=64), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('failed_login_count', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('last_login_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('username')
    )
    op.create_table('ai_analyses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('cache_key', sa.String(length=80), nullable=False),
    sa.Column('opportunity_key', sa.String(length=255), nullable=False),
    sa.Column('verdict_id', sa.Integer(), nullable=True),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('risks', sa.JSON(), nullable=False),
    sa.Column('quality_score', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('model', sa.String(length=64), nullable=False),
    sa.Column('prompt_version', sa.String(length=16), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('cost_usd', sa.Float(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['verdict_id'], ['ai_verdicts.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('cache_key')
    )
    with op.batch_alter_table('ai_analyses', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ai_analyses_opportunity_key'), ['opportunity_key'], unique=False)

    op.create_table('audit_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('at', sa.DateTime(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('event', sa.String(length=32), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('detail', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.create_index('ix_audit_log_at', ['at'], unique=False)

    op.create_table('pair_dismissals',
    sa.Column('pair_key', sa.String(length=255), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('dismissed_at', sa.DateTime(), nullable=False),
    sa.Column('note', sa.String(length=500), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('pair_key')
    )
    op.create_table('sessions',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('csrf_token', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=255), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sessions_user_id'), ['user_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sessions_user_id'))

    op.drop_table('sessions')
    op.drop_table('pair_dismissals')
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.drop_index('ix_audit_log_at')

    op.drop_table('audit_log')
    with op.batch_alter_table('ai_analyses', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ai_analyses_opportunity_key'))

    op.drop_table('ai_analyses')
    op.drop_table('users')
    op.drop_table('settings_overrides')
    with op.batch_alter_table('opportunity_history', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_opportunity_history_pair_key'))

    op.drop_table('opportunity_history')
    with op.batch_alter_table('ai_verdicts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ai_verdicts_pair_key'))

    op.drop_table('ai_verdicts')
    op.drop_table('ai_usage_daily')
