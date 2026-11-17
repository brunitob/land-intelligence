"""caché de tiempos de manejo por punto

Revision ID: b3e8f1a2c4d5
Revises: a7c1e2d4b9f0
Create Date: 2026-11-13 16:20:00
"""
from alembic import op
import sqlalchemy as sa

revision = 'b3e8f1a2c4d5'
down_revision = 'a7c1e2d4b9f0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'drive_time_cache',
        sa.Column('airport_code', sa.String(length=8), primary_key=True),
        sa.Column('lat_e4', sa.Integer(), primary_key=True),
        sa.Column('lon_e4', sa.Integer(), primary_key=True),
        sa.Column('minutes', sa.Float(), nullable=True),
        sa.Column('computed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('drive_time_cache')
