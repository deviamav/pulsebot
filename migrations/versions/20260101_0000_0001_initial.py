"""Initial schema: users, tasks, comments, attachments.

Revision ID: 0001_initial
Revises:
Create Date: 2026-01-01 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "role",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("telegram_id", name=op.f("uq_users_telegram_id")),
    )
    op.create_index(
        op.f("ix_users_telegram_id"), "users", ["telegram_id"], unique=False
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("designer_id", sa.Integer(), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reminder_24h_sent", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "reminder_2h_sent", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "reminder_overdue_sent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["users.id"],
            name=op.f("fk_tasks_customer_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["designer_id"],
            ["users.id"],
            name=op.f("fk_tasks_designer_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_index(
        op.f("ix_tasks_customer_id"), "tasks", ["customer_id"], unique=False
    )
    op.create_index(
        op.f("ix_tasks_designer_id"), "tasks", ["designer_id"], unique=False
    )
    op.create_index(
        "ix_tasks_status_deadline", "tasks", ["status", "deadline"], unique=False
    )
    op.create_index(
        "ix_tasks_designer_status", "tasks", ["designer_id", "status"], unique=False
    )
    op.create_index(
        "ix_tasks_customer_status", "tasks", ["customer_id", "status"], unique=False
    )

    op.create_table(
        "comments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("author_role", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_comments_task_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_comments_author_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comments")),
    )
    op.create_index(op.f("ix_comments_task_id"), "comments", ["task_id"], unique=False)

    op.create_table(
        "attachments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("telegram_file_id", sa.String(length=255), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=127), nullable=True),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("file_unique_id", sa.String(length=128), nullable=True),
        sa.Column("uploaded_by", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_attachments_task_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name=op.f("fk_attachments_uploaded_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attachments")),
    )
    op.create_index(
        op.f("ix_attachments_task_id"), "attachments", ["task_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_attachments_task_id"), table_name="attachments")
    op.drop_table("attachments")

    op.drop_index(op.f("ix_comments_task_id"), table_name="comments")
    op.drop_table("comments")

    op.drop_index("ix_tasks_customer_status", table_name="tasks")
    op.drop_index("ix_tasks_designer_status", table_name="tasks")
    op.drop_index("ix_tasks_status_deadline", table_name="tasks")
    op.drop_index(op.f("ix_tasks_designer_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_customer_id"), table_name="tasks")
    op.drop_table("tasks")

    op.drop_index(op.f("ix_users_telegram_id"), table_name="users")
    op.drop_table("users")
