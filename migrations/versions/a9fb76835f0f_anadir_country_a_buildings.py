"""añadir country a buildings

Revision ID: a9fb76835f0f
Revises: 1c44625e544d
Create Date: 2026-10-05 18:15:11.784745

Migración con datos: la tabla ya tiene edificios, así que country no se puede añadir de golpe como NOT NULL
(las filas existentes no tendrían valor y el ALTER fallaría). Sigue el patrón expand → backfill → contract:
primero se añade la columna admitiendo NULL, luego se rellena, y al final se exige.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9fb76835f0f"
down_revision: str | Sequence[str] | None = "1c44625e544d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Añade country a buildings sin perder los edificios existentes: todos quedan en ES."""

    # Expand: columna nueva, todavía admite NULL para no fallar con los edificios que ya existen
    op.add_column("buildings", sa.Column("country", sa.String(length=2), nullable=True))

    # Backfill: todos los edificios anteriores a esta migración están en España
    op.execute("UPDATE buildings SET country = 'ES'")

    # Contract: ya relleno, se exige, y solo admite dos letras mayúsculas
    op.alter_column("buildings", "country", existing_type=sa.String(length=2), nullable=False)
    op.create_check_constraint(op.f("ck_buildings_country_format"), "buildings", "country ~ '^[A-Z]{2}$'")


def downgrade() -> None:
    """Quita el CHECK y la columna country. Los edificios se conservan, sin su país."""
    op.drop_constraint(op.f("ck_buildings_country_format"), "buildings", type_="check")
    op.drop_column("buildings", "country")
