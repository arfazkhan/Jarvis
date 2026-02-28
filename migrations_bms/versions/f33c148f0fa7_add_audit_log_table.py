"""add_audit_log_table

Revision ID: f33c148f0fa7
Revises: 233ed713cdfd
Create Date: 2026-02-25 01:43:54.623670

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f33c148f0fa7'
down_revision: Union[str, None] = '233ed713cdfd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('timestamp', sa.Float(), nullable=False),
        sa.Column('method', sa.String(10), nullable=False),
        sa.Column('path', sa.String(255), nullable=False),
        sa.Column('status', sa.Integer(), nullable=False),
        sa.Column('user', sa.String(50), nullable=False),
        sa.Column('ip', sa.String(45), nullable=True),
        sa.Column('latency_ms', sa.Float(), nullable=True)
    )
    op.create_index('idx_audit_user', 'audit_logs', ['user'])
    op.create_index('idx_audit_timestamp', 'audit_logs', ['timestamp'])


def downgrade() -> None:
    op.drop_table('audit_logs')
