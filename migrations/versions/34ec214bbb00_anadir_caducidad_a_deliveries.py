"""añadir caducidad a deliveries

Revision ID: 34ec214bbb00
Revises: afd946b9bb78
Create Date: 2026-10-06 10:12:40.271903

Migración con datos: la tabla puede tener reservas pendientes, y desde aquí toda reserva pendiente necesita un plazo
(expires_at). Sigue el patrón expand → backfill → contract: primero se añade la columna admitiendo NULL, luego se da
plazo a las pendientes que ya existían, y al final se exige con un CHECK y se admite el estado EXPIRED.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "34ec214bbb00"
down_revision: str | Sequence[str] | None = "afd946b9bb78"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Estados válidos de una entrega antes y después de esta migración
OLD_STATUSES = "status IN ('PENDING', 'DEPOSITED', 'PICKED_UP')"
NEW_STATUSES = "status IN ('PENDING', 'DEPOSITED', 'PICKED_UP', 'EXPIRED')"

# Condición del índice parcial: solo las reservas pendientes pueden caducar
PENDING = "status = 'PENDING'"


def upgrade() -> None:
    """Añade el plazo de las reservas sin perder las pendientes: las que ya existían caducan dentro de 30 minutos."""

    # Expand: columna nueva, admite NULL. Solo importa mientras la entrega está PENDING
    op.add_column("deliveries", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))

    # Backfill: las reservas pendientes que ya existían reciben 30 minutos desde ahora. Es un valor fijo: una
    # migración no lee la configuración (RESERVATION_TTL_SECONDS). Las demás entregas se quedan en NULL
    op.execute("UPDATE deliveries SET expires_at = now() + interval '30 minutes' WHERE status = 'PENDING'")

    # Contract: el CHECK de estados pasa a admitir EXPIRED (se sustituye: un CHECK no se modifica)...
    op.drop_constraint(op.f("ck_deliveries_status"), "deliveries", type_="check")
    op.create_check_constraint(op.f("ck_deliveries_status"), "deliveries", NEW_STATUSES)
    # ... toda reserva pendiente tiene plazo...
    op.create_check_constraint(
        op.f("ck_deliveries_pending_has_expiry"), "deliveries", "status <> 'PENDING' OR expires_at IS NOT NULL"
    )
    # ... y un índice parcial sostiene la búsqueda de reservas vencidas del worker (§7.13)
    op.create_index(
        "ix_deliveries_pending_expiry", "deliveries", ["expires_at"], unique=False, postgresql_where=sa.text(PENDING)
    )


def downgrade() -> None:
    """
    Quita el índice, el CHECK nuevo y la columna, y restaura el CHECK de estados antiguo.
    Pérdida asumida: el CHECK antiguo no admite EXPIRED, así que antes las entregas caducadas pasan a PICKED_UP.
    No se pueden dejar en PENDING: volverían a ser activas y ocuparían su taquilla, que ya está libre
    """
    op.drop_index("ix_deliveries_pending_expiry", table_name="deliveries", postgresql_where=sa.text(PENDING))
    op.drop_constraint(op.f("ck_deliveries_pending_has_expiry"), "deliveries", type_="check")
    op.drop_constraint(op.f("ck_deliveries_status"), "deliveries", type_="check")
    op.execute("UPDATE deliveries SET status = 'PICKED_UP' WHERE status = 'EXPIRED'")
    op.create_check_constraint(op.f("ck_deliveries_status"), "deliveries", OLD_STATUSES)
    op.drop_column("deliveries", "expires_at")
