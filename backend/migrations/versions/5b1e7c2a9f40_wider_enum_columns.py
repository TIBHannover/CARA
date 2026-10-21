"""Wider enum columns: room for new roles, sources and action kinds (the adjudicator role)

Revision ID: 5b1e7c2a9f40
Revises: d792db67105e
Create Date: 2026-10-21 12:30:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5b1e7c2a9f40"
down_revision: str | Sequence[str] | None = "d792db67105e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = [("study_members", "role"), ("judgments", "source"), ("actions", "kind"), ("actions", "source")]


def upgrade() -> None:
    """Apply this migration."""
    for table, column in COLUMNS:
        op.alter_column(table, column, type_=sa.String(32))


def downgrade() -> None:
    """Undo this migration; fails while a value longer than the old width is stored."""
    widths = {"role": 9, "source": 10, "kind": 11}
    for table, column in COLUMNS:
        op.alter_column(table, column, type_=sa.String(widths[column]))
