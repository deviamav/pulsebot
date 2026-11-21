"""Attachment ORM model."""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.task import Task
    from app.db.models.user import User


class Attachment(Base, TimestampMixin):
    """A file attachment stored as a Telegram ``file_id``."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    telegram_file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(127), nullable=True)
    media_type: Mapped[str] = mapped_column(String(32), nullable=False)
    file_unique_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    uploaded_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    task: Mapped["Task"] = relationship("Task", back_populates="attachments")
    uploader: Mapped["User | None"] = relationship("User", lazy="joined")

    def __repr__(self) -> str:
        return (
            f"<Attachment id={self.id} task_id={self.task_id} "
            f"media_type={self.media_type}>"
        )
