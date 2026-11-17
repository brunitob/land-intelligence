"""highlights (destacados) con filtros editables y asignación manual de anuncios

Revision ID: a7c1e2d4b9f0
Revises: f3d5c03aaeaa
Create Date: 2026-11-13 12:30:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'a7c1e2d4b9f0'
down_revision = 'f3d5c03aaeaa'
branch_labels = None
depends_on = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    hl = op.create_table(
        'highlights',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=80), nullable=False, unique=True),
        sa.Column('keywords', JSONB, nullable=False, server_default='[]'),
        sa.Column('match_mode', sa.String(length=8), nullable=False, server_default='any'),
        sa.Column('zones', JSONB, nullable=False, server_default='[]'),
        sa.Column('property_types', JSONB, nullable=False, server_default='[]'),
        sa.Column('water_classes', JSONB, nullable=False, server_default='[]'),
        sa.Column('max_price_usd', sa.Float(), nullable=True),
        sa.Column('min_area_m2', sa.Float(), nullable=True),
        sa.Column('include_rentals', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        'highlight_listings',
        sa.Column('highlight_id', sa.Integer(), sa.ForeignKey('highlights.id', ondelete='CASCADE'),
                  primary_key=True),
        sa.Column('listing_id', sa.Integer(), sa.ForeignKey('listings.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('mode', sa.String(length=10), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_highlight_listings_listing_id', 'highlight_listings', ['listing_id'])
    # Ejemplos iniciales (editables o borrables desde el dashboard; no se vuelven a crear).
    op.bulk_insert(hl, [
        # Mismas claves en todas las filas: bulk_insert toma las columnas de la primera.
        {"name": "Villa", "keywords": ["villa"], "match_mode": "any", "min_area_m2": None, "position": 1},
        {"name": "Hectárea", "keywords": [], "match_mode": "any", "min_area_m2": 10000, "position": 2},
        {"name": "Lago", "keywords": ["lago", "costa", "playa"], "match_mode": "any", "min_area_m2": None,
         "position": 3},
    ])


def downgrade() -> None:
    op.drop_index('ix_highlight_listings_listing_id', table_name='highlight_listings')
    op.drop_table('highlight_listings')
    op.drop_table('highlights')
