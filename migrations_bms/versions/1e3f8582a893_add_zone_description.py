"""add_zone_description

Revision ID: 1e3f8582a893
Revises: 019f2885c5c7
Create Date: 2026-02-24 23:34:47.877838

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1e3f8582a893'
down_revision: Union[str, None] = '019f2885c5c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('zones', sa.Column('description', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('zones', 'description')
