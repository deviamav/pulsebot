"""invite_codes table.

Revision ID: 0002_invite_codes
Revises: 0001_initial
Create Date: 2026-01-02 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_invite_codes"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "invite_codes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by_id", sa.Integer(), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_revoked", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_invite_codes_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["used_by_id"],
            ["users.id"],
            name=op.f("fk_invite_codes_used_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invite_codes")),
        sa.UniqueConstraint("code", name=op.f("uq_invite_codes_code")),
    )
    op.create_index(
        op.f("ix_invite_codes_code"), "invite_codes", ["code"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_invite_codes_code"), table_name="invite_codes")
    op.drop_table("invite_codes")
