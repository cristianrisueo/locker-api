"""crear deliveries

Revision ID: fc2ffe8da1fd
Revises: 8438a2b81939
Create Date: 2026-10-05 14:39:08.518134

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fc2ffe8da1fd"
down_revision: str | Sequence[str] | None = "8438a2b81939"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Condición de «entrega activa» de los dos índices únicos parciales
ACTIVE = "status IN ('PENDING', 'DEPOSITED')"


def upgrade() -> None:
    """Crea la tabla de entregas, con su CHECK de estados y los dos índices únicos parciales de entregas activas."""
    op.create_table(
        "deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("locker_id", sa.Uuid(), nullable=False),
        sa.Column("carrier", sa.String(length=100), nullable=False),
        sa.Column("tracking_ref", sa.String(length=64), nullable=False),
        sa.Column("recipient", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="PENDING", nullable=False),
        sa.Column("deposited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("picked_up_at", sa.DateTime(timezone=True), nullable=True),
        # Estados válidos
        sa.CheckConstraint("status IN ('PENDING', 'DEPOSITED', 'PICKED_UP')", name=op.f("ck_deliveries_status")),
        sa.ForeignKeyConstraint(["locker_id"], ["lockers.id"], name=op.f("fk_deliveries_locker_id_lockers")),
        sa.PrimaryKeyConstraint("id"),
    )
    # Una taquilla nunca tiene dos entregas activas (I1). Las recogidas no cuentan: la taquilla se reutiliza
    op.create_index(
        "uq_deliveries_active_locker",
        "deliveries",
        ["locker_id"],
        unique=True,
        postgresql_where=sa.text(ACTIVE),
    )
    # Un paquete (transportista + referencia) nunca tiene dos entregas activas (I2)
    op.create_index(
        "uq_deliveries_active_package",
        "deliveries",
        ["carrier", "tracking_ref"],
        unique=True,
        postgresql_where=sa.text(ACTIVE),
    )


def downgrade() -> None:
    """Borra los índices y la tabla de entregas (el CHECK y la FK se van con la tabla)."""
    op.drop_index("uq_deliveries_active_package", table_name="deliveries", postgresql_where=sa.text(ACTIVE))
    op.drop_index("uq_deliveries_active_locker", table_name="deliveries", postgresql_where=sa.text(ACTIVE))
    op.drop_table("deliveries")
