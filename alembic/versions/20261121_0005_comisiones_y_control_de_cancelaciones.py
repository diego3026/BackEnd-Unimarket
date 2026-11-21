"""comisiones y control de cancelaciones

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-21 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("stores", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("cancelled_by", sa.String(length=10), server_default="", nullable=False))
    op.add_column("orders", sa.Column("paid_cancelled", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("orders", sa.Column("customer_confirmation", sa.String(length=15), server_default="", nullable=False))
    op.add_column("orders", sa.Column("dispute_status", sa.String(length=12), server_default="", nullable=False))
    op.add_column("orders", sa.Column("dispute_note", sa.String(length=300), server_default="", nullable=False))
    op.create_index("ix_orders_delivered_at", "orders", ["delivered_at"])
    op.create_index("ix_orders_dispute_status", "orders", ["dispute_status"])
    # Datos existentes: las tiendas aprobadas empiezan a contar desde su creación,
    # y las fechas de entrega/cancelación salen del historial del pedido.
    op.execute("UPDATE stores SET approved_at = created_at WHERE status = 'approved'")
    op.execute(
        "UPDATE orders SET delivered_at = (history->>'delivered')::timestamptz "
        "WHERE status = 'delivered' AND history->>'delivered' IS NOT NULL"
    )
    op.execute(
        "UPDATE orders SET cancelled_at = (history->>'cancelled')::timestamptz "
        "WHERE status = 'cancelled' AND history->>'cancelled' IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_orders_dispute_status", table_name="orders")
    op.drop_index("ix_orders_delivered_at", table_name="orders")
    for col in (
        "dispute_note",
        "dispute_status",
        "customer_confirmation",
        "paid_cancelled",
        "cancelled_by",
        "cancelled_at",
        "delivered_at",
    ):
        op.drop_column("orders", col)
    op.drop_column("stores", "approved_at")
