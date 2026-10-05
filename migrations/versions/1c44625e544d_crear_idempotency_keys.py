"""crear idempotency_keys

Revision ID: 1c44625e544d
Revises: fc2ffe8da1fd
Create Date: 2026-10-05 18:09:10.859476

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "1c44625e544d"
down_revision: str | Sequence[str] | None = "fc2ffe8da1fd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Crea la tabla de claves de idempotencia, con la PK compuesta por transportista y clave."""
    op.create_table(
        "idempotency_keys",
        sa.Column("carrier", sa.String(length=100), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        # NULL solo mientras dura la transacción de la reserva: se rellena antes de confirmar
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # La clave es por transportista: dos transportistas pueden usar la misma sin interferir
        sa.PrimaryKeyConstraint("carrier", "key", name="pk_idempotency_keys"),
    )


def downgrade() -> None:
    """Borra la tabla de claves de idempotencia (la PK se va con la tabla)."""
    op.drop_table("idempotency_keys")
