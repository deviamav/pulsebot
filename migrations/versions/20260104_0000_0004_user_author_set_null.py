"""Soften user-author FKs so users can be hard-deleted.

Until now ``comments.author_id`` and ``attachments.uploaded_by`` had
``ON DELETE RESTRICT``, which made deleting an active designer
impossible the moment they posted a single comment or file in a
shared task.

UI never relies on the author's *name* — comments are anonymised by
``author_role`` and attachments don't reference the uploader at all
— so we can safely convert these FKs to ``ON DELETE SET NULL`` and
make the columns nullable.  After a delete the corresponding rows
keep their content but show "автор удалён" semantics implicitly.

Revision ID: 0004_user_author_set_null
Revises: 0003_drop_closed_status
Create Date: 2026-01-04 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_user_author_set_null"
down_revision: Union[str, Sequence[str], None] = "0003_drop_closed_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- comments.author_id ------------------------------------------------
    op.drop_constraint(
        "fk_comments_author_id_users", "comments", type_="foreignkey"
    )
    op.alter_column("comments", "author_id", existing_type=sa.Integer(), nullable=True)
    op.create_foreign_key(
        "fk_comments_author_id_users",
        "comments",
        "users",
        ["author_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # --- attachments.uploaded_by ------------------------------------------
    op.drop_constraint(
        "fk_attachments_uploaded_by_users", "attachments", type_="foreignkey"
    )
    op.alter_column(
        "attachments", "uploaded_by", existing_type=sa.Integer(), nullable=True
    )
    op.create_foreign_key(
        "fk_attachments_uploaded_by_users",
        "attachments",
        "users",
        ["uploaded_by"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Rolling back is only possible when there are no orphan rows
    # (author_id IS NULL). We refuse to coerce data here.
    op.drop_constraint(
        "fk_attachments_uploaded_by_users", "attachments", type_="foreignkey"
    )
    op.alter_column(
        "attachments", "uploaded_by", existing_type=sa.Integer(), nullable=False
    )
    op.create_foreign_key(
        "fk_attachments_uploaded_by_users",
        "attachments",
        "users",
        ["uploaded_by"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "fk_comments_author_id_users", "comments", type_="foreignkey"
    )
    op.alter_column("comments", "author_id", existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key(
        "fk_comments_author_id_users",
        "comments",
        "users",
        ["author_id"],
        ["id"],
        ondelete="RESTRICT",
    )
