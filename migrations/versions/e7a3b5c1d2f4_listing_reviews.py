"""avisos revisados (filtro "Solo nuevos")

Los avisos vistos por primera vez hace más de 2 días quedan marcados como revisados: así "nuevos" arranca con lo
de las inmobiliarias recién agregadas y no con todo el histórico.

Revision ID: e7a3b5c1d2f4
Revises: d4f8a1c2e9b7
Create Date: 2026-11-19 22:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = 'e7a3b5c1d2f4'
down_revision = 'd4f8a1c2e9b7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'listing_reviews',
        sa.Column('listing_id', sa.Integer(), sa.ForeignKey('listings.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('reviewed_by', sa.String(length=64), nullable=True),
    )
    op.execute("INSERT INTO listing_reviews (listing_id, reviewed_by) "
               "SELECT id, 'inicial' FROM listings WHERE first_seen_at < now() - interval '2 days'")


def downgrade() -> None:
    op.drop_table('listing_reviews')
