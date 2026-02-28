"""baseline_bms_schema

Revision ID: 019f2885c5c7
Revises: 
Create Date: 2026-02-24 23:33:28.515437

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '019f2885c5c7'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Equipment Table
    op.create_table(
        'equipment',
        sa.Column('equipment_id', sa.String(), primary_key=True),
        sa.Column('name', sa.String()),
        sa.Column('equipment_type', sa.String()),
        sa.Column('status', sa.String(), server_default='unknown'),
        sa.Column('location', sa.String()),
        sa.Column('runtime_hours', sa.Float(), server_default='0'),
        sa.Column('efficiency', sa.Float()),
        sa.Column('last_maintenance', sa.String()),
        sa.Column('parent_equipment_id', sa.String()),
        sa.Column('metadata', sa.String()),
        sa.Column('created_at', sa.String(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.String(), server_default=sa.text('CURRENT_TIMESTAMP'))
    )

    # 2. Data Points Table
    op.create_table(
        'data_points',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('point_id', sa.String(), nullable=False),
        sa.Column('equipment_id', sa.String(), sa.ForeignKey('equipment.equipment_id')),
        sa.Column('value', sa.Float()),
        sa.Column('unit', sa.String()),
        sa.Column('quality', sa.String(), server_default='good'),
        sa.Column('timestamp', sa.String(), server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    op.create_index('idx_datapoints_point_time', 'data_points', ['point_id', 'timestamp'])

    # 3. Alarms Table
    op.create_table(
        'alarms',
        sa.Column('alarm_id', sa.String(), primary_key=True),
        sa.Column('equipment_id', sa.String(), sa.ForeignKey('equipment.equipment_id')),
        sa.Column('source_point_id', sa.String()),
        sa.Column('message', sa.String()),
        sa.Column('severity', sa.String()),
        sa.Column('state', sa.String(), server_default='active'),
        sa.Column('triggered_at', sa.String(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('acknowledged_at', sa.String()),
        sa.Column('acknowledged_by', sa.String()),
        sa.Column('resolved_at', sa.String()),
        sa.Column('cluster_id', sa.String()),
        sa.Column('metadata', sa.String())
    )

    # 4. Energy Readings Table
    op.create_table(
        'energy_readings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('meter_id', sa.String(), nullable=False),
        sa.Column('value', sa.Float()),
        sa.Column('unit', sa.String(), server_default='kW'),
        sa.Column('outdoor_temp', sa.Float()),
        sa.Column('occupancy', sa.Float()),
        sa.Column('timestamp', sa.String(), server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    op.create_index('idx_energy_meter_time', 'energy_readings', ['meter_id', 'timestamp'])

    # 5. GSAS Scores Table
    op.create_table(
        'gsas_scores',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('building_id', sa.String()),
        sa.Column('overall_score', sa.Float()),
        sa.Column('certification_level', sa.String()),
        sa.Column('category_scores', sa.String()),
        sa.Column('timestamp', sa.String(), server_default=sa.text('CURRENT_TIMESTAMP'))
    )

    # 6. Work Orders Table
    op.create_table(
        'work_orders',
        sa.Column('work_order_id', sa.String(), primary_key=True),
        sa.Column('equipment_id', sa.String(), sa.ForeignKey('equipment.equipment_id')),
        sa.Column('task_type', sa.String()),
        sa.Column('status', sa.String(), server_default='open'),
        sa.Column('pre_snapshot', sa.String()),
        sa.Column('post_snapshot', sa.String()),
        sa.Column('opened_at', sa.String(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('closed_at', sa.String()),
        sa.Column('verification_result', sa.String())
    )

    # 7. Zones Table
    op.create_table(
        'zones',
        sa.Column('zone_id', sa.String(), primary_key=True),
        sa.Column('name', sa.String()),
        sa.Column('floor', sa.String()),
        sa.Column('building', sa.String()),
        sa.Column('co2_point_id', sa.String()),
        sa.Column('vav_point_id', sa.String()),
        sa.Column('lighting_point_id', sa.String()),
        sa.Column('return_air_point_id', sa.String()),
        sa.Column('schedule_id', sa.String()),
        sa.Column('load_kw', sa.Float(), server_default='2.0'),
        sa.Column('metadata', sa.String())
    )


def downgrade() -> None:
    op.drop_table('zones')
    op.drop_table('work_orders')
    op.drop_table('gsas_scores')
    op.drop_table('energy_readings')
    op.drop_table('alarms')
    op.drop_table('data_points')
    op.drop_table('equipment')
