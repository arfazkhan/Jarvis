"""add_performance_indexes

Revision ID: 233ed713cdfd
Revises: 1e3f8582a893
Create Date: 2026-02-24 23:41:46.367696

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '233ed713cdfd'
down_revision: Union[str, None] = '1e3f8582a893'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('idx_workorders_status', 'work_orders', ['status'])
    op.create_index('idx_gsas_building', 'gsas_scores', ['building_id'])


def downgrade() -> None:
    op.drop_index('idx_gsas_building', 'gsas_scores')
    op.drop_index('idx_workorders_status', 'work_orders')
