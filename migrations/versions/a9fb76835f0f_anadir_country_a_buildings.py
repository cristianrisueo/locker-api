"""añadir country a buildings

Revision ID: a9fb76835f0f
Revises: 1c44625e544d
Create Date: 2026-10-05 18:15:11.784745

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "a9fb76835f0f"
down_revision: str | Sequence[str] | None = "1c44625e544d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Esqueleto: todavía no añade country."""


def downgrade() -> None:
    """Esqueleto: no hay nada que deshacer."""
