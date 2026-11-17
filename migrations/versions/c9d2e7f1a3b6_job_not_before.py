"""jobs.not_before para diferir jobs (franja horaria de robots.txt)

Revision ID: c9d2e7f1a3b6
Revises: b3e8f1a2c4d5
Create Date: 2026-11-17 17:40:00
"""
from alembic import op
import sqlalchemy as sa

revision = 'c9d2e7f1a3b6'
down_revision = 'b3e8f1a2c4d5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('not_before', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs', 'not_before')
