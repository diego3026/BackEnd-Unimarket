"""pines del mapa y ubicación de tiendas

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-21 13:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("campus_places", sa.Column("description", sa.String(length=500), server_default="", nullable=False))
    op.add_column("campus_places", sa.Column("kind", sa.String(length=20), server_default="building", nullable=False))
    op.add_column("campus_places", sa.Column("is_delivery_point", sa.Boolean(), server_default="true", nullable=False))
    op.add_column("stores", sa.Column("address", sa.String(length=200), server_default="", nullable=False))
    op.add_column("stores", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("stores", sa.Column("longitude", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("stores", "longitude")
    op.drop_column("stores", "latitude")
    op.drop_column("stores", "address")
    op.drop_column("campus_places", "is_delivery_point")
    op.drop_column("campus_places", "kind")
    op.drop_column("campus_places", "description")
