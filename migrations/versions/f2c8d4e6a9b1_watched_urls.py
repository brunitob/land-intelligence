"""fichas en seguimiento (sección Seguimiento)

Revision ID: f2c8d4e6a9b1
Revises: e7a3b5c1d2f4
Create Date: 2026-11-22 12:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = 'f2c8d4e6a9b1'
down_revision = 'e7a3b5c1d2f4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'watched_urls',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('url', sa.Text(), nullable=False, unique=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('listing_id', sa.Integer(), sa.ForeignKey('listings.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('seen_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('watched_urls')
