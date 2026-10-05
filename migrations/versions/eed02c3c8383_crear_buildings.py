"""crear buildings

Revision ID: eed02c3c8383
Revises:
Create Date: 2026-10-05 11:44:10.923159

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "eed02c3c8383"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Crea la tabla de edificios. Sin country: se añade en una migración posterior, con datos (§5.8)."""
    op.create_table(
        "buildings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Borra la tabla de edificios."""
    op.drop_table("buildings")
