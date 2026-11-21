"""Migrate away from the CLOSED task status.

After UX feedback the team decided to keep a single terminal status
(``DONE``).  Any task that was previously ``CLOSED`` gets re-mapped to
``DONE`` so existing data stays consistent.

Revision ID: 0003_drop_closed_status
Revises: 0002_invite_codes
Create Date: 2026-01-03 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0003_drop_closed_status"
down_revision: Union[str, Sequence[str], None] = "0002_invite_codes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Status is stored as plain text (``native_enum=False``); no enum
    # type rewrite is required — just rewrite the data.
    op.execute("UPDATE tasks SET status = 'DONE' WHERE status = 'CLOSED'")


def downgrade() -> None:
    # Best-effort rollback: we can't tell ex-CLOSED rows apart anymore.
    # No-op keeps the migration reversible without losing data.
    pass
