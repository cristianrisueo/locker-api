"""crear outbox_events

Revision ID: afd946b9bb78
Revises: a9fb76835f0f
Create Date: 2026-10-05 18:45:20.137377

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "afd946b9bb78"
down_revision: str | Sequence[str] | None = "a9fb76835f0f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Crea la tabla de eventos pendientes de enviar. Sin índices: solo guarda pendientes y muertos (§5.6)."""
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        # Intentos de envío fallidos: un evento nuevo empieza en 0
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        # Cuándo se puede volver a intentar: un evento nuevo, ya. NULL = evento muerto, el worker ya no lo toma
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Borra la tabla de eventos (y con ella los eventos pendientes y muertos que quedaran)."""
    op.drop_table("outbox_events")
