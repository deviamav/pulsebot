"""Task ORM model."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.db.models.enums import Priority, TaskStatus

if TYPE_CHECKING:
    from app.db.models.attachment import Attachment
    from app.db.models.comment import Comment
    from app.db.models.user import User


class Task(Base, TimestampMixin):
    """A design task in the system."""

    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_status_deadline", "status", "deadline"),
        Index("ix_tasks_designer_status", "designer_id", "status"),
        Index("ix_tasks_customer_status", "customer_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, name="task_status", native_enum=False, length=32),
        nullable=False,
        default=TaskStatus.NEW,
    )
    priority: Mapped[Priority] = mapped_column(
        SAEnum(Priority, name="task_priority", native_enum=False, length=16),
        nullable=False,
        default=Priority.MEDIUM,
    )

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    designer_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    reminder_24h_sent: Mapped[bool] = mapped_column(default=False, nullable=False)
    reminder_2h_sent: Mapped[bool] = mapped_column(default=False, nullable=False)
    reminder_overdue_sent: Mapped[bool] = mapped_column(default=False, nullable=False)

    customer: Mapped["User"] = relationship(
        "User", back_populates="customer_tasks", foreign_keys=[customer_id]
    )
    designer: Mapped["User | None"] = relationship(
        "User", back_populates="designer_tasks", foreign_keys=[designer_id]
    )
    comments: Mapped[list["Comment"]] = relationship(
        "Comment",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="Comment.created_at",
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        "Attachment",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="Attachment.created_at",
    )

    def __repr__(self) -> str:
        return f"<Task id={self.id} status={self.status.value} title={self.title!r}>"
