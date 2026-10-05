"""crear lockers

Revision ID: 8438a2b81939
Revises: eed02c3c8383
Create Date: 2026-10-05 11:46:00.226261

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8438a2b81939"
down_revision: str | Sequence[str] | None = "eed02c3c8383"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Crea la tabla de taquillas, con sus restricciones y el índice parcial de taquillas libres."""
    op.create_table(
        "lockers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("building_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=10), nullable=False),
        sa.Column("size", sa.String(length=1), nullable=False),
        sa.Column("status", sa.String(length=4), server_default="FREE", nullable=False),
        # Tallas y estados válidos
        sa.CheckConstraint("size IN ('S', 'M', 'L')", name=op.f("ck_lockers_size")),
        sa.CheckConstraint("status IN ('FREE', 'BUSY')", name=op.f("ck_lockers_status")),
        sa.ForeignKeyConstraint(["building_id"], ["buildings.id"], name=op.f("fk_lockers_building_id_buildings")),
        sa.PrimaryKeyConstraint("id"),
        # Una etiqueta no se repite dentro de un edificio
        sa.UniqueConstraint("building_id", "label", name="uq_lockers_building_id_label"),
    )
    # Índice parcial: solo las taquillas libres, por edificio y talla (lo que busca la reserva)
    op.create_index(
        "ix_lockers_free_by_size",
        "lockers",
        ["building_id", "size"],
        unique=False,
        postgresql_where=sa.text("status = 'FREE'"),
    )


def downgrade() -> None:
    """Borra el índice y la tabla de taquillas (las restricciones se van con la tabla)."""
    op.drop_index("ix_lockers_free_by_size", table_name="lockers", postgresql_where=sa.text("status = 'FREE'"))
    op.drop_table("lockers")
