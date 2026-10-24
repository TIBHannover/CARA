"""Pool depths per encoder: pool.encoders (fused by reciprocal rank fusion) becomes pool.depths (a union)

Revision ID: 8c3d1f6a2b57
Revises: 5b1e7c2a9f40
Create Date: 2026-10-24 08:00:00

"""

import json
from collections.abc import Callable, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "8c3d1f6a2b57"
down_revision: str | Sequence[str] | None = "5b1e7c2a9f40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rewrite(change: Callable[[dict[str, Any]], bool]) -> None:
    connection = op.get_bind()
    for study_id, settings in connection.execute(sa.text("SELECT id, settings FROM studies")).all():
        pool = settings.get("pool", {})
        if change(pool):
            connection.execute(
                sa.text("UPDATE studies SET settings = CAST(:settings AS jsonb) WHERE id = :id"),
                {"settings": json.dumps(settings), "id": study_id},
            )


def _to_depths(pool: dict[str, Any]) -> bool:
    if "encoders" not in pool:
        return False
    encoders = pool.pop("encoders") or []
    depth = pool.get("k") or 200
    pool["depths"] = {name: depth for name in encoders}
    return True


def _to_encoders(pool: dict[str, Any]) -> bool:
    if "depths" not in pool:
        return False
    pool["encoders"] = list(pool.pop("depths") or {})
    return True


def upgrade() -> None:
    """Apply this migration: each fused encoder pools as deep as the study's k."""
    _rewrite(_to_depths)


def downgrade() -> None:
    """Undo this migration: the depths are lost; the encoders are fused again."""
    _rewrite(_to_encoders)
