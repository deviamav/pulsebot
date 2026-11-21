"""Comment ORM model."""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.db.models.enums import Role

if TYPE_CHECKING:
    from app.db.models.task import Task
    from app.db.models.user import User


class Comment(Base, TimestampMixin):
    """A comment on a task, attributed only by role to preserve anonymity."""

    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    author_role: Mapped[Role] = mapped_column(
        SAEnum(Role, name="user_role", native_enum=False, length=32),
        nullable=False,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)

    task: Mapped["Task"] = relationship("Task", back_populates="comments")
    author: Mapped["User | None"] = relationship("User", lazy="joined")

    def __repr__(self) -> str:
        return (
            f"<Comment id={self.id} task_id={self.task_id} "
            f"role={self.author_role.value}>"
        )
